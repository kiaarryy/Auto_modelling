"""Run Carnot_TEva FMU simulations for prepared measured chillers.

The Carnot_TEva FMU is a single-model parameterization rather than a 157-curve
candidate screen like EIR/EEIR. For each prepared chiller this script sets the
measured nominal cooling capacity, nominal temperatures, and nominal Carnot
efficiency, then writes one result row and one best time-series CSV.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd
from fmpy import read_model_description, simulate_fmu

from run_fmu_eir_calibration import (
    OUTPUT_VARIABLES,
    cvrmse,
    max_abs_delta,
    mean_abs_delta,
    result_to_dataframe,
    rmse,
)
from prepare_eir_chiller_steady_data import TABLE_COLUMNS, write_modelica_table


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CARNOT_FMU = (
    ROOT
    / "Cali_EIR_BSU_CH1"
    / "Modelica"
    / "ChillerCalibration_FMU_chiller_Carnot.fmu"
)
DEFAULT_NOMINALS = (
    ROOT
    / "outputs"
    / "electric_reformulated_eir"
    / "nominals"
    / "eeir_measured_nominals_physical.xlsx"
)
DEFAULT_OUTPUT = (
    ROOT
    / "outputs"
    / "electric_carnot_teva"
    / "simulation"
    / "carnot_multi_chiller_results_current_fmu.xlsx"
)
DEFAULT_SUMMARY = (
    ROOT
    / "outputs"
    / "electric_carnot_teva"
    / "simulation"
    / "carnot_best_curve_summary_current_fmu.xlsx"
)
DEFAULT_BEST_TS = (
    ROOT
    / "outputs"
    / "electric_carnot_teva"
    / "simulation"
    / "best_timeseries_current_fmu"
)
DEFAULT_CARNOT_TABLE_DIR = (
    ROOT
    / "outputs"
    / "electric_carnot_teva"
    / "chiller_tables_current_fmu"
)

CARNOT_AUDIT_PARAMETERS = [
    "Chi.QEva_flow_nominal",
    "Chi.use_eta_Carnot_nominal",
    "Chi.etaCarnot_nominal",
    "Chi.TEva_nominal",
    "Chi.TCon_nominal",
    "Chi.dTEva_nominal",
    "Chi.dTCon_nominal",
    "a1",
    "a2",
    "a3",
    "a4",
    "a5",
    "a6",
    "VSD2.fileName",
    "VSD2.tableName",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Carnot_TEva FMU screening for measured chillers.")
    parser.add_argument("--fmu", type=Path, default=DEFAULT_CARNOT_FMU)
    parser.add_argument("--nominals", type=Path, default=DEFAULT_NOMINALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--best-timeseries-dir", type=Path, default=DEFAULT_BEST_TS)
    parser.add_argument("--carnot-table-dir", type=Path, default=DEFAULT_CARNOT_TABLE_DIR)
    parser.add_argument("--chiller", action="append")
    parser.add_argument("--max-chillers", type=int)
    parser.add_argument("--start-time", type=float, default=0.0)
    parser.add_argument("--output-interval", type=float)
    parser.add_argument(
        "--condenser-dt-max",
        type=float,
        default=180.0,
        help="Filter rows whose measured condenser heat balance implies a larger delta-T.",
    )
    parser.add_argument("--eta-min", type=float, default=0.0)
    parser.add_argument(
        "--eta-max",
        type=float,
        default=0.99,
        help="Upper bound for etaCarnot_nominal; Carnot_TEva requires eta < 1.",
    )
    return parser.parse_args()


def finite_float(value: Any) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def exposed_variable_names(fmu_path: Path) -> set[str]:
    model_description = read_model_description(str(fmu_path), validate=False)
    return {variable.name for variable in model_description.modelVariables}


def filtered_start_values(fmu_path: Path, start_values: Mapping[str, Any]) -> Dict[str, Any]:
    exposed = exposed_variable_names(fmu_path)
    return {name: value for name, value in start_values.items() if name in exposed}


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
        raise ValueError("No prepared chillers selected for Carnot simulation")
    return nominals.reset_index(drop=True), qa.reset_index(drop=True)


def read_modelica_table(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", skiprows=3, names=TABLE_COLUMNS)


def condenser_delta_t_estimate(table: pd.DataFrame) -> pd.Series:
    cdw = pd.to_numeric(table["CDW"], errors="coerce")
    q_kw = pd.to_numeric(table["Q_evap_kW"], errors="coerce")
    p_kw = pd.to_numeric(table["P/kw"], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        return (q_kw + p_kw) / (4.186 * cdw)


def prepare_carnot_table(
    chiller: str,
    nominal_row: pd.Series,
    table_dir: Path,
    condenser_dt_max: float,
) -> tuple[Path, Dict[str, Any]]:
    source_table = Path(str(nominal_row["TablePath"]))
    if not source_table.is_absolute():
        source_table = ROOT / source_table
    if not source_table.exists():
        raise FileNotFoundError(f"{chiller} table file not found: {source_table}")

    table = read_modelica_table(source_table)
    dt_est = condenser_delta_t_estimate(table)
    base_mask = table[TABLE_COLUMNS].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)
    m_eva_nominal = finite_float(nominal_row.get("mEva_flow_nominal_lps"))
    m_con_nominal = finite_float(nominal_row.get("mCon_flow_nominal_lps"))
    min_chw_flow = 0.05 * m_eva_nominal if m_eva_nominal is not None else 0.0
    min_cdw_flow = 0.05 * m_con_nominal if m_con_nominal is not None else 0.0
    flow_mask = (
        pd.to_numeric(table["CHW"], errors="coerce").ge(min_chw_flow)
        & pd.to_numeric(table["CDW"], errors="coerce").ge(min_cdw_flow)
    )
    filter_mask = base_mask & flow_mask & np.isfinite(dt_est) & (dt_est < condenser_dt_max)
    filtered = table.loc[filter_mask, TABLE_COLUMNS].copy()
    if filtered.empty:
        raise ValueError(f"{chiller} has no Carnot-compatible rows after condenser delta-T filtering")

    sample_seconds = finite_float(nominal_row.get("SampleSeconds"))
    if sample_seconds is None:
        raise ValueError(f"{chiller} missing SampleSeconds")
    filtered["Time"] = np.arange(len(filtered), dtype=float) * sample_seconds

    output_table = table_dir / f"{chiller}_ChillerData.txt"
    write_modelica_table(filtered, output_table)

    return output_table, {
        "SourceTablePath": str(source_table),
        "TablePath": str(output_table),
        "OriginalRows": int(len(table)),
        "CarnotRows": int(len(filtered)),
        "DroppedRowsForCarnot": int(len(table) - len(filtered)),
        "CarnotFilter": (
            f"CHW/CDW >= 5% nominal flow and estimated condenser deltaT < "
            f"{condenser_dt_max:g} K"
        ),
        "MinCHWFlowForCarnot": float(min_chw_flow),
        "MinCDWFlowForCarnot": float(min_cdw_flow),
        "MaxEstimatedCondenserDeltaT_K": float(np.nanmax(dt_est.to_numpy(dtype=float))),
        "StopTime": float((len(filtered) - 1) * sample_seconds),
    }


def result_metrics(result: np.ndarray, model_name: str, source_row: int = 1) -> Dict[str, Any]:
    p_sim = np.asarray(result["P_s"], dtype=float).reshape(-1)
    p_mea = np.asarray(result["P_m"], dtype=float).reshape(-1)
    q_sim = np.asarray(result["Q_s"], dtype=float).reshape(-1)
    q_mea = np.asarray(result["Q_m"], dtype=float).reshape(-1)
    len_p = min(len(p_sim), len(p_mea))
    len_q = min(len(q_sim), len(q_mea))
    p_sim, p_mea = p_sim[:len_p], p_mea[:len_p]
    q_sim, q_mea = q_sim[:len_q], q_mea[:len_q]
    return {
        "ModelName": model_name,
        "SourceRow": source_row,
        "Status": "ok",
        "Error": "",
        "Samples_Power": len_p,
        "Samples_Cooling": len_q,
        "RMSE_Power": rmse(p_sim, p_mea),
        "CVRMSE_Power_%": cvrmse(p_sim, p_mea),
        "Max_DeltaPower_W": max_abs_delta(p_sim, p_mea),
        "Mean_DeltaPower_W": mean_abs_delta(p_sim, p_mea),
        "RMSE_Cooling": rmse(q_sim, q_mea),
        "CVRMSE_Cooling_%": cvrmse(q_sim, q_mea),
        "Max_DeltaCooling_W": max_abs_delta(q_sim, q_mea),
        "Mean_DeltaCooling_W": mean_abs_delta(q_sim, q_mea),
    }


def carnot_nominal_values(row: pd.Series, eta_min: float, eta_max: float) -> Dict[str, Any]:
    q_nom_kw = float(row["Q_nominal_kW"])
    measured_cop = float(row["COP_nominal_measured"])
    t_eva_nominal = float(row["TEvaLvg_nominal_C"]) + 273.15
    t_con_nominal = float(row["TConLvg_nominal_C"]) + 273.15
    carnot_cop = t_eva_nominal / (t_con_nominal - t_eva_nominal)
    eta_raw = measured_cop / carnot_cop
    eta = min(max(eta_raw, eta_min), eta_max)
    return {
        "Chi.QEva_flow_nominal": -q_nom_kw * 1000.0,
        "Chi.use_eta_Carnot_nominal": True,
        "Chi.etaCarnot_nominal": eta,
        "Chi.TEva_nominal": t_eva_nominal,
        "Chi.TCon_nominal": t_con_nominal,
        "Carnot_COP_nominal": carnot_cop,
        "Measured_COP_nominal": measured_cop,
        "etaCarnot_nominal_raw": eta_raw,
        "etaCarnot_nominal_used": eta,
        "etaClipped": eta != eta_raw,
    }


def start_values_for_chiller(fmu_path: Path, table_file: Path, nominal_row: pd.Series, eta_min: float, eta_max: float) -> tuple[Dict[str, Any], Dict[str, Any]]:
    carnot_values = carnot_nominal_values(nominal_row, eta_min, eta_max)
    values: Dict[str, Any] = {
        "VSD2.fileName": str(table_file.resolve()).replace("\\", "/"),
        "VSD2.tableName": "AllData2",
        "a1": 1.0,
        "a2": 0.0,
        "a3": 0.0,
        "a4": 0.0,
        "a5": 0.0,
        "a6": 0.0,
    }
    values.update({key: value for key, value in carnot_values.items() if key.startswith("Chi.")})
    return filtered_start_values(fmu_path, values), carnot_values


def simulate_chiller(
    fmu_path: Path,
    nominal_row: pd.Series,
    start_time: float,
    output_interval_override: Optional[float],
    table_dir: Path,
    condenser_dt_max: float,
    eta_min: float,
    eta_max: float,
) -> tuple[Dict[str, Any], np.ndarray, Dict[str, Any]]:
    chiller = str(nominal_row["Chiller"])
    table_file, table_info = prepare_carnot_table(chiller, nominal_row, table_dir, condenser_dt_max)
    stop_time = table_info["StopTime"]
    output_interval = output_interval_override
    if output_interval is None:
        output_interval = finite_float(nominal_row.get("SampleSeconds"))

    start_values, carnot_values = start_values_for_chiller(fmu_path, table_file, nominal_row, eta_min, eta_max)
    result = simulate_fmu(
        filename=str(fmu_path),
        start_time=start_time,
        stop_time=stop_time,
        output_interval=output_interval,
        start_values=start_values,
        output=OUTPUT_VARIABLES,
        validate=False,
    )
    metrics = result_metrics(result, "Carnot_TEva_measured_nominal")
    prefix = {
        "Chiller": chiller,
        "TablePath": str(table_file),
        "ValidRows": table_info["CarnotRows"],
        "SourceValidRows": nominal_row.get("ValidRows", np.nan),
        "SampleSeconds": nominal_row.get("SampleSeconds", np.nan),
        "StopTime": stop_time,
        "Q_nominal_kW": nominal_row.get("Q_nominal_kW", np.nan),
        "COP_nominal_measured": nominal_row.get("COP_nominal_measured", np.nan),
        "TEvaLvg_nominal_C": nominal_row.get("TEvaLvg_nominal_C", np.nan),
        "TConLvg_nominal_C": nominal_row.get("TConLvg_nominal_C", np.nan),
    }
    prefix.update(table_info)
    prefix.update(carnot_values)
    return {**prefix, **metrics}, result, carnot_values


def rank_results(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if {"CVRMSE_Power_%", "CVRMSE_Cooling_%"}.issubset(df.columns):
        df["CVRMSE_Sum_%"] = df["CVRMSE_Power_%"] + df["CVRMSE_Cooling_%"]
        ok = df["Status"].eq("ok") & df["CVRMSE_Sum_%"].notna()
        df["Rank_By_CVRMSE_Sum"] = np.nan
        df.loc[ok, "Rank_By_CVRMSE_Sum"] = df.loc[ok].groupby("Chiller")["CVRMSE_Sum_%"].rank(method="min")
    return df


def parameter_audit(fmu_path: Path) -> pd.DataFrame:
    exposed = exposed_variable_names(fmu_path)
    return pd.DataFrame(
        [
            {
                "Parameter": name,
                "ExposedInFMU": name in exposed,
                "UsableByScript": name in exposed,
            }
            for name in CARNOT_AUDIT_PARAMETERS
        ]
    )


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
        nominals.to_excel(writer, sheet_name="NominalsSource", index=False)
        qa.to_excel(writer, sheet_name="QA", index=False)
        audit.to_excel(writer, sheet_name="ParameterAudit", index=False)

    skipped = qa[qa["Status"].eq("skipped")].copy()
    skip_rows = [
        {
            "Chiller": row["Chiller"],
            "Status": "skipped",
            "ResultStatus": "skipped",
            "SkipReason": row.get("SkipReason", ""),
            "ValidRows": row.get("ValidRows", np.nan),
        }
        for _, row in skipped.iterrows()
    ]
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

    nominals, qa = load_nominals(args.nominals, args.chiller, args.max_chillers)
    all_rows: List[Dict[str, Any]] = []
    best_rows: List[Dict[str, Any]] = []
    args.best_timeseries_dir.mkdir(parents=True, exist_ok=True)

    for index, nominal_row in nominals.iterrows():
        chiller = str(nominal_row["Chiller"])
        print(f"=== {chiller}: [{index + 1}/{len(nominals)}] ===")
        try:
            row, result, _ = simulate_chiller(
                args.fmu,
                nominal_row,
                args.start_time,
                args.output_interval,
                args.carnot_table_dir,
                args.condenser_dt_max,
                args.eta_min,
                args.eta_max,
            )
            ts_path = args.best_timeseries_dir / f"{chiller}_best_timeseries.csv"
            result_to_dataframe(result).to_csv(ts_path, index=False)
            row["BestTimeseriesPath"] = str(ts_path)
            all_rows.append(row)
            best_rows.append(row.copy())
            print(
                f"  ok: CVRMSE_P={row['CVRMSE_Power_%']:.3f}% "
                f"CVRMSE_Q={row['CVRMSE_Cooling_%']:.3f}% "
                f"eta={row['etaCarnot_nominal_used']:.4f}"
            )
        except Exception as exc:
            all_rows.append(
                {
                    "Chiller": chiller,
                    "ModelName": "Carnot_TEva_measured_nominal",
                    "SourceRow": 1,
                    "Status": "failed",
                    "Error": str(exc),
                }
            )
            print(f"  failed: {exc}")

    write_outputs(all_rows, best_rows, nominals, qa, args.fmu, args.output, args.summary_output)
    print(f"Results workbook: {args.output}")
    print(f"Summary workbook: {args.summary_output}")
    print(f"Best time series dir: {args.best_timeseries_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
