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
from auto_fmu.manifest import sha256_file
from auto_fmu.metrics import regression_metrics
from auto_fmu.readiness import ReadinessResult
from auto_fmu.reporting import table_to_markdown
from auto_fmu.status import RunStatus


TABLE_COLUMNS = ["time_s", "Tin_C", "Tout_meas_C", "Twb_C", "TRan_C", "TAppAct_C", "mdot_cell_kgps", "y_used", "fanHz", "fans_on_count", "Q_flow_W", "PFan_meas_W"]
OUTPUTS = ["TOut_m", "TOut_s", "Q_m", "Q_s", "P_m", "P_s"]


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


def scale_total_outputs(frame: pd.DataFrame, factor: float = 2.0) -> pd.DataFrame:
    scaled = frame.copy()
    scaled["Q_s"] = scaled["Q_s"] * factor
    scaled["P_s"] = scaled["P_s"] * factor
    return scaled


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
        source_table = build_ct_table(_read(ct_path), wet, [self._flow(path) for path in flow_paths])
        self.canonical, self.time_mapping = compress_full_period(source_table)
        self.table_file = self.device_dir / "prepare" / "CT_data.txt"
        _write_table(self.table_file, self.canonical)
        write_csv(self.device_dir / "prepare" / "canonical.csv", self.canonical)
        write_csv(self.device_dir / "prepare" / "time_mapping.csv", self.time_mapping)
        write_csv(self.device_dir / "prepare" / "adapter_qa.csv", pd.DataFrame([{"equipment_id": self.context.device["id"], "rows_valid": len(self.canonical), "flow_sources": len(flow_paths)}]))

    def check_readiness(self) -> ReadinessResult:
        minimum = int(self.context.device.get("readiness", {}).get("min_valid_rows", 288))
        reasons = [] if len(self.canonical) >= minimum else [f"requires at least {minimum} valid rows; got {len(self.canonical)}"]
        return ReadinessResult(not reasons, reasons, {"rows_valid": len(self.canonical), "minimum_rows": minimum})

    def _base(self) -> dict[str, Any]:
        return {
            "table_path": self.table_file.resolve().as_posix(),
            "m_flow_nominal": float(self.canonical["mdot_cell_kgps"].median()),
            "TAirInWB_nominal": float(self.canonical["Twb_C"].median() + 273.15),
            "TWatIn_nominal": float(self.canonical["Tin_C"].median() + 273.15),
            "TWatOut_nominal": float(self.canonical["Tout_meas_C"].median() + 273.15),
            "yMin": 0.05,
            "fraFreCon": 0.1,
        }

    def _simulate(self, candidate: dict[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
        from fmpy import simulate_fmu

        model = str(candidate["model"])
        fmu = resolve_path(self.context.config, candidate["fmu_path"])
        parameters = pd.read_csv(resolve_path(self.context.config, candidate["parameter_csv"]))
        selected = parameters[(parameters["tower"] == self.context.device["id"]) & (parameters["model"] == model)].iloc[0].dropna().to_dict()
        values = york_values(self._base(), selected) if model == "YorkCalc" else merkel_values(self._base(), selected)
        snapshot = inspect_fmu(fmu)
        values = {name: value for name, value in values.items() if name in snapshot.variables}
        result = simulate_fmu(
            str(fmu),
            start_values=values,
            output=OUTPUTS,
            stop_time=float(self.canonical["time_s"].iloc[-1]),
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
        self._write_json(
            self.device_dir / "fmu" / f"{model}_external_fmu_reference.json",
            {"mode": "external_reference", "path": str(fmu), "sha256": sha256_file(fmu), "interface": {"outputs": list(snapshot.outputs), "parameters": list(snapshot.parameters)}, "smoke": {"status": "passed", "rows": len(frame)}},
        )
        return frame, rows, values

    def calibrate(self) -> None:
        self.series = {}
        self.metrics = {}
        self.parameters = {}
        self.errors = []
        flat_rows = []
        for candidate in self.context.device.get("candidates", []):
            model = str(candidate["model"])
            try:
                frame, rows, values = self._simulate(candidate)
                self.series[model], self.metrics[model], self.parameters[model] = frame, rows, values
                flat_rows.extend({"candidate": model, **row} for row in rows)
            except Exception as exc:
                self.errors.append(f"{model}: {exc}")
        if not self.metrics:
            raise ValueError("all cooling tower candidates failed: " + "; ".join(self.errors))
        self.selected_candidate = min(self.metrics, key=lambda model: sum(float(row["CVRMSE_pct"]) for row in self.metrics[model]))
        write_csv(self.device_dir / "calibrate" / "all_candidate_metrics.csv", pd.DataFrame(flat_rows))
        write_csv(self.device_dir / "calibrate" / "parameters.csv", pd.DataFrame([{"candidate": model, "start_values": json.dumps(values, sort_keys=True)} for model, values in self.parameters.items()]))
        self._write_json(self.device_dir / "selected_model.json", {"candidate": self.selected_candidate})

    def validate(self) -> None:
        self.metric_rows = [{"candidate": self.selected_candidate, **row} for row in self.metrics[self.selected_candidate]]
        write_csv(self.device_dir / "validate" / "full_period_metrics.csv", pd.DataFrame(self.metric_rows))
        write_csv(self.device_dir / "validate" / "time_series.csv", self.series[self.selected_candidate])

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
