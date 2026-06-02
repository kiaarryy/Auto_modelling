from __future__ import annotations

import json
import math
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


TABLE_COLUMNS = ["Time", "CHWS", "CHWR", "CDWS", "CDWR", "CHW", "CDW", "P/kw", "VSD", "deltaT_chw", "deltaT_cdw", "Q_evap_kW"]


def _numeric(frame: pd.DataFrame, name: str | None, default: float = np.nan) -> pd.Series:
    if not name:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce")


def _sample_seconds(timestamps: pd.Series, default: float = 300.0) -> float:
    differences = pd.to_datetime(timestamps, errors="coerce").sort_values().diff().dt.total_seconds()
    differences = differences[(differences > 0.0) & np.isfinite(differences)]
    return float(differences.median()) if len(differences) else default


def normalize_chiller_frame(raw: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    timestamps = pd.to_datetime(raw[columns["timestamp"]], errors="coerce")
    chws = _numeric(raw, columns["chws_C"])
    chwr = _numeric(raw, columns["chwr_C"])
    cdws = _numeric(raw, columns["cdws_C"])
    cdwr = _numeric(raw, columns["cdwr_C"])
    chw = _numeric(raw, columns["chw_lps"])
    cdw = _numeric(raw, columns["cdw_lps"])
    power = _numeric(raw, columns["power_kw"])
    delta_chw = _numeric(raw, columns.get("delta_chw_C")) if columns.get("delta_chw_C") else chwr - chws
    delta_cdw = _numeric(raw, columns.get("delta_cdw_C")) if columns.get("delta_cdw_C") else cdwr - cdws
    computed_q = chw * 4.186 * delta_chw
    measured_q = _numeric(raw, columns.get("qeva_kw"))
    qe = measured_q.where(measured_q.notna(), computed_q)
    normalized = pd.DataFrame(
        {
            "timestamp": timestamps,
            "CHWS": chws,
            "CHWR": chwr,
            "CDWS": cdws,
            "CDWR": cdwr,
            "CHW": chw,
            "CDW": cdw,
            "P/kw": power,
            "VSD": _numeric(raw, columns.get("vsd"), 1.0).fillna(1.0),
            "deltaT_chw": delta_chw,
            "deltaT_cdw": delta_cdw,
            "Q_evap_kW": qe,
        }
    )
    numeric_columns = [column for column in normalized if column != "timestamp"]
    mask = normalized["timestamp"].notna()
    mask &= np.isfinite(normalized[numeric_columns]).all(axis=1)
    mask &= (normalized["P/kw"] > 0.0) & (normalized["CHW"] > 0.0) & (normalized["CDW"] > 0.0)
    mask &= (normalized["deltaT_chw"] > 0.0) & (normalized["Q_evap_kW"] > 0.0)
    normalized = normalized.loc[mask].sort_values("timestamp").reset_index(drop=True)
    normalized.insert(0, "Time", np.arange(len(normalized), dtype=float) * _sample_seconds(timestamps))
    return normalized[["Time", "timestamp", *TABLE_COLUMNS[1:]]]


def series_metrics(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    work = frame.copy()
    work["COP_m"] = work["Q_m"] / work["P_m"]
    work["COP_s"] = work["Q_s"] / work["P_s"]
    return {
        "P_W": regression_metrics(work["P_m"], work["P_s"]),
        "QEva_W": regression_metrics(work["Q_m"], work["Q_s"]),
        "COP": regression_metrics(work["COP_m"], work["COP_s"]),
    }


def _find_column(columns: Iterable[str], tokens: Iterable[str]) -> str | None:
    lowered = [token.lower() for token in tokens]
    return next((column for column in columns if all(token in column.lower() for token in lowered)), None)


def discover_columns(raw: pd.DataFrame, configured: dict[str, str] | None = None) -> dict[str, str]:
    configured = configured or {}
    columns = raw.columns
    discovered = {
        "timestamp": configured.get("timestamp") or ("DateTime" if "DateTime" in columns else None),
        "chws_C": configured.get("chws_C") or _find_column(columns, ["CHWS", "WTS"]),
        "chwr_C": configured.get("chwr_C") or _find_column(columns, ["CHWR", "WTS"]),
        "cdws_C": configured.get("cdws_C") or _find_column(columns, ["CDWS", "WTS"]),
        "cdwr_C": configured.get("cdwr_C") or _find_column(columns, ["CDWR", "WTS"]),
        "chw_lps": configured.get("chw_lps") or _find_column(columns, ["CHW", "WFM"]),
        "cdw_lps": configured.get("cdw_lps") or _find_column(columns, ["CDW", "WFM"]),
        "power_kw": configured.get("power_kw") or ("P/kw" if "P/kw" in columns else None),
        "qeva_kw": configured.get("qeva_kw") or _find_column(columns, ["BLDG", "LOAD"]),
        "vsd": configured.get("vsd") or _find_column(columns, ["VSD", "STS"]),
        "delta_chw_C": configured.get("delta_chw_C") or ("deltaT_chw" if "deltaT_chw" in columns else None),
        "delta_cdw_C": configured.get("delta_cdw_C") or ("deltaT_cdw" if "deltaT_cdw" in columns else None),
    }
    required = ("timestamp", "chws_C", "chwr_C", "cdws_C", "cdwr_C", "chw_lps", "cdw_lps", "power_kw")
    missing = [name for name in required if not discovered[name]]
    if missing:
        raise ValueError(f"cannot discover chiller columns: {', '.join(missing)}")
    return {key: value for key, value in discovered.items() if value}


def _write_modelica_table(path: Path, table: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("#1\n")
        handle.write(f"double AllData2({len(table)},12)\n")
        handle.write("#" + "\t".join(TABLE_COLUMNS) + "\n")
        for _, row in table.iterrows():
            handle.write("\t".join(f"{float(row[column]):.10g}" for column in TABLE_COLUMNS) + "\n")


def _nominals(table: pd.DataFrame) -> dict[str, float]:
    nominal = table.loc[table["Q_evap_kW"].idxmax()]
    q_nominal = float(nominal["Q_evap_kW"])
    p_nominal = float(nominal["P/kw"])
    plr = table["Q_evap_kW"] / q_nominal
    minimum_plr = max(0.05, float(plr[plr > 0.0].min()))
    return {
        "Q_nominal_kW": q_nominal,
        "P_nominal_kW": p_nominal,
        "COP_nominal": q_nominal / p_nominal,
        "mEva_flow_nominal": float(nominal["CHW"]),
        "mCon_flow_nominal": float(nominal["CDW"]),
        "TEvaLvg_nominal": float(nominal["CHWS"]) + 273.15,
        "TEvaLvgMin": float(table["CHWS"].min()) + 273.15,
        "TEvaLvgMax": float(table["CHWS"].max()) + 273.15,
        "TConEnt_nominal": float(nominal["CDWS"]) + 273.15,
        "TConEntMin": float(table["CDWS"].min()) + 273.15,
        "TConEntMax": float(table["CDWS"].max()) + 273.15,
        "TConLvg_nominal": float(nominal["CDWR"]) + 273.15,
        "TConLvgMin": float(table["CDWR"].min()) + 273.15,
        "TConLvgMax": float(table["CDWR"].max()) + 273.15,
        "PLRMax": 1.0,
        "PLRMinUnl": minimum_plr,
        "PLRMin": minimum_plr,
        "etaMotor": 1.0,
    }


def _filtered(snapshot, values: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in values.items() if name in snapshot.variables}


def _curve_values(kind: str, row: pd.Series) -> dict[str, float]:
    values = {}
    for index in range(1, 7):
        for prefix in ("capFunT", "EIRFunT"):
            value = float(row[f"{prefix}_{index}"])
            if kind == "ElectricReformulatedEIR":
                values[f"datchi.{prefix}[{index}]"] = value
                values[f"datChi.{prefix}[{index}]"] = value
            values[f"{prefix}_{index}"] = value
    maximum = 10 if kind == "ElectricReformulatedEIR" else 3
    for index in range(1, maximum + 1):
        value = float(row[f"EIRFunPLR_{index}"])
        if kind == "ElectricReformulatedEIR":
            values[f"datchi.EIRFunPLR[{index}]"] = value
            values[f"datChi.EIRFunPLR[{index}]"] = value
        values[f"EIRFunPLR_{index}"] = value
    return values


def _start_values(kind: str, snapshot, table_file: Path, nominals: dict[str, float], curve: pd.Series | None) -> dict[str, Any]:
    values: dict[str, Any] = {"VSD2.fileName": table_file.resolve().as_posix(), "VSD2.tableName": "AllData2"}
    if curve is not None:
        values.update(_curve_values(kind, curve))
    if kind == "ElectricEIR":
        values.update({f"datChi.{name}": value for name, value in nominals.items() if name not in ("P_nominal_kW", "Q_nominal_kW", "TConLvg_nominal", "TConLvgMin", "TConLvgMax")})
        values["datChi.QEva_flow_nominal"] = -nominals["Q_nominal_kW"] * 1000.0
    elif kind == "ElectricReformulatedEIR":
        values.update({name: value for name, value in nominals.items() if name not in ("P_nominal_kW", "Q_nominal_kW", "TConEnt_nominal", "TConEntMin", "TConEntMax")})
        values["QEva_flow_nominal"] = -nominals["Q_nominal_kW"] * 1000.0
        for prefix in ("datchi", "datChi"):
            values.update({f"{prefix}.{name}": value for name, value in nominals.items() if name not in ("P_nominal_kW", "Q_nominal_kW")})
            values[f"{prefix}.QEva_flow_nominal"] = -nominals["Q_nominal_kW"] * 1000.0
    else:
        t_eva = nominals["TEvaLvg_nominal"]
        t_con = nominals["TConLvg_nominal"]
        eta = min(0.99, nominals["COP_nominal"] / (t_eva / (t_con - t_eva)))
        values.update(
            {
                "Chi.QEva_flow_nominal": -nominals["Q_nominal_kW"] * 1000.0,
                "Chi.use_eta_Carnot_nominal": True,
                "Chi.etaCarnot_nominal": eta,
                "Chi.TEva_nominal": t_eva,
                "Chi.TCon_nominal": t_con,
                **{f"a{index}": 1.0 if index == 1 else 0.0 for index in range(1, 7)},
            }
        )
    return _filtered(snapshot, values)


class ChillerRunner(EquipmentRunner):
    def prepare(self) -> None:
        source = resolve_path(self.context.config, self.context.device["sources"]["steady_csv"])
        raw = pd.read_csv(source)
        columns = discover_columns(raw, self.context.device.get("columns"))
        self.canonical = normalize_chiller_frame(raw, columns)
        self.nominals = _nominals(self.canonical)
        self.table_file = self.device_dir / "prepare" / "AllData2.txt"
        _write_modelica_table(self.table_file, self.canonical)
        write_csv(self.device_dir / "prepare" / "canonical.csv", self.canonical)
        write_csv(
            self.device_dir / "prepare" / "adapter_qa.csv",
            pd.DataFrame([{"equipment_id": self.context.device["id"], "rows_raw": len(raw), "rows_valid": len(self.canonical), "sample_seconds": _sample_seconds(self.canonical["timestamp"])}]),
        )
        self._write_json(self.device_dir / "prepare" / "source_mapping.json", {"steady_csv": str(source), "sha256": sha256_file(source), "columns": columns})

    def check_readiness(self) -> ReadinessResult:
        minimum = int(self.context.device.get("readiness", {}).get("min_valid_rows", 30))
        reasons = [] if len(self.canonical) >= minimum else [f"requires at least {minimum} valid rows; got {len(self.canonical)}"]
        return ReadinessResult(not reasons, reasons, {"rows_valid": len(self.canonical), "minimum_rows": minimum})

    def _simulate_candidate(self, candidate: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
        from fmpy import simulate_fmu

        kind = str(candidate["kind"])
        fmu = resolve_path(self.context.config, candidate["fmu_path"])
        snapshot = inspect_fmu(fmu)
        curve = None
        if candidate.get("curve_data"):
            curve_data = pd.read_excel(resolve_path(self.context.config, candidate["curve_data"]), sheet_name=candidate.get("sheet", "Chiller Data"))
            curve = curve_data.iloc[int(candidate["row"]) - 1]
        start_values = _start_values(kind, snapshot, self.table_file, self.nominals, curve)
        interval = _sample_seconds(self.canonical["timestamp"])
        result = simulate_fmu(
            str(fmu),
            start_values=start_values,
            output=["P_s", "P_m", "Q_s", "Q_m"],
            stop_time=float(self.canonical["Time"].iloc[-1]),
            output_interval=interval,
            validate=False,
        )
        frame = pd.DataFrame({name: np.asarray(result[name]) for name in ("time", "P_s", "P_m", "Q_s", "Q_m")})
        metrics = series_metrics(frame)
        reference = {
            "mode": ExportMode.EXTERNAL_REFERENCE.value,
            "path": str(fmu),
            "sha256": sha256_file(fmu),
            "interface": {"outputs": list(snapshot.outputs), "parameters": list(snapshot.parameters)},
            "smoke": {"status": "passed", "rows": len(frame)},
        }
        self._write_json(self.device_dir / "fmu" / f"{kind}_external_fmu_reference.json", reference)
        return {"candidate": kind, "start_values": start_values, "metrics": metrics}, frame

    def calibrate(self) -> None:
        self.candidate_results = {}
        self.candidate_series = {}
        self.candidate_errors = []
        rows = []
        parameters = []
        for candidate in self.context.device.get("candidates", []):
            kind = str(candidate["kind"])
            try:
                result, frame = self._simulate_candidate(candidate)
                self.candidate_results[kind] = result
                self.candidate_series[kind] = frame
                metrics = result["metrics"]
                rows.append({"candidate": kind, **{f"{variable}_{metric}": value for variable, values in metrics.items() for metric, value in values.items()}})
                parameters.append({"candidate": kind, "start_values": json.dumps(result["start_values"], ensure_ascii=False, sort_keys=True)})
            except Exception as exc:
                self.candidate_errors.append(f"{kind}: {exc}")
                rows.append({"candidate": kind, "error": str(exc)})
        successful = [row for row in rows if "P_W_CVRMSE_pct" in row]
        if not successful:
            raise ValueError("all chiller candidates failed: " + "; ".join(self.candidate_errors))
        selected = min(successful, key=lambda row: float(row["P_W_CVRMSE_pct"]) + float(row["QEva_W_CVRMSE_pct"]))
        self.selected_candidate = str(selected["candidate"])
        write_csv(self.device_dir / "calibrate" / "all_candidate_metrics.csv", pd.DataFrame(rows))
        write_csv(self.device_dir / "calibrate" / "parameters.csv", pd.DataFrame(parameters))
        self._write_json(self.device_dir / "selected_model.json", {"candidate": self.selected_candidate, "nominals": self.nominals})

    def validate(self) -> None:
        frame = self.candidate_series[self.selected_candidate].copy()
        metrics = series_metrics(frame)
        self.metric_rows = [{"candidate": self.selected_candidate, "variable": variable, **values} for variable, values in metrics.items()]
        write_csv(self.device_dir / "validate" / "full_period_metrics.csv", pd.DataFrame(self.metric_rows))
        frame["COP_s"] = frame["Q_s"] / frame["P_s"]
        frame["COP_m"] = frame["Q_m"] / frame["P_m"]
        write_csv(self.device_dir / "validate" / "time_series.csv", frame)

    def export_fmu(self) -> ExportResult:
        if self.candidate_errors:
            return ExportResult(False, ExportMode.EXTERNAL_REFERENCE, "; ".join(self.candidate_errors))
        return ExportResult(True, ExportMode.EXTERNAL_REFERENCE, "external chiller FMUs inspected and simulated")

    def regression_rows(self) -> list[dict[str, Any]]:
        return [
            {"equipment_id": self.context.device["id"], "candidate": candidate, "variable": variable, "value": values["CVRMSE_pct"]}
            for candidate, result in self.candidate_results.items()
            for variable, values in result["metrics"].items()
        ]

    def report(self, status: RunStatus) -> None:
        output = self.device_dir / "report" / "summary.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        metrics = pd.DataFrame(self.metric_rows)
        output.write_text(
            f"# chiller/{self.context.device['id']}\n\nStatus: `{status.value}`\n\nSelected candidate: `{getattr(self, 'selected_candidate', 'none')}`\n\n"
            + (table_to_markdown(metrics) if not metrics.empty else "_No validation metrics._")
            + "\n",
            encoding="utf-8",
        )
