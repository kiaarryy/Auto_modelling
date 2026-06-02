from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from auto_fmu.config import resolve_path
from auto_fmu.equipment.base import EquipmentRunner, write_csv
from auto_fmu.fmu.exporter import ExportMode, ExportResult
from auto_fmu.fmu.inspect import inspect_fmu
from auto_fmu.fmu.runner import build_fmi_input, validate_start_values
from auto_fmu.manifest import sha256_file
from auto_fmu.readiness import ReadinessResult
from auto_fmu.reporting import table_to_markdown
from auto_fmu.status import RunStatus


MODEL_FAMILIES = ("affinity_y3", "speed_poly", "flow_speed_5term")


def _find_column(columns: Iterable[str], includes: Iterable[str]) -> str | None:
    tokens = [token.lower() for token in includes]
    return next((column for column in columns if all(token in column.lower() for token in tokens)), None)


def discover_columns(pump: pd.DataFrame, flow: pd.DataFrame, device: dict[str, Any]) -> dict[str, str]:
    configured = device.get("columns", {})
    timestamp = configured.get("timestamp", "DateTime")
    power = configured.get("power_kw") or ("P/kw" if "P/kw" in pump else _find_column(pump.columns, ["kw"]))
    frequency = configured.get("frequency_hz") or _find_column(pump.columns, ["VSD", "STS"]) or _find_column(pump.columns, ["VSD", "CTRL"])
    flow_tokens = ["CDW", "WFM"] if device.get("source_kind") == "HX" else [device.get("flow_family", ""), "WFM"]
    flow_column = configured.get("flow_lps") or _find_column(flow.columns, flow_tokens)
    discovered = {"timestamp": timestamp, "power_kw": power, "frequency_hz": frequency, "flow_lps": flow_column}
    missing = [name for name, value in discovered.items() if not value]
    if missing:
        raise ValueError(f"cannot discover pump columns: {', '.join(missing)}")
    return discovered


