from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from auto_fmu.config import resolve_path
from auto_fmu.equipment.base import EquipmentRunner, write_csv
from auto_fmu.fmu.exporter import ExportMode, ExportResult
from auto_fmu.fmu.inspect import inspect_fmu
from auto_fmu.manifest import sha256_file
from auto_fmu.metrics import regression_metrics
from auto_fmu.readiness import ReadinessResult
from auto_fmu.reporting import table_to_markdown
from auto_fmu.status import RunStatus


CP_WATER = 4186.0
KG_PER_L = 0.997
NUMERIC_FMU_COLUMNS = [
    "time_s",
    "T1In_m_C",
    "T1Out_m_C",
    "T2In_m_C",
    "T2Out_m_C",
    "m1_flow_kg_s",
    "m2_flow_kg_s",
    "Q_m_W",
    "Q1_m_W",
    "Q2_m_W",
    "eps_m",
    "dT_lm_m_C",
    "P_aux_W",
    "active_proxy",
]
PAIR_MAP = {
    "T1Out": ("T1Out_m", "T1Out_s"),
    "T2Out": ("T2Out_m", "T2Out_s"),
    "Q": ("Q_m", "Q_s"),
}


def _find(columns: Iterable[str], tokens: Iterable[str]) -> str | None:
    lowered = [token.lower() for token in tokens]
    return next((column for column in columns if all(token in column.lower() for token in lowered)), None)


