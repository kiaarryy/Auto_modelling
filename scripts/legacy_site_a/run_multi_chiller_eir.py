"""Run ElectricEIR FMU curve screening for prepared measured chillers.

Inputs are produced by ``prepare_eir_chiller_steady_data.py``:

- A measured nominal-values workbook.
- One ``AllData2`` text table for each prepared chiller.

The script keeps ``Cali_EIR_BSU_CH1`` read-only and writes all simulation
results under ``outputs/electric_eir``.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from prepare_eir_chiller_steady_data import FMU_NOMINAL_COLUMNS
from run_fmu_eir_calibration import (
    DEFAULT_CHILLER_DATA,
    DEFAULT_FMU,
    PARAMETER_COLUMNS,
    load_cases,
    result_to_dataframe,
    run_one_case,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NOMINALS = ROOT / "outputs" / "electric_eir" / "nominals" / "eir_measured_nominals.xlsx"
DEFAULT_OUTPUT = ROOT / "outputs" / "electric_eir" / "simulation" / "eir_multi_chiller_results.xlsx"
DEFAULT_BEST_TS = ROOT / "outputs" / "electric_eir" / "simulation" / "best_timeseries"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ElectricEIR FMU screening for all prepared measured chillers."
    )
    parser.add_argument("--fmu", type=Path, default=DEFAULT_FMU)
    parser.add_argument("--chiller-data", type=Path, default=DEFAULT_CHILLER_DATA)
    parser.add_argument("--sheet", default="Chiller Data")
    parser.add_argument("--nominals", type=Path, default=DEFAULT_NOMINALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--best-timeseries-dir", type=Path, default=DEFAULT_BEST_TS)
    parser.add_argument("--chiller", action="append", help="Run only this chiller; can be repeated.")
    parser.add_argument("--max-chillers", type=int)
    parser.add_argument("--max-models", type=int)
    parser.add_argument("--start-time", type=float, default=0.0)
    parser.add_argument(
        "--output-interval",
        type=float,
        help="Override output interval. Defaults to each chiller's prepared table sample interval.",
    )
    return parser.parse_args()


def finite_float(value: Any) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def load_nominals(path: Path, selected: Optional[List[str]], max_chillers: Optional[int]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_excel(path, sheet_name="Nominals")
    if "Chiller" not in df.columns:
        raise ValueError(f"Nominals workbook missing Chiller column: {path}")
    if selected:
        selected_set = set(selected)
        df = df[df["Chiller"].isin(selected_set)].copy()
    if max_chillers is not None:
        df = df.head(max_chillers).copy()
    if df.empty:
        raise ValueError("No prepared chillers selected for simulation")
    return df.reset_index(drop=True)


def nominal_start_values(row: pd.Series) -> Dict[str, float]:
    values: Dict[str, float] = {}
    for column in FMU_NOMINAL_COLUMNS:
        if column in row:
            value = finite_float(row[column])
            if value is not None:
                values[column] = value
    return values


def chiller_result_prefix(row: pd.Series) -> Dict[str, Any]:
    return {
        "Chiller": row["Chiller"],
        "TablePath": row.get("TablePath", ""),
        "ValidRows": row.get("ValidRows", np.nan),
        "SampleSeconds": row.get("SampleSeconds", np.nan),
        "StopTime": row.get("StopTime", np.nan),
        "Q_nominal_kW": row.get("Q_nominal_kW", np.nan),
        "COP_nominal_measured": row.get("COP_nominal_measured", np.nan),
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

    stop_time_value = finite_float(nominal_row.get("StopTime"))
    if stop_time_value is None:
        raise ValueError(f"{chiller} missing StopTime")
    output_interval = output_interval_override
    if output_interval is None:
        output_interval = finite_float(nominal_row.get("SampleSeconds"))

    extra_start_values = nominal_start_values(nominal_row)
    prefix = chiller_result_prefix(nominal_row)
    all_rows: List[Dict[str, Any]] = []
    best_row: Optional[Dict[str, Any]] = None
    best_result: Optional[np.ndarray] = None
    best_score = float("inf")

    print(
        f"=== {chiller}: cases={len(cases)} stop={stop_time_value} interval={output_interval} ==="
    )
    for case_index, case in cases.iterrows():
        model_name = str(case["Model Name"])
        try:
            metrics, result = run_one_case(
                fmu_path,
                table_file,
                case,
                start_time,
                stop_time_value,
                output_interval,
                include_excel_nominals=False,
                extra_start_values=extra_start_values,
            )
            score = metrics["CVRMSE_Power_%"] + metrics["CVRMSE_Cooling_%"]
            row = {**prefix, **metrics}
            all_rows.append(row)
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
            row = {
                **prefix,
                "ModelName": model_name,
                "SourceRow": int(case["SourceRowZeroBased"]) + 1,
                "Status": "failed",
                "Error": str(exc),
            }
            all_rows.append(row)
            print(f"  [{case_index + 1}/{len(cases)}] {model_name}: failed: {exc}")

    if best_row is not None and best_result is not None:
        best_timeseries_dir.mkdir(parents=True, exist_ok=True)
        ts_path = best_timeseries_dir / f"{chiller}_best_timeseries.csv"
        result_to_dataframe(best_result).to_csv(ts_path, index=False)
        best_row["BestTimeseriesPath"] = str(ts_path)

    return all_rows, best_row


def rank_all_results(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if {"Chiller", "Status", "CVRMSE_Power_%", "CVRMSE_Cooling_%"}.issubset(df.columns):
        df["CVRMSE_Sum_%"] = df["CVRMSE_Power_%"] + df["CVRMSE_Cooling_%"]
        ok = df["Status"].eq("ok") & df["CVRMSE_Sum_%"].notna()
        df["Rank_By_CVRMSE_Sum"] = np.nan
        df.loc[ok, "Rank_By_CVRMSE_Sum"] = df.loc[ok].groupby("Chiller")[
            "CVRMSE_Sum_%"
        ].rank(method="min")
    return df


def write_workbook(
    all_rows: List[Mapping[str, Any]],
    best_rows: List[Mapping[str, Any]],
    nominals: pd.DataFrame,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_df = rank_all_results(pd.DataFrame(all_rows))
    best_df = pd.DataFrame(best_rows)
    if not best_df.empty:
        best_df = rank_all_results(best_df)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        all_df.to_excel(writer, sheet_name="AllResults", index=False)
        best_df.to_excel(writer, sheet_name="BestResults", index=False)
        nominals.to_excel(writer, sheet_name="NominalsUsed", index=False)


def main() -> int:
    args = parse_args()
    if not args.fmu.exists():
        raise FileNotFoundError(args.fmu)
    if not args.chiller_data.exists():
        raise FileNotFoundError(args.chiller_data)

    nominals = load_nominals(args.nominals, args.chiller, args.max_chillers)
    cases = load_cases(args.chiller_data, args.sheet, row=None, max_models=args.max_models)
    # Keep only the curve-related columns and metadata needed by the runner.
    required = ["Model Name", "SourceRowZeroBased", *PARAMETER_COLUMNS]
    cases = cases[required].copy()

    all_rows: List[Dict[str, Any]] = []
    best_rows: List[Dict[str, Any]] = []
    for _, nominal_row in nominals.iterrows():
        chiller_rows, best_row = run_chiller(
            args.fmu,
            nominal_row,
            cases,
            args.start_time,
            args.output_interval,
            args.best_timeseries_dir,
        )
        all_rows.extend(chiller_rows)
        if best_row is not None:
            best_rows.append(best_row)

    write_workbook(all_rows, best_rows, nominals, args.output)
    print(f"Results workbook: {args.output}")
    print(f"Best time series dir: {args.best_timeseries_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
