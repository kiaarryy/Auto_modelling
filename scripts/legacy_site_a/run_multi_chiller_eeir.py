"""Run ElectricReformulatedEIR FMU screening for prepared measured chillers."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from prepare_eir_chiller_steady_data import EEIR_FMU_NOMINAL_COLUMNS
from run_fmu_eeir_calibration import (
    DEFAULT_EEIR_DATA,
    DEFAULT_EEIR_FMU,
    EEIR_CURVE_COLUMNS,
    load_cases,
    parameter_audit,
    result_to_dataframe,
    run_one_case,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NOMINALS = (
    ROOT / "outputs" / "electric_reformulated_eir" / "nominals" / "eeir_measured_nominals_physical.xlsx"
)
DEFAULT_OUTPUT = (
    ROOT / "outputs" / "electric_reformulated_eir" / "simulation" / "eeir_multi_chiller_results_physical.xlsx"
)
DEFAULT_BEST_TS = ROOT / "outputs" / "electric_reformulated_eir" / "simulation" / "best_timeseries_physical"
DEFAULT_SUMMARY = (
    ROOT / "outputs" / "electric_reformulated_eir" / "simulation" / "eeir_best_curve_summary_physical.xlsx"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EEIR FMU screening for measured chillers.")
    parser.add_argument("--fmu", type=Path, default=DEFAULT_EEIR_FMU)
    parser.add_argument("--chiller-data", type=Path, default=DEFAULT_EEIR_DATA)
    parser.add_argument("--sheet", default="Chiller Data")
    parser.add_argument("--nominals", type=Path, default=DEFAULT_NOMINALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--best-timeseries-dir", type=Path, default=DEFAULT_BEST_TS)
    parser.add_argument("--chiller", action="append")
    parser.add_argument("--max-chillers", type=int)
    parser.add_argument("--max-models", type=int)
    parser.add_argument("--start-time", type=float, default=0.0)
    parser.add_argument("--output-interval", type=float)
    return parser.parse_args()


def finite_float(value: Any) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def load_nominals(path: Path, selected: Optional[List[str]], max_chillers: Optional[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not path.exists():
        raise FileNotFoundError(path)
    nominals = pd.read_excel(path, sheet_name="Nominals")
    qa = pd.read_excel(path, sheet_name="QA")
    if selected:
        selected_set = set(selected)
        nominals = nominals[nominals["Chiller"].isin(selected_set)].copy()
        qa = qa[qa["Chiller"].isin(selected_set)].copy()
    if max_chillers is not None:
        nominals = nominals.head(max_chillers).copy()
        qa = qa[qa["Chiller"].isin(set(nominals["Chiller"]))].copy()
    if nominals.empty:
        raise ValueError("No prepared chillers selected for EEIR simulation")
    return nominals.reset_index(drop=True), qa.reset_index(drop=True)


def nominal_start_values(row: pd.Series) -> Dict[str, float]:
    values: Dict[str, float] = {}
    for column in EEIR_FMU_NOMINAL_COLUMNS:
        if column in row:
            value = finite_float(row[column])
            if value is not None:
                values[column] = value

    alias_groups = {
        "QEva_flow_nominal": ["QEva_flow_nominal", "datChi.QEva_flow_nominal"],
        "COP_nominal": ["COP_nominal", "datChi.COP_nominal"],
        "mEva_flow_nominal": ["mEva_flow_nominal", "datChi.mEva_flow_nominal"],
        "mCon_flow_nominal": ["mCon_flow_nominal", "datChi.mCon_flow_nominal"],
        "PLRMax": ["PLRMax", "datChi.PLRMax", "datchi.PLRMax"],
        "PLRMinUnl": ["PLRMinUnl", "datChi.PLRMinUnl", "datchi.PLRMinUnl"],
        "PLRMin": ["PLRMin", "datChi.PLRMin", "datchi.PLRMin"],
        "etaMotor": ["etaMotor", "datChi.etaMotor"],
        "TEvaLvg_nominal": ["TEvaLvg_nominal", "datChi.TEvaLvg_nominal", "datchi.TEvaLvg_nominal"],
        "TEvaLvgMin": ["TEvaLvgMin", "datChi.TEvaLvgMin", "datchi.TEvaLvgMin"],
        "TEvaLvgMax": ["TEvaLvgMax", "datChi.TEvaLvgMax", "datchi.TEvaLvgMax"],
        "TConLvg_nominal": ["TConLvg_nominal", "datchi.TConLvg_nominal"],
        "TConLvgMin": ["TConLvgMin", "datchi.TConLvgMin"],
        "TConLvgMax": ["TConLvgMax", "datchi.TConLvgMax"],
    }
    for target, sources in alias_groups.items():
        for source in sources:
            if source in row:
                value = finite_float(row[source])
                if value is not None:
                    values[target] = value
                    break
    return values


def result_prefix(row: pd.Series) -> Dict[str, Any]:
    return {
        "Chiller": row["Chiller"],
        "TablePath": row.get("TablePath", ""),
        "ValidRows": row.get("ValidRows", np.nan),
        "SampleSeconds": row.get("SampleSeconds", np.nan),
        "StopTime": row.get("StopTime", np.nan),
        "Q_nominal_kW": row.get("Q_nominal_kW", np.nan),
        "COP_nominal_measured": row.get("COP_nominal_measured", np.nan),
        "Note": "EEIR start values were mapped to the parameter names exposed by the selected FMU.",
    }


def run_chiller(
    fmu_path: Path,
    nominal_row: pd.Series,
    cases: pd.DataFrame,
    start_time: float,
    output_interval_override: Optional[float],
    best_timeseries_dir: Path,
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    chiller = str(nominal_row["Chiller"])
    table_file = Path(str(nominal_row["TablePath"]))
    if not table_file.exists():
        raise FileNotFoundError(f"{chiller} table file not found: {table_file}")
    stop_time = finite_float(nominal_row.get("StopTime"))
    if stop_time is None:
        raise ValueError(f"{chiller} missing StopTime")
    output_interval = output_interval_override
    if output_interval is None:
        output_interval = finite_float(nominal_row.get("SampleSeconds"))

    extra = nominal_start_values(nominal_row)
    prefix = result_prefix(nominal_row)
    rows: List[Dict[str, Any]] = []
    best_row: Optional[Dict[str, Any]] = None
    best_result: Optional[np.ndarray] = None
    best_score = float("inf")

    print(f"=== {chiller}: cases={len(cases)} stop={stop_time} interval={output_interval} ===")
    for case_index, case in cases.iterrows():
        model_name = str(case["Model Name"])
        try:
            metrics, result = run_one_case(
                fmu_path,
                table_file,
                case,
                start_time,
                stop_time,
                output_interval,
                extra_start_values=extra,
            )
            score = metrics["CVRMSE_Power_%"] + metrics["CVRMSE_Cooling_%"]
            row = {**prefix, **metrics}
            rows.append(row)
            if math.isfinite(score) and score < best_score:
                best_score = score
                best_row = row
                best_result = result
            print(
                f"  [{case_index + 1}/{len(cases)}] {model_name}: "
                f"CVRMSE_P={metrics['CVRMSE_Power_%']:.3f}% "
                f"CVRMSE_Q={metrics['CVRMSE_Cooling_%']:.3f}%"
            )
        except Exception as exc:
            rows.append(
                {
                    **prefix,
                    "ModelName": model_name,
                    "SourceRow": int(case["SourceRowZeroBased"]) + 1,
                    "Status": "failed",
                    "Error": str(exc),
                }
            )
            print(f"  [{case_index + 1}/{len(cases)}] {model_name}: failed: {exc}")

    if best_row is not None and best_result is not None:
        best_timeseries_dir.mkdir(parents=True, exist_ok=True)
        ts_path = best_timeseries_dir / f"{chiller}_best_timeseries.csv"
        result_to_dataframe(best_result).to_csv(ts_path, index=False)
        best_row["BestTimeseriesPath"] = str(ts_path)
    return rows, best_row


def rank_results(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if {"Chiller", "Status", "CVRMSE_Power_%", "CVRMSE_Cooling_%"}.issubset(df.columns):
        df["CVRMSE_Sum_%"] = df["CVRMSE_Power_%"] + df["CVRMSE_Cooling_%"]
        ok = df["Status"].eq("ok") & df["CVRMSE_Sum_%"].notna()
        df["Rank_By_CVRMSE_Sum"] = np.nan
        df.loc[ok, "Rank_By_CVRMSE_Sum"] = df.loc[ok].groupby("Chiller")["CVRMSE_Sum_%"].rank(method="min")
    return df


def write_outputs(
    all_rows: List[Mapping[str, Any]],
    best_rows: List[Mapping[str, Any]],
    nominals: pd.DataFrame,
    qa: pd.DataFrame,
    fmu_path: Path,
    output_path: Path,
    summary_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_df = rank_results(pd.DataFrame(all_rows))
    best_df = rank_results(pd.DataFrame(best_rows))
    audit = parameter_audit(fmu_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        all_df.to_excel(writer, sheet_name="AllResults", index=False)
        best_df.to_excel(writer, sheet_name="BestResults", index=False)
        nominals.to_excel(writer, sheet_name="NominalsUsed", index=False)
        qa.to_excel(writer, sheet_name="QA", index=False)
        audit.to_excel(writer, sheet_name="ParameterAudit", index=False)

    skipped = qa[qa["Status"].eq("skipped")].copy()
    skip_rows = []
    for _, row in skipped.iterrows():
        skip_rows.append(
            {
                "Chiller": row["Chiller"],
                "ResultStatus": "skipped",
                "SkipReason": row.get("SkipReason", ""),
                "ValidRows": row.get("ValidRows", np.nan),
            }
        )
    summary = best_df.copy()
    if not summary.empty:
        summary.insert(1, "ResultStatus", "simulated")
    summary = pd.concat([summary, pd.DataFrame(skip_rows)], ignore_index=True, sort=False)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_excel(summary_path, index=False)


def main() -> int:
    args = parse_args()
    if not args.fmu.exists():
        raise FileNotFoundError(args.fmu)
    if not args.chiller_data.exists():
        raise FileNotFoundError(args.chiller_data)

    nominals, qa = load_nominals(args.nominals, args.chiller, args.max_chillers)
    cases = load_cases(args.chiller_data, args.sheet, row=None, max_models=args.max_models)
    cases = cases[["Model Name", "SourceRowZeroBased", *EEIR_CURVE_COLUMNS]].copy()

    all_rows: List[Dict[str, Any]] = []
    best_rows: List[Dict[str, Any]] = []
    for _, nominal_row in nominals.iterrows():
        rows, best = run_chiller(
            args.fmu,
            nominal_row,
            cases,
            args.start_time,
            args.output_interval,
            args.best_timeseries_dir,
        )
        all_rows.extend(rows)
        if best is not None:
            best_rows.append(best)

    write_outputs(all_rows, best_rows, nominals, qa, args.fmu, args.output, args.summary_output)
    print(f"Results workbook: {args.output}")
    print(f"Summary workbook: {args.summary_output}")
    print(f"Best time series dir: {args.best_timeseries_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