def _numeric(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if not column:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["DateTime"] = pd.to_datetime(frame["DateTime"], errors="coerce")
    return frame.dropna(subset=["DateTime"]).sort_values("DateTime")


def _heat_balance(q1: pd.Series, q2: pd.Series) -> pd.Series:
    denominator = pd.concat([q1.abs(), q2.abs()], axis=1).max(axis=1).replace(0.0, np.nan)
    return (q1 - q2).abs() / denominator


def _lmtd(delta_a: pd.Series, delta_b: pd.Series) -> pd.Series:
    close = (delta_a - delta_b).abs() < 1e-9
    valid = (delta_a > 0.0) & (delta_b > 0.0)
    result = (delta_a - delta_b) / np.log((delta_a / delta_b).where(valid, np.nan))
    result = result.where(~close, (delta_a + delta_b) / 2.0)
    return result.where(valid & np.isfinite(result), np.nan)


def select_temperature_mapping(raw: pd.DataFrame) -> tuple[dict[str, str], pd.DataFrame]:
    columns = raw.columns
    discovered = {
        "m1": _find(columns, ["chw", "wfm"]),
        "m2": _find(columns, ["cdw", "wfm"]),
        "chw_rwt": _find(columns, ["chw", "rwt"]),
        "chw_swt": _find(columns, ["chw", "swt"]),
        "cdw_rwt": _find(columns, ["cdw", "rwt"]),
        "cdw_swt": _find(columns, ["cdw", "swt"]),
        "power": "P/kw" if "P/kw" in columns else _find(columns, ["P/kw"]),
    }
    required = ("m1", "m2", "chw_rwt", "chw_swt", "cdw_rwt", "cdw_swt")
    missing = [key for key in required if not discovered[key]]
    if missing:
        return {}, pd.DataFrame([{"status": "blocked_missing_temperature_or_flow_fields", "missing": "; ".join(missing)}])
    m1 = _numeric(raw, discovered["m1"]).abs() * KG_PER_L
    m2 = _numeric(raw, discovered["m2"]).abs() * KG_PER_L
    rows = []
    for t1_in, t1_out in ((discovered["chw_rwt"], discovered["chw_swt"]), (discovered["chw_swt"], discovered["chw_rwt"])):
        for t2_in, t2_out in ((discovered["cdw_rwt"], discovered["cdw_swt"]), (discovered["cdw_swt"], discovered["cdw_rwt"])):
            q1 = m1 * CP_WATER * (_numeric(raw, t1_in) - _numeric(raw, t1_out))
            q2 = m2 * CP_WATER * (_numeric(raw, t2_out) - _numeric(raw, t2_in))
            usable = (m1 > 1.0) & (m2 > 1.0) & (q1 > 5000.0) & (q2 > 5000.0)
            rows.append(
                {
                    "status": "ok",
                    "T1In_m_C": t1_in,
                    "T1Out_m_C": t1_out,
                    "T2In_m_C": t2_in,
                    "T2Out_m_C": t2_out,
                    "usable_rows": int(usable.sum()),
                    "median_balance_rel": float(_heat_balance(q1, q2).loc[usable].median()) if usable.any() else np.nan,
                }
            )
    scored = pd.DataFrame(rows).sort_values(["usable_rows", "median_balance_rel"], ascending=[False, True], na_position="last")
    best = scored.iloc[0]
    mapping = {name: str(best[name]) for name in ("T1In_m_C", "T1Out_m_C", "T2In_m_C", "T2Out_m_C")}
    mapping.update({"m1_flow_lps": str(discovered["m1"]), "m2_flow_lps": str(discovered["m2"]), "P_aux_kW": str(discovered["power"] or "")})
    return mapping, scored


def build_hx_table(raw: pd.DataFrame, pump: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    mapping, scored = select_temperature_mapping(raw)
    if not mapping:
        return pd.DataFrame(columns=["DateTime", *NUMERIC_FMU_COLUMNS]), scored
    out = pd.DataFrame({"DateTime": raw["DateTime"]})
    for name in ("T1In_m_C", "T1Out_m_C", "T2In_m_C", "T2Out_m_C"):
        out[name] = _numeric(raw, mapping[name])
    out["m1_flow_kg_s"] = _numeric(raw, mapping["m1_flow_lps"]).abs() * KG_PER_L
    out["m2_flow_kg_s"] = _numeric(raw, mapping["m2_flow_lps"]).abs() * KG_PER_L
    out["P_aux_W"] = _numeric(raw, mapping["P_aux_kW"]).clip(lower=0.0) * 1000.0
    if pump is not None and not pump.empty:
        frequency = _find(pump.columns, ["vsd", "sts"]) or _find(pump.columns, ["vsd", "ctrl"])
        power = "P/kw" if "P/kw" in pump else _find(pump.columns, ["P/kw"])
        pump_values = pd.DataFrame(
            {
                "DateTime": pump["DateTime"],
                "hxcwp_freq_Hz": _numeric(pump, frequency).clip(lower=0.0),
                "hxcwp_P_W": _numeric(pump, power).clip(lower=0.0) * 1000.0,
            }
        )
        out = out.merge(pump_values, on="DateTime", how="left")
    else:
        out["hxcwp_freq_Hz"] = np.nan
        out["hxcwp_P_W"] = np.nan
    out["P_aux_W"] = out["P_aux_W"].fillna(out["hxcwp_P_W"]).fillna(0.0)
    out["Q1_m_W"] = out["m1_flow_kg_s"] * CP_WATER * (out["T1In_m_C"] - out["T1Out_m_C"])
    out["Q2_m_W"] = out["m2_flow_kg_s"] * CP_WATER * (out["T2Out_m_C"] - out["T2In_m_C"])
    out["Q_m_W"] = (out["Q1_m_W"] + out["Q2_m_W"]) / 2.0
    capacity_min = pd.concat([out["m1_flow_kg_s"] * CP_WATER, out["m2_flow_kg_s"] * CP_WATER], axis=1).min(axis=1)
    out["eps_m"] = (out["Q_m_W"].abs() / (capacity_min * (out["T1In_m_C"] - out["T2In_m_C"]).abs().replace(0.0, np.nan))).clip(0.0, 1.5).fillna(0.0)
    out["dT_lm_m_C"] = _lmtd((out["T1In_m_C"] - out["T2Out_m_C"]).abs(), (out["T1Out_m_C"] - out["T2In_m_C"]).abs()).fillna(0.0)
    out["active_proxy"] = ((out["P_aux_W"] > 1000.0) | (out["hxcwp_freq_Hz"].fillna(0.0) > 1.0) | (out["Q_m_W"].abs() > 5000.0)).astype(float)
    needed = [column for column in NUMERIC_FMU_COLUMNS if column not in ("time_s", "active_proxy")]
    valid = out[needed].replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    valid &= (out["m1_flow_kg_s"] > 1.0) & (out["m2_flow_kg_s"] > 1.0)
    valid &= (out["T1In_m_C"] - out["T1Out_m_C"] > 0.05) & (out["T2Out_m_C"] - out["T2In_m_C"] > 0.05)
    valid &= (out["Q1_m_W"] > 5000.0) & (out["Q2_m_W"] > 5000.0) & (_heat_balance(out["Q1_m_W"], out["Q2_m_W"]) <= 0.5)
    valid &= out["active_proxy"] > 0.0
    work = out.loc[valid].copy()
    work["time_s"] = (work["DateTime"] - work["DateTime"].iloc[0]).dt.total_seconds() if not work.empty else pd.Series(dtype=float)
    return work[["DateTime", *NUMERIC_FMU_COLUMNS]], scored


def validate_finite_table(table: pd.DataFrame) -> None:
    numeric = table[NUMERIC_FMU_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("HX CombiTimeTable contains blank, NaN, or infinite values")


def write_dymola_table(path: Path, table: pd.DataFrame) -> None:
    validate_finite_table(table)
    numeric = table[NUMERIC_FMU_COLUMNS]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("#1\n")
        handle.write(f"double HX_data({len(numeric)},{len(numeric.columns)})\n")
        numeric.to_csv(handle, header=False, index=False, line_terminator="\n", float_format="%.10g")


def iter_chunk_tables(source: pd.DataFrame, chunk_rows: int = 288) -> list[tuple[int, pd.DataFrame]]:
    chunks = []
    for start in range(0, len(source), chunk_rows):
        table = source.iloc[start : start + chunk_rows].copy()
        table["time_s"] = np.arange(len(table), dtype=float) * 300.0
        chunks.append((start, table))
    return chunks


def select_window(table: pd.DataFrame, max_rows: int = 288, stride: int = 12) -> pd.DataFrame:
    if len(table) <= max_rows:
        window = table.iloc[:max_rows].copy()
    else:
        features = ["T1In_m_C", "T1Out_m_C", "T2In_m_C", "T2Out_m_C", "m1_flow_kg_s", "m2_flow_kg_s", "Q_m_W"]
        full_mean = table[features].mean()
        scale = table[features].std().replace(0.0, 1.0).fillna(1.0)
        candidates = []
        for start in range(0, len(table) - max_rows + 1, stride):
            window = table.iloc[start : start + max_rows]
            if np.allclose(np.diff(window["time_s"]), 300.0):
                candidates.append((float(((window[features].mean() - full_mean).abs() / scale).mean()), start))
        start = min(candidates)[1] if candidates else 0
        window = table.iloc[start : start + max_rows].copy()
    window["time_s"] = np.arange(len(window), dtype=float) * 300.0
    return window


def estimate_nominals(table: pd.DataFrame) -> dict[str, float]:
    capacity_min = pd.concat([table["m1_flow_kg_s"] * CP_WATER, table["m2_flow_kg_s"] * CP_WATER], axis=1).min(axis=1)
    eps = (table["Q_m_W"].abs() / (capacity_min * (table["T1In_m_C"] - table["T2In_m_C"]).abs().replace(0.0, np.nan))).clip(0.05, 0.98)
    return {
        "m1_flow_nominal": float(table["m1_flow_kg_s"].quantile(0.95)),
        "m2_flow_nominal": float(table["m2_flow_kg_s"].quantile(0.95)),
        "dp1_nominal": 0.0,
        "dp2_nominal": 0.0,
        "Q_flow_nominal": float(table["Q_m_W"].abs().quantile(0.95)),
        "T_a1_nominal": float(table["T1In_m_C"].median() + 273.15),
        "T_b1_nominal": float(table["T1Out_m_C"].median() + 273.15),
        "T_a2_nominal": float(table["T2In_m_C"].median() + 273.15),
        "T_b2_nominal": float(table["T2Out_m_C"].median() + 273.15),
        "eps": float(eps.median()),
    }


def build_candidate_grid(nominals: Mapping[str, float]) -> list[dict[str, Any]]:
    grid = []
    for q_scale in (0.7, 1.0, 1.3):
        for flow_scale in (0.85, 1.0, 1.15):
            grid.append(
                {
                    "model": "PlateEffectivenessNTU",
                    **{name: float(nominals[name]) for name in ("dp1_nominal", "dp2_nominal", "T_a1_nominal", "T_b1_nominal", "T_a2_nominal", "T_b2_nominal")},
                    "m1_flow_nominal": float(nominals["m1_flow_nominal"]) * flow_scale,
                    "m2_flow_nominal": float(nominals["m2_flow_nominal"]) * flow_scale,
                    "Q_flow_nominal": float(nominals["Q_flow_nominal"]) * q_scale,
                    "n1": 0.8,
                    "n2": 0.8,
                    "r_nominal": 1.0,
                }
            )
    for scale in (0.75, 0.9, 1.0, 1.1, 1.25):
        grid.append(
            {
                "model": "ConstantEffectiveness",
                **{name: float(nominals[name]) for name in ("m1_flow_nominal", "m2_flow_nominal", "dp1_nominal", "dp2_nominal")},
                "eps": float(np.clip(float(nominals["eps"]) * scale, 0.05, 0.98)),
            }
        )
    return grid


def score_metrics(rows: list[dict[str, Any]]) -> float:
    values = {row["variable"]: float(row["CVRMSE_pct"]) for row in rows}
    return 2.0 * values["T1Out"] + 2.0 * values["T2Out"] + values["Q"]


class HeatExchangerRunner(EquipmentRunner):
    def prepare(self) -> None:
        sources = self.context.device["sources"]
        raw_path = resolve_path(self.context.config, sources["hx_csv"])
        pump_path = resolve_path(self.context.config, sources["hxcwp_csv"]) if sources.get("hxcwp_csv") else None
        raw = _read(raw_path)
        pump = _read(pump_path) if pump_path and pump_path.exists() else None
        self.canonical, scored = build_hx_table(raw, pump)
        self.prepare_reasons = []
        if self.canonical.empty and "missing" in scored:
            self.prepare_reasons.append("missing HX temperature or flow fields: " + str(scored.iloc[0]["missing"]))
        write_csv(self.device_dir / "prepare" / "canonical.csv", self.canonical)
        write_csv(self.device_dir / "prepare" / "mapping_candidates.csv", scored)
        self.nominals = estimate_nominals(self.canonical) if not self.canonical.empty else {}
        qa = {"equipment_id": self.context.device["id"], "rows_raw": len(raw), "rows_valid": len(self.canonical), "status": "ready" if not self.canonical.empty else "blocked_no_valid_rows"}
        write_csv(self.device_dir / "prepare" / "adapter_qa.csv", pd.DataFrame([qa]))

    def check_readiness(self) -> ReadinessResult:
        minimum = int(self.context.device.get("readiness", {}).get("min_valid_rows", 288))
        reasons = list(self.prepare_reasons)
        if len(self.canonical) < minimum:
            reasons.append(f"requires at least {minimum} valid rows; got {len(self.canonical)}")
        return ReadinessResult(not reasons, reasons, {"rows_valid": len(self.canonical), "minimum_rows": minimum})

    def _parameters(self) -> list[dict[str, Any]]:
        calibration = self.context.device.get("calibration", {})
        if calibration.get("parameters_csv"):
            source = pd.read_csv(resolve_path(self.context.config, calibration["parameters_csv"]))
            rows = source[source["hx"] == self.context.device["id"]]
            return [row.dropna().to_dict() for _, row in rows.iterrows()]
        return build_candidate_grid(self.nominals)

    def calibrate(self) -> None:
        wanted = {str(candidate["model"]) for candidate in self.context.device.get("candidates", [])}
        self.calibration_metrics = []
        parameters_csv = self.context.device.get("calibration", {}).get("parameters_csv")
        if parameters_csv:
            self.parameters = self._parameters()
        else:
            from fmpy import simulate_fmu

            candidates = {str(candidate["model"]): candidate for candidate in self.context.device.get("candidates", [])}
            window = select_window(self.canonical)
            table_path = self.device_dir / "calibrate" / "representative_window.txt"
            write_dymola_table(table_path, window)
            scored_parameters = []
            for row in self._parameters():
                model = str(row["model"])
                if model not in candidates:
                    continue
                fmu = resolve_path(self.context.config, candidates[model]["fmu_path"])
                snapshot = inspect_fmu(fmu)
                values = {**self._clean_parameters(row), "table_path": table_path.resolve().as_posix()}
                values = {key: value for key, value in values.items() if key in snapshot.variables}
                result = simulate_fmu(str(fmu), start_values=values, output=[name for pair in PAIR_MAP.values() for name in pair], stop_time=float(window["time_s"].iloc[-1]), output_interval=300.0, validate=False)
                frame = pd.DataFrame.from_records(result)
                metrics = [{"candidate": model, "variable": variable, **regression_metrics(frame[measured], frame[simulated])} for variable, (measured, simulated) in PAIR_MAP.items()]
                score = score_metrics(metrics)
                self.calibration_metrics.extend({"score": score, **metric} for metric in metrics)
                scored_parameters.append({"score": score, **row})
            self.parameters = [min((row for row in scored_parameters if row["model"] == model), key=lambda row: float(row["score"])) for model in sorted(wanted)]
        selected = {}
        for row in self.parameters:
            model = str(row["model"])
            if model in wanted and model not in selected:
                selected[model] = row
        if wanted - selected.keys():
            raise ValueError("missing HX candidate parameters: " + ", ".join(sorted(wanted - selected.keys())))
        self.parameters = list(selected.values())
        write_csv(self.device_dir / "calibrate" / "parameters.csv", pd.DataFrame(self.parameters))
        write_csv(self.device_dir / "calibrate" / "all_candidate_metrics.csv", pd.DataFrame(self.calibration_metrics, columns=["candidate", "variable", "CVRMSE_pct", "NMBE_pct", "score"]))

    @staticmethod
    def _clean_parameters(row: Mapping[str, Any]) -> dict[str, Any]:
        skip = {"hx", "candidate_id", "model", "score", "timeseries", "source_start_row", "source_end_row", "rows", "representative_score"}
        return {key: value for key, value in row.items() if key not in skip and not pd.isna(value)}

    def _simulate_model(self, candidate: dict[str, Any], parameter_row: dict[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        from fmpy import simulate_fmu

        model = str(candidate["model"])
        fmu = resolve_path(self.context.config, candidate["fmu_path"])
        snapshot = inspect_fmu(fmu)
        values = self._clean_parameters(parameter_row)
        values = {key: value for key, value in values.items() if key in snapshot.variables}
        frames, manifest, failures = [], [], []
        for chunk_id, (start, table) in enumerate(iter_chunk_tables(self.canonical, int(self.context.device.get("validation", {}).get("chunk_rows", 288))), start=1):
            table_path = self.device_dir / "validate" / "tables" / f"{model}_chunk_{chunk_id:04d}.txt"
            write_dymola_table(table_path, table)
            start_values = {**values, "table_path": table_path.resolve().as_posix()}
            try:
                result = simulate_fmu(str(fmu), start_values=start_values, output=[name for pair in PAIR_MAP.values() for name in pair], stop_time=float(table["time_s"].iloc[-1]), output_interval=300.0, validate=False)
                frame = pd.DataFrame.from_records(result)
                frame["time"] = frame["time"] + float(start * 300)
                frame["chunk_id"] = chunk_id
                frames.append(frame)
                manifest.append({"model": model, "chunk_id": chunk_id, "source_start_row": start, "source_end_row": start + len(table) - 1, "rows": len(table), "status": "passed"})
            except Exception as exc:
                failures.append({"model": model, "chunk_id": chunk_id, "source_start_row": start, "source_end_row": start + len(table) - 1, "rows": len(table), "error_type": type(exc).__name__, "error": str(exc)})
                manifest.append({"model": model, "chunk_id": chunk_id, "source_start_row": start, "source_end_row": start + len(table) - 1, "rows": len(table), "status": "failed"})
        if not frames:
            raise ValueError(f"all {model} validation chunks failed")
        frame = pd.concat(frames, ignore_index=True)
        metrics = [{"candidate": model, "variable": variable, **regression_metrics(frame[measured], frame[simulated])} for variable, (measured, simulated) in PAIR_MAP.items()]
        self._write_json(
            self.device_dir / "fmu" / f"{model}_external_fmu_reference.json",
            {"mode": "external_reference", "path": str(fmu), "sha256": sha256_file(fmu), "interface": {"outputs": list(snapshot.outputs), "parameters": list(snapshot.parameters)}, "smoke": {"status": "passed", "chunks": len(frames)}},
        )
        return frame, metrics, manifest, failures

    def validate(self) -> None:
        self.series, self.metrics, self.chunk_manifest, self.validation_errors = {}, {}, [], []
        candidates = {str(candidate["model"]): candidate for candidate in self.context.device.get("candidates", [])}
        for row in self.parameters:
            model = str(row["model"])
            try:
                frame, metrics, manifest, failures = self._simulate_model(candidates[model], row)
                self.series[model], self.metrics[model] = frame, metrics
                self.chunk_manifest.extend(manifest)
                self.validation_errors.extend(failures)
            except Exception as exc:
                self.validation_errors.append({"model": model, "error_type": type(exc).__name__, "error": str(exc)})
        write_csv(self.device_dir / "validate" / "failed_chunks.csv", pd.DataFrame(self.validation_errors, columns=["model", "chunk_id", "source_start_row", "source_end_row", "rows", "error_type", "error"]))
        write_csv(self.device_dir / "validate" / "chunk_manifest.csv", pd.DataFrame(self.chunk_manifest))
        if not self.metrics:
            raise ValueError("all HX candidates failed validation")
        self.selected_candidate = min(self.metrics, key=lambda model: score_metrics(self.metrics[model]))
        self.metric_rows = self.metrics[self.selected_candidate]
        write_csv(self.device_dir / "validate" / "full_period_metrics.csv", pd.DataFrame([row for rows in self.metrics.values() for row in rows]))
        write_csv(self.device_dir / "validate" / "time_series.csv", self.series[self.selected_candidate])
        self._write_json(self.device_dir / "selected_model.json", {"candidate": self.selected_candidate, "score": score_metrics(self.metric_rows)})

    def export_fmu(self) -> ExportResult:
        if self.validation_errors:
            return ExportResult(False, ExportMode.EXTERNAL_REFERENCE, f"{len(self.validation_errors)} HX validation chunks failed")
        return ExportResult(True, ExportMode.EXTERNAL_REFERENCE, "external HX FMUs inspected and simulated")

    def _write_manifest(self, status: RunStatus) -> None:
        super()._write_manifest(status)
        path = self.device_dir / "manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["chunk_validation"] = {"chunks": len(getattr(self, "chunk_manifest", [])), "failed_chunks": len(getattr(self, "validation_errors", []))}
        self._write_json(path, payload)

    def regression_rows(self) -> list[dict[str, Any]]:
        return [{"equipment_id": self.context.device["id"], "candidate": row["candidate"], "variable": row["variable"], "value": row["CVRMSE_pct"]} for rows in getattr(self, "metrics", {}).values() for row in rows]

    def report(self, status: RunStatus) -> None:
        output = self.device_dir / "report" / "summary.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        metrics = pd.DataFrame([row for rows in getattr(self, "metrics", {}).values() for row in rows])
        details = table_to_markdown(metrics) if not metrics.empty else "_No validation metrics because readiness failed._"
        output.write_text(f"# heat_exchanger/{self.context.device['id']}\n\nStatus: `{status.value}`\n\n" + details + "\n", encoding="utf-8")
