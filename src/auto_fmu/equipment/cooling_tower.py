from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any, Iterable

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


TABLE_COLUMNS = ["time_s", "Tin_C", "Tout_meas_C", "Twb_C", "TRan_C", "TAppAct_C", "mdot_cell_kgps", "y_used", "fanHz", "fans_on_count", "Q_flow_W", "PFan_meas_W"]
OUTPUTS = ["TOut_m", "TOut_s", "Q_m", "Q_s", "P_m", "P_s"]
WINDOW_FEATURES = ["TRan_C", "TAppAct_C", "mdot_cell_kgps", "y_used", "PFan_meas_W", "Q_flow_W"]
DEFAULT_MERKEL_CWAT = {
    "merkel.UACor.cWatFra[1]": 0.1082,
    "merkel.UACor.cWatFra[2]": 1.667,
    "merkel.UACor.cWatFra[3]": -0.7713,
}


def _find(columns: Iterable[str], tokens: Iterable[str]) -> str | None:
    lowered = [token.lower() for token in tokens]
    return next((column for column in columns if all(token in column.lower() for token in lowered)), None)


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["DateTime"] = pd.to_datetime(frame["DateTime"], errors="coerce")
    return frame.dropna(subset=["DateTime"]).sort_values("DateTime")


def compress_full_period(source: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = source.copy()
    mapping = pd.DataFrame({"source_time_s": work["time_s"].to_numpy(float)})
    work["time_s"] = np.arange(len(work), dtype=float) * 300.0
    return work, mapping


def contiguous_runs(source: pd.DataFrame, step_seconds: float = 300.0) -> list[tuple[int, int]]:
    if source.empty:
        return []
    runs = []
    start = 0
    previous = float(source["time_s"].iloc[0])
    for index, value in enumerate(source["time_s"].iloc[1:], start=1):
        current = float(value)
        if abs(current - previous - step_seconds) > 1e-6:
            runs.append((start, index - 1))
            start = index
        previous = current
    runs.append((start, len(source) - 1))
    return runs


def select_calibration_window(source: pd.DataFrame, rows: int = 288, stride: int = 12) -> tuple[pd.DataFrame, dict[str, Any]]:
    features = [column for column in WINDOW_FEATURES if column in source]
    candidates = []
    if features:
        full_mean = source[features].mean()
        scale = source[features].std().replace(0.0, 1.0).fillna(1.0)
    for run_start, run_end in contiguous_runs(source):
        if run_end - run_start + 1 < rows:
            continue
        for start in range(run_start, run_end - rows + 2, stride):
            score = float(((source.iloc[start : start + rows][features].mean() - full_mean).abs() / scale).mean()) if features else 0.0
            candidates.append((score, start, start + rows - 1))
    if not candidates:
        raise ValueError(f"cooling tower requires a contiguous {rows}-row calibration window")
    score, start, end = min(candidates, key=lambda candidate: (candidate[0], -candidate[1]))
    window = source.iloc[start : end + 1].copy()
    source_start_time = float(window["time_s"].iloc[0])
    source_end_time = float(window["time_s"].iloc[-1])
    window["time_s"] = np.arange(len(window), dtype=float) * 300.0
    return window, {
        "representative_score": score,
        "source_start_row": start,
        "source_end_row": end,
        "source_start_time_s": source_start_time,
        "source_end_time_s": source_end_time,
        "rows": len(window),
    }


def scale_total_outputs(frame: pd.DataFrame, factor: float = 2.0) -> pd.DataFrame:
    scaled = frame.copy()
    scaled["Q_s"] = scaled["Q_s"] * factor
    scaled["P_s"] = scaled["P_s"] * factor
    return scaled


def build_thermal_candidates(model: str, base: dict[str, Any]) -> list[dict[str, float]]:
    if model == "YorkCalc":
        approaches = [max(0.2, float(base["TApp_nominal"]) * factor) for factor in (0.25, 0.5, 0.75, 1.0, 1.25)]
        ranges = [max(0.3, float(base["TRan_nominal"]) * factor) for factor in (0.6, 0.85, 1.0, 1.2)]
        return [{"TApp_nominal": approach, "TRan_nominal": tower_range} for approach, tower_range in itertools.product(approaches, ranges)]
    if model == "Merkel":
        return [
            {
                "merkel.ratWatAir_nominal": ratio,
                **{name: value * scale for name, value in DEFAULT_MERKEL_CWAT.items()},
                "kUA_scale_proxy": scale,
            }
            for ratio, scale in itertools.product((0.8, 1.0, 1.2, 1.5, 1.8), (0.75, 1.0, 1.25, 1.5))
        ]
    raise ValueError(f"unsupported cooling tower model: {model}")


def fan_parameters(model: str, alpha: float, nominal_power: float) -> dict[str, float]:
    relative = (0.0, 0.1, 0.3, 0.6, 1.0)
    prefix = "merkel.fanRelPow.r_P" if model == "Merkel" else "fanRelPow_r_P"
    power_name = "merkel.PFan_nominal" if model == "Merkel" else "PFan_nominal"
    return {power_name: nominal_power, **{f"{prefix}[{index}]": float(value**alpha) for index, value in enumerate(relative, start=1)}, "fan_alpha": alpha}


def estimate_fan_nominal(table: pd.DataFrame, alpha: float, n_fans: float = 2.0) -> float:
    relative = table["y_used"].clip(lower=0.05, upper=1.0) ** alpha
    estimates = (table["PFan_meas_W"] / (n_fans * relative)).replace([np.inf, -np.inf], np.nan).dropna()
    estimates = estimates[estimates > 0.0]
    return float(estimates.median()) if len(estimates) else float(table["PFan_meas_W"].median() / n_fans)


def york_values(base: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    values = {
        "tableFileName": base["table_path"],
        "m_flow_nominal": base["m_flow_nominal"],
        "TAirInWB_nominal": base["TAirInWB_nominal"],
        "TWatIn_nominal_start": base["TWatIn_nominal"],
        "TWatOut_nominal_start": base["TWatOut_nominal"],
        "yMin": base["yMin"],
        "nFan": 1.0,
        "fraFreCon": base["fraFreCon"],
    }
    values.update({key: value for key, value in parameters.items() if key not in {"tower", "model", "score", "timeseries", "nFan"}})
    values["nFan"] = 1.0
    return values


def merkel_values(base: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    values = {
        "Tout1.fileName": base["table_path"],
        "merkel.TAirInWB_nominal": base["TAirInWB_nominal"],
        "merkel.TWatIn_nominal": base["TWatIn_nominal"],
        "merkel.TWatOut_nominal": base["TWatOut_nominal"],
        "merkel.yMin": base["yMin"],
        "merkel.fraFreCon": base["fraFreCon"],
    }
    values.update({key: value for key, value in parameters.items() if key not in {"tower", "model", "score", "timeseries"}})
    return values


def _metric(variable: str, measured: pd.Series, simulated: pd.Series) -> dict[str, Any]:
    if variable == "TOut":
        measured = measured - 273.15
        simulated = simulated - 273.15
    return {"variable": variable, **regression_metrics(measured, simulated)}


def score_metrics(rows: list[dict[str, Any]]) -> float:
    metrics = {row["variable"]: row for row in rows}
    return float(metrics["Q"]["CVRMSE_pct"]) + float(metrics["P"]["CVRMSE_pct"]) + 5.0 * float(metrics["TOut"]["RMSE"])


def _write_table(path: Path, table: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("#1\n")
        handle.write(f"double CT_data({len(table)},{len(table.columns)})\n")
        table.to_csv(handle, header=False, index=False, line_terminator="\n", float_format="%.10g")


def build_ct_table(ct: pd.DataFrame, wet: pd.DataFrame, flows: list[pd.DataFrame], n_fans: int = 2) -> pd.DataFrame:
    tin = _find(ct.columns, ["CDWR", "WTS"])
    tout = _find(ct.columns, ["CDWS", "WTS"])
    power = "P/kw" if "P/kw" in ct else _find(ct.columns, ["P/kw"])
    fan_columns = [column for column in ct if "VSD-CTRL" in column] or [column for column in ct if "VSD-STS" in column]
    if not all((tin, tout, power, fan_columns)):
        raise ValueError("cooling tower input columns are incomplete")
    work = pd.DataFrame(
        {
            "DateTime": ct["DateTime"],
            "Tin_C": pd.to_numeric(ct[tin], errors="coerce"),
            "Tout_meas_C": pd.to_numeric(ct[tout], errors="coerce"),
            "PFan_meas_W": pd.to_numeric(ct[power], errors="coerce") * 1000.0,
        }
    )
    fan = ct[fan_columns].apply(pd.to_numeric, errors="coerce").clip(lower=0.0)
    work["fanHz"] = fan.replace(0.0, np.nan).mean(axis=1).fillna(fan.max(axis=1))
    work["fans_on_count"] = np.where(work["fanHz"] > 1.0, n_fans, 0) if len(fan_columns) == 1 else (fan > 1.0).sum(axis=1).clip(upper=n_fans)
    work["y_used"] = (work["fanHz"] / 50.0).clip(lower=0.0, upper=1.0)
    work = work.merge(wet, on="DateTime", how="left")
    flow_names = []
    for index, flow in enumerate(flows):
        name = f"flow_{index}_kg_s"
        flow_names.append(name)
        work = work.merge(flow.rename(columns={"m_flow_kg_s": name}), on="DateTime", how="left")
    work["m_flow_total_kg_s"] = work[flow_names].sum(axis=1, min_count=1)
    work["mdot_cell_kgps"] = work["m_flow_total_kg_s"] / float(n_fans)
    work["TRan_C"] = work["Tin_C"] - work["Tout_meas_C"]
    work["TAppAct_C"] = work["Tout_meas_C"] - work["Twb_C"]
    work["Q_flow_W"] = work["m_flow_total_kg_s"] * 4186.0 * work["TRan_C"]
    valid_columns = ["Tin_C", "Tout_meas_C", "Twb_C", "mdot_cell_kgps", "y_used", "PFan_meas_W", "Q_flow_W"]
    valid = work[valid_columns].replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    valid &= (work["m_flow_total_kg_s"] > 1.0) & (work["y_used"] > 0.02) & (work["fans_on_count"] > 0)
    valid &= (work["TRan_C"] > 0.05) & (work["TAppAct_C"] >= 0.0) & (work["PFan_meas_W"] > 0.0)
    work = work.loc[valid].copy()
    work["time_s"] = (work["DateTime"] - work["DateTime"].iloc[0]).dt.total_seconds()
    return work[TABLE_COLUMNS]


class CoolingTowerRunner(EquipmentRunner):
    def _flow(self, path: Path) -> pd.DataFrame:
        frame = _read(path)
        column = _find(frame.columns, ["CDW", "WFM"])
        if not column:
            raise ValueError(f"cannot discover CDW flow column: {path}")
        return pd.DataFrame({"DateTime": frame["DateTime"], "m_flow_kg_s": pd.to_numeric(frame[column], errors="coerce").clip(lower=0.0) * 0.997})

    def prepare(self) -> None:
        sources = self.context.device["sources"]
        ct_path = resolve_path(self.context.config, sources["tower_csv"])
        wet_path = resolve_path(self.context.config, sources["wetbulb_csv"])
        flow_paths = [resolve_path(self.context.config, value) for value in sources["flow_csvs"]]
        wet = _read(wet_path)
        wet_column = _find(wet.columns, ["Twb"])
        if not wet_column:
            raise ValueError("cannot discover wet-bulb column")
        wet = pd.DataFrame({"DateTime": wet["DateTime"], "Twb_C": pd.to_numeric(wet[wet_column], errors="coerce")})
        self.source_table = build_ct_table(_read(ct_path), wet, [self._flow(path) for path in flow_paths])
        self.canonical, self.time_mapping = compress_full_period(self.source_table)
        self.table_file = self.device_dir / "prepare" / "CT_data.txt"
        _write_table(self.table_file, self.canonical)
        write_csv(self.device_dir / "prepare" / "canonical.csv", self.canonical)
        write_csv(self.device_dir / "prepare" / "time_mapping.csv", self.time_mapping)
        write_csv(self.device_dir / "prepare" / "adapter_qa.csv", pd.DataFrame([{"equipment_id": self.context.device["id"], "rows_valid": len(self.canonical), "flow_sources": len(flow_paths)}]))

    def check_readiness(self) -> ReadinessResult:
        minimum = int(self.context.device.get("readiness", {}).get("min_valid_rows", 288))
        reasons = [] if len(self.canonical) >= minimum else [f"requires at least {minimum} valid rows; got {len(self.canonical)}"]
        return ReadinessResult(not reasons, reasons, {"rows_valid": len(self.canonical), "minimum_rows": minimum})

    def _base(self, table: pd.DataFrame | None = None, table_file: Path | None = None) -> dict[str, Any]:
        table = self.canonical if table is None else table
        table_file = self.table_file if table_file is None else table_file
        return {
            "table_path": table_file.resolve().as_posix(),
            "m_flow_nominal": float(table["mdot_cell_kgps"].median()),
            "TAirInWB_nominal": float(table["Twb_C"].median() + 273.15),
            "TWatIn_nominal": float(table["Tin_C"].median() + 273.15),
            "TWatOut_nominal": float(table["Tout_meas_C"].median() + 273.15),
            "TApp_nominal": float(table["TAppAct_C"].median()),
            "TRan_nominal": float(table["TRan_C"].median()),
            "yMin": 0.05,
            "nFan": 2.0,
            "fraFreCon": 0.1,
        }

    def _simulate(
        self,
        candidate: dict[str, Any],
        parameters: dict[str, Any],
        *,
        table: pd.DataFrame | None = None,
        table_file: Path | None = None,
        write_reference: bool = False,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
        from fmpy import simulate_fmu

        table = self.canonical if table is None else table
        table_file = self.table_file if table_file is None else table_file
        model = str(candidate["model"])
        fmu = resolve_path(self.context.config, candidate["fmu_path"])
        values = york_values(self._base(table, table_file), parameters) if model == "YorkCalc" else merkel_values(self._base(table, table_file), parameters)
        snapshot = inspect_fmu(fmu)
        values = {name: value for name, value in values.items() if name in snapshot.variables}
        result = simulate_fmu(
            str(fmu),
            start_values=values,
            output=OUTPUTS,
            stop_time=float(table["time_s"].iloc[-1]),
            output_interval=300.0,
            fmi_type="CoSimulation",
        )
        frame = scale_total_outputs(pd.DataFrame.from_records(result))
        scored = frame[frame["time"] >= 300.0]
        rows = [
            _metric("TOut", scored["TOut_m"], scored["TOut_s"]),
            _metric("Q", scored["Q_m"], scored["Q_s"]),
            _metric("P", scored["P_m"], scored["P_s"]),
        ]
        if write_reference:
            self._write_json(
                self.device_dir / "fmu" / f"{model}_external_fmu_reference.json",
                {"mode": "external_reference", "path": str(fmu), "sha256": sha256_file(fmu), "interface": {"outputs": list(snapshot.outputs), "parameters": list(snapshot.parameters)}, "smoke": {"status": "passed", "rows": len(frame)}},
            )
        return frame, rows, values

    def _archived_parameters(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        source = candidate.get("parameter_csv") or self.context.device.get("calibration", {}).get("parameters_csv")
        if not source:
            return None
        parameters = pd.read_csv(resolve_path(self.context.config, source))
        model = str(candidate["model"])
        return parameters[(parameters["tower"] == self.context.device["id"]) & (parameters["model"] == model)].iloc[0].dropna().to_dict()

    def _search_parameters(self, candidate: dict[str, Any], window: pd.DataFrame, window_file: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        model = str(candidate["model"])
        records = []
        successful = []
        for index, parameters in enumerate(build_thermal_candidates(model, self._base(window, window_file))):
            try:
                _, metrics, _ = self._simulate(candidate, parameters, table=window, table_file=window_file)
                score = score_metrics(metrics)
                records.extend({"candidate": model, "stage": "thermal", "search_id": f"thermal_{index}", "score": score, **row} for row in metrics)
                successful.append((float(next(row["CVRMSE_pct"] for row in metrics if row["variable"] == "Q")), float(next(row["RMSE"] for row in metrics if row["variable"] == "TOut")), parameters))
            except Exception as exc:
                records.append({"candidate": model, "stage": "thermal", "search_id": f"thermal_{index}", "error": str(exc)})
        if not successful:
            raise ValueError(f"all {model} thermal search candidates failed")
        thermal = min(successful, key=lambda result: (result[0], result[1]))[2]
        fan_results = []
        alphas = self.context.device.get("calibration", {}).get("fan_alphas", [1.2, 1.6, 2.0, 2.5, 3.0])
        for alpha in alphas:
            parameters = {**thermal, **fan_parameters(model, float(alpha), estimate_fan_nominal(window, float(alpha)))}
            try:
                _, metrics, _ = self._simulate(candidate, parameters, table=window, table_file=window_file)
                score = score_metrics(metrics)
                records.extend({"candidate": model, "stage": "fan", "search_id": f"fan_{alpha}", "score": score, **row} for row in metrics)
                fan_results.append((score, parameters))
            except Exception as exc:
                records.append({"candidate": model, "stage": "fan", "search_id": f"fan_{alpha}", "error": str(exc)})
        return min(fan_results, key=lambda result: result[0])[1] if fan_results else thermal, records

    def calibrate(self) -> None:
        settings = self.context.device.get("calibration", {})
        window, manifest = select_calibration_window(
            self.source_table,
            rows=int(settings.get("window_rows", 288)),
            stride=int(settings.get("window_stride", 12)),
        )
        window_file = self.device_dir / "calibrate" / "calibration_window.txt"
        _write_table(window_file, window)
        write_csv(self.device_dir / "calibrate" / "calibration_window.csv", window)
        self._write_json(self.device_dir / "calibrate" / "calibration_window.json", manifest)
        self.series = {}
        self.metrics = {}
        self.parameters = {}
        self.errors = []
        flat_rows = []
        for candidate in self.context.device.get("candidates", []):
            model = str(candidate["model"])
            try:
                archived = self._archived_parameters(candidate)
                if archived is None:
                    parameters, rows = self._search_parameters(candidate, window, window_file)
                    flat_rows.extend(rows)
                else:
                    parameters = archived
                    flat_rows.append({"candidate": model, "stage": "external_parameters", "search_id": "archived_override"})
                self.parameters[model] = parameters
            except Exception as exc:
                self.errors.append(f"{model}: {exc}")
        if not self.parameters:
            raise ValueError("all cooling tower candidates failed: " + "; ".join(self.errors))
        write_csv(self.device_dir / "calibrate" / "all_candidate_metrics.csv", pd.DataFrame(flat_rows))
        write_csv(self.device_dir / "calibrate" / "parameters.csv", pd.DataFrame([{"candidate": model, "start_values": json.dumps(values, sort_keys=True)} for model, values in self.parameters.items()]))

    def validate(self) -> None:
        for candidate in self.context.device.get("candidates", []):
            model = str(candidate["model"])
            if model not in self.parameters:
                continue
            try:
                frame, rows, _ = self._simulate(candidate, self.parameters[model], write_reference=True)
                self.series[model], self.metrics[model] = frame, rows
            except Exception as exc:
                self.errors.append(f"{model}: {exc}")
        if not self.metrics:
            raise ValueError("all cooling tower full-period validations failed: " + "; ".join(self.errors))
        self.selected_candidate = min(self.metrics, key=lambda model: score_metrics(self.metrics[model]))
        self.metric_rows = [{"candidate": self.selected_candidate, **row} for row in self.metrics[self.selected_candidate]]
        write_csv(self.device_dir / "validate" / "full_period_metrics.csv", pd.DataFrame(self.metric_rows))
        write_csv(self.device_dir / "validate" / "time_series.csv", self.series[self.selected_candidate])
        self._write_json(self.device_dir / "selected_model.json", {"candidate": self.selected_candidate, "score": score_metrics(self.metric_rows)})

    def export_fmu(self) -> ExportResult:
        if self.errors:
            return ExportResult(False, ExportMode.EXTERNAL_REFERENCE, "; ".join(self.errors))
        return ExportResult(True, ExportMode.EXTERNAL_REFERENCE, "external cooling tower FMUs inspected and simulated")

    def regression_rows(self) -> list[dict[str, Any]]:
        return [{"equipment_id": self.context.device["id"], "candidate": row["candidate"], "variable": row["variable"], "value": row["CVRMSE_pct"]} for row in self.metric_rows]

    def report(self, status: RunStatus) -> None:
        output = self.device_dir / "report" / "summary.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"# cooling_tower/{self.context.device['id']}\n\nStatus: `{status.value}`\n\n" + table_to_markdown(pd.DataFrame(self.metric_rows)) + "\n", encoding="utf-8")