def clean_table(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["m_flow_kg_s", "y_used", "P_meas_W"]
    clean = frame.copy()
    for column in columns:
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    clean = clean.replace([np.inf, -np.inf], np.nan).dropna(subset=columns)
    return clean[(clean["m_flow_kg_s"] > 0.0) & (clean["y_used"] > 0.0) & (clean["P_meas_W"] > 0.0)].copy()


def design_matrix(frame: pd.DataFrame, family: str, m_flow_nominal: float) -> tuple[np.ndarray, list[str]]:
    y = pd.to_numeric(frame["y_used"], errors="coerce").to_numpy(dtype=float)
    phi = pd.to_numeric(frame["m_flow_kg_s"], errors="coerce").to_numpy(dtype=float) / max(m_flow_nominal, 1e-6)
    if family == "affinity_y3":
        return np.column_stack([y**3]), ["c3"]
    if family == "speed_poly":
        return np.column_stack([np.ones_like(y), y, y**3]), ["c0", "c2", "c3"]
    if family == "flow_speed_5term":
        return np.column_stack([np.ones_like(y), phi, y, y**3, phi * y]), ["c0", "c1", "c2", "c3", "c4"]
    raise ValueError(f"unknown pump model family: {family}")


def fit_model_family(frame: pd.DataFrame, family: str) -> dict[str, float | str]:
    clean = clean_table(frame)
    if clean.empty:
        raise ValueError("cannot fit pump model on an empty table")
    m_flow_nominal = float(clean["m_flow_kg_s"].median())
    matrix, names = design_matrix(clean, family, m_flow_nominal)
    measured = clean["P_meas_W"].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(matrix, measured, rcond=None)
    p_nominal = float(max(np.nanmax(np.abs(beta)), np.nanmedian(measured), 1.0))
    parameters: dict[str, float | str] = {
        "family": family,
        "P_nominal": p_nominal,
        "m_flow_nominal": m_flow_nominal,
        "y_min": 0.05,
        "y_max": 1.20,
        "c0": 0.0,
        "c1": 0.0,
        "c2": 0.0,
        "c3": 0.0,
        "c4": 0.0,
    }
    for name, value in zip(names, beta):
        parameters[name] = float(value / p_nominal)
    return parameters


def predict_power(frame: pd.DataFrame, parameters: dict[str, Any]) -> pd.Series:
    y = pd.to_numeric(frame["y_used"], errors="coerce").clip(
        lower=float(parameters.get("y_min", 0.05)),
        upper=float(parameters.get("y_max", 1.20)),
    )
    m_flow = pd.to_numeric(frame["m_flow_kg_s"], errors="coerce").clip(lower=0.0)
    phi = m_flow / max(float(parameters["m_flow_nominal"]), 1e-6)
    relative = (
        float(parameters.get("c0", 0.0))
        + float(parameters.get("c1", 0.0)) * phi
        + float(parameters.get("c2", 0.0)) * y
        + float(parameters.get("c3", 0.0)) * y**3
        + float(parameters.get("c4", 0.0)) * phi * y
    )
    return (float(parameters["P_nominal"]) * relative).clip(lower=0.0)


def pump_metrics(measured: Iterable[float], simulated: Iterable[float]) -> dict[str, float]:
    work = pd.DataFrame({"measured": measured, "simulated": simulated}).replace([np.inf, -np.inf], np.nan).dropna()
    if work.empty:
        raise ValueError("no finite pump metric pairs")
    residual = work["simulated"] - work["measured"]
    rmse = float(np.sqrt(np.mean(residual**2)))
    mean = float(work["measured"].mean())
    total = float(np.sum((work["measured"] - mean) ** 2))
    return {
        "N": int(len(work)),
        "RMSE": rmse,
        "MAE": float(np.mean(np.abs(residual))),
        "CVRMSE_pct": float(rmse / mean * 100.0) if mean else np.nan,
        "NMBE_pct": float(residual.mean() / mean * 100.0) if mean else np.nan,
        "R2": float(1.0 - float(np.sum(residual**2)) / total) if total else np.nan,
    }


def _contiguous_runs(frame: pd.DataFrame, step_seconds: float) -> list[tuple[int, int]]:
    if frame.empty:
        return []
    runs = []
    start = 0
    previous = float(frame["time_s"].iloc[0])
    for index, value in enumerate(frame["time_s"].iloc[1:], start=1):
        current = float(value)
        if abs(current - previous - step_seconds) > 1e-6:
            runs.append((start, index - 1))
            start = index
        previous = current
    runs.append((start, len(frame) - 1))
    return runs


def _window_candidates(frame: pd.DataFrame, rows: int, stride: int, step_seconds: float) -> list[tuple[float, int, int]]:
    features = ["m_flow_kg_s", "y_used", "P_meas_W"]
    if frame.empty:
        return []
    if len(frame) < rows:
        return []
    full = frame[features]
    scale = (full.quantile(0.75) - full.quantile(0.25)).replace(0.0, np.nan)
    scale = scale.fillna(full.std()).replace(0.0, 1.0).fillna(1.0)
    candidates = []
    for run_start, run_end in _contiguous_runs(frame, step_seconds):
        if run_end - run_start + 1 < rows:
            continue
        for start in range(run_start, run_end - rows + 2, stride):
            window = frame.iloc[start : start + rows]
            score = ((window[features].mean() - full.mean()).abs() / scale).mean()
            score += 0.5 * ((window[features].quantile(0.25) - full.quantile(0.25)).abs() / scale).mean()
            score += 0.5 * ((window[features].quantile(0.75) - full.quantile(0.75)).abs() / scale).mean()
            candidates.append((float(score), start, start + rows - 1))
    return sorted(candidates, key=lambda row: row[0])


def select_windows(frame: pd.DataFrame, settings: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = int(settings.get("rows", 288))
    stride = int(settings.get("stride", 12))
    count = int(settings.get("count", 3))
    minimum_separation = int(settings.get("min_separation", 288))
    step_seconds = float(settings.get("step_seconds", 300.0))
    selected: list[tuple[float, int, int]] = []
    for score, start, end in _window_candidates(frame, rows, stride, step_seconds):
        if any(not (end < previous_start - minimum_separation or start > previous_end + minimum_separation) for _, previous_start, previous_end in selected):
            continue
        selected.append((score, start, end))
        if len(selected) >= count:
            break
    windows = []
    manifest = []
    for window_id, (score, start, end) in enumerate(selected, start=1):
        window = frame.iloc[start : end + 1].copy()
        windows.append(window)
        manifest.append(
            {
                "window_id": window_id,
                "representative_score": score,
                "source_start_row": start,
                "source_end_row": end,
                "source_start_timestamp": str(window["timestamp"].iloc[0]),
                "source_end_timestamp": str(window["timestamp"].iloc[-1]),
                "rows": len(window),
            }
        )
    if not windows:
        return frame.iloc[0:0].copy(), pd.DataFrame(manifest)
    result = pd.concat(windows, ignore_index=True)
    result["time_s"] = np.arange(len(result), dtype=float) * step_seconds
    return result, pd.DataFrame(manifest)


class PumpRunner(EquipmentRunner):
    def prepare(self) -> None:
        device = self.context.device
        sources = device["sources"]
        pump_path = resolve_path(self.context.config, sources["pump_csv"])
        flow_path = resolve_path(self.context.config, sources["flow_csv"])
        pump = pd.read_csv(pump_path)
        flow = pd.read_csv(flow_path)
        columns = discover_columns(pump, flow, device)
        timestamp = columns.get("timestamp", "DateTime")
        pump_time = pd.to_datetime(pump[timestamp], errors="coerce")
        flow_time = pd.to_datetime(flow[timestamp], errors="coerce")
        pump_frame = pd.DataFrame(
            {
                "timestamp": pump_time,
                "P_meas_W": pd.to_numeric(pump[columns["power_kw"]], errors="coerce") * float(device.get("power_scale", 1000.0)),
                "freq_Hz": pd.to_numeric(pump[columns["frequency_hz"]], errors="coerce"),
            }
        )
        flow_frame = pd.DataFrame(
            {
                "timestamp": flow_time,
                "m_flow_kg_s": pd.to_numeric(flow[columns["flow_lps"]], errors="coerce") * float(device.get("flow_scale", 0.997)),
            }
        )
        pump_frame = pump_frame.dropna(subset=["timestamp"]).sort_values("timestamp")
        flow_frame = flow_frame.dropna(subset=["timestamp"]).sort_values("timestamp")
        merged = pump_frame.merge(flow_frame, on="timestamp", how="left")
        merged["y_used"] = (merged["freq_Hz"] / float(device.get("frequency_nominal_hz", 50.0))).clip(lower=0.0, upper=1.0)
        merged["time_s"] = (merged["timestamp"] - merged["timestamp"].min()).dt.total_seconds()
        valid = clean_table(merged)
        valid = valid[(valid["P_meas_W"] > float(device.get("power_on_w", 1000.0))) & (valid["freq_Hz"] > float(device.get("frequency_on_hz", 1.0))) & (valid["m_flow_kg_s"] > float(device.get("flow_on_kg_s", 1.0)))].copy()
        self.canonical = valid[["time_s", "timestamp", "m_flow_kg_s", "y_used", "freq_Hz", "P_meas_W"]]
        self.window_table, self.window_manifest = select_windows(self.canonical, device.get("window", {}))
        source_flow = pd.to_numeric(merged["m_flow_kg_s"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        source_flow = source_flow[source_flow > float(device.get("flow_on_kg_s", 1.0))]
        self.flow_p95 = float(source_flow.quantile(0.95)) if len(source_flow) else np.nan
        write_csv(self.device_dir / "prepare" / "canonical.csv", self.canonical)
        write_csv(self.device_dir / "prepare" / "adapter_qa.csv", pd.DataFrame([self._qa_row(len(merged))]))
        write_csv(self.device_dir / "prepare" / "window_manifest.csv", self.window_manifest)
        self._write_json(
            self.device_dir / "prepare" / "source_mapping.json",
            {
                "pump_csv": str(pump_path),
                "pump_sha256": sha256_file(pump_path),
                "flow_csv": str(flow_path),
                "flow_sha256": sha256_file(flow_path),
                "columns": columns,
            },
        )

    def _qa_row(self, rows_raw: int) -> dict[str, Any]:
        return {
            "equipment_id": self.context.device["id"],
            "rows_raw": rows_raw,
            "rows_valid": len(self.canonical),
            "windows_selected": len(self.window_manifest),
            "mapped_flow_p95_kg_s": self.flow_p95,
        }

    def check_readiness(self) -> ReadinessResult:
        settings = self.context.device.get("readiness", {})
        reasons = []
        minimum_rows = int(settings.get("min_valid_rows", 288))
        minimum_windows = int(settings.get("min_windows", 1))
        if len(self.canonical) < minimum_rows:
            reasons.append(f"requires at least {minimum_rows} valid rows; got {len(self.canonical)}")
        if len(self.window_manifest) < minimum_windows:
            reasons.append(f"requires at least {minimum_windows} continuous windows; got {len(self.window_manifest)}")
        flow_threshold = float(settings.get("hxcwp_min_flow_p95", 10.0))
        if self.context.device["id"].startswith("HXCWP") and not bool(settings.get("allow_low_hxcwp_flow", False)):
            if np.isnan(self.flow_p95) or self.flow_p95 < flow_threshold:
                reasons.append(f"mapped flow p95 {self.flow_p95:.3g} kg/s is below HXCWP threshold {flow_threshold:g} kg/s")
        details = self._qa_row(rows_raw=-1)
        return ReadinessResult(ready=not reasons, reasons=reasons, details=details)

    def calibrate(self) -> None:
        candidates = self.context.device.get("candidates", MODEL_FAMILIES)
        rows = []
        self.parameters = {}
        for candidate in candidates:
            parameters = fit_model_family(self.window_table, candidate)
            self.parameters[candidate] = parameters
            calibration = pump_metrics(self.window_table["P_meas_W"], predict_power(self.window_table, parameters))
            full = pump_metrics(self.canonical["P_meas_W"], predict_power(self.canonical, parameters))
            rows.append(
                {
                    "candidate": candidate,
                    **{f"cal_{key}": value for key, value in calibration.items()},
                    **{f"full_{key}": value for key, value in full.items()},
                    **{key: value for key, value in parameters.items() if key != "family"},
                }
            )
        ranked = sorted(rows, key=lambda row: (float(row["full_CVRMSE_pct"]), abs(float(row["full_NMBE_pct"]))))
        self.selected = dict(ranked[0])
        self.selected["overfit_warning"] = bool(
            float(self.selected["full_CVRMSE_pct"])
            > max(3.0 * float(self.selected["cal_CVRMSE_pct"]), float(self.context.device.get("thresholds", {}).get("CVRMSE_pct", 10.0)))
        )
        write_csv(self.device_dir / "calibrate" / "all_candidate_metrics.csv", pd.DataFrame(rows))
        write_csv(
            self.device_dir / "calibrate" / "parameters.csv",
            pd.DataFrame([{"candidate": name, **parameters} for name, parameters in self.parameters.items()]),
        )
        self._write_json(self.device_dir / "selected_model.json", {"candidate": self.selected["candidate"], "parameters": self.parameters[self.selected["candidate"]], "overfit_warning": self.selected["overfit_warning"]})

    def validate(self) -> None:
        candidate = str(self.selected["candidate"])
        simulated = predict_power(self.canonical, self.parameters[candidate])
        metrics = pump_metrics(self.canonical["P_meas_W"], simulated)
        self.metric_rows = [{"candidate": candidate, "variable": "P_W", **metrics}]
        write_csv(self.device_dir / "validate" / "full_period_metrics.csv", pd.DataFrame(self.metric_rows))
        write_csv(
            self.device_dir / "validate" / "time_series.csv",
            pd.DataFrame(
                {
                    "timestamp": self.canonical["timestamp"],
                    "candidate": candidate,
                    "variable": "P_W",
                    "measured": self.canonical["P_meas_W"],
                    "simulated": simulated,
                }
            ),
        )

    def render_modelica(self) -> Path | None:
        if self.export_mode != ExportMode.RENDER_AND_EXPORT:
            return None
        source = Path(__file__).resolve().parents[3] / "models" / "pump" / "PumpEmpiricalPower.mo"
        target = self.device_dir / "modelica" / "generated_model.mo"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        return target

    def export_fmu(self) -> ExportResult:
        result = super().export_fmu()
        if not result.ok or result.mode != ExportMode.RENDER_AND_EXPORT or result.artifact is None:
            return result
        smoke_path = self.device_dir / "fmu" / "smoke.json"
        try:
            from fmpy import simulate_fmu

            candidate = str(self.selected["candidate"])
            parameters = self.parameters[candidate]
            start_values = {key: value for key, value in parameters.items() if key != "family"}
            snapshot = inspect_fmu(result.artifact)
            validate_start_values(snapshot, start_values, allow_fixed_parameters=True)
            expected_inputs = ("m_flow_in", "y_in")
            expected_outputs = ("P_s",)
            missing = sorted((set(expected_inputs) - set(snapshot.inputs)) | (set(expected_outputs) - set(snapshot.outputs)))
            if missing:
                raise ValueError(f"missing FMI variables: {', '.join(missing)}")
            nominal_flow = float(parameters["m_flow_nominal"])
            inputs = build_fmi_input(
                {"time": [0.0, 300.0], "m_flow_in": [nominal_flow, nominal_flow], "y_in": [1.0, 1.0]},
                expected_inputs,
            )
            simulated = simulate_fmu(
                str(result.artifact),
                start_values=start_values,
                input=inputs,
                output=list(expected_outputs),
                stop_time=300.0,
                output_interval=300.0,
            )
            values = pd.to_numeric(pd.Series(simulated["P_s"]), errors="coerce")
            if values.empty or not np.isfinite(values).all():
                raise ValueError("P_s smoke output is empty or non-finite")
            smoke = {"status": "passed", "rows": len(values), "P_s": values.tolist()}
            smoke_path.write_text(json.dumps(smoke, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return ExportResult(True, result.mode, "FMU exported and FMPy smoke passed", result.artifact)
        except Exception as exc:
            smoke_path.write_text(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return ExportResult(False, result.mode, f"FMPy smoke failed: {exc}", result.artifact)

    def regression_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "equipment_id": self.context.device["id"],
                "candidate": row["candidate"],
                "variable": "full_cvrmse_pct",
                "value": row["CVRMSE_pct"],
            }
            for row in self.metric_rows
        ]

    def report(self, status: RunStatus) -> None:
        output = self.device_dir / "report" / "summary.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        body = table_to_markdown(pd.DataFrame(self.metric_rows)) if self.metric_rows else "_No validation metrics: readiness failed._"
        output.write_text(
            f"# pump/{self.context.device['id']}\n\n"
            f"Status: `{status.value}`\n\n"
            f"Readiness reasons: `{'; '.join(self.readiness.reasons) or 'none'}`\n\n"
            + body
            + "\n",
            encoding="utf-8",
        )
