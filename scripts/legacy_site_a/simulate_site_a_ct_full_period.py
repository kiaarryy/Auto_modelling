"""Run full-period Site A cooling tower FMU simulations with calibrated parameters."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping

import numpy as np
import pandas as pd

from calibrate_site_a_ct_fmus import (
    CTM_FMU,
    CTY_FMU,
    LOG_DIR as CAL_LOG_DIR,
    OUT_DIR as CAL_DIR,
    TABLES,
    base_values,
    ctm_values,
    cty_values,
    flatten_metrics,
    simulate_case,
    write_dymola_table,
    Y_MIN_DEFAULT,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "cooling_tower" / "auto_model_site_a_full_period"
BEST_PARAMETERS = CAL_DIR / "site_a_best_parameters.csv"
REFINED_PARAMETERS = CAL_DIR / "site_a_best_parameters_full_period_refined.csv"
LOG_DIR = CAL_LOG_DIR / "full_period_validation"
TABLE_COLUMNS = [
    "time_s",
    "Tin_C",
    "Tout_meas_C",
    "Twb_C",
    "TRan_C",
    "TAppAct_C",
    "mdot_cell_kgps",
    "y_used",
    "fanHz",
    "fans_on_count",
    "Q_flow_W",
    "PFan_meas_W",
]


def clean_params(row: Mapping[str, object]) -> Dict[str, object]:
    skip = {"tower", "model", "score", "timeseries"}
    out: Dict[str, object] = {}
    for key, value in row.items():
        if key in skip:
            continue
        if pd.isna(value):
            continue
        out[key] = float(value)
    return out


def full_period_table(source: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = source[TABLE_COLUMNS].copy()
    meta = pd.DataFrame({"source_time_s": work["time_s"].to_numpy(float)})
    work["time_s"] = np.arange(len(work), dtype=float) * 300.0
    return work, meta


def run_one(
    tower: str,
    model: str,
    params: Mapping[str, object],
    table: pd.DataFrame,
    table_path: Path,
    base: Mapping[str, object],
    timeseries_dir: Path,
) -> pd.DataFrame:
    local_base = dict(base)
    local_base["table_path"] = str(table_path).replace("\\", "/")
    values = cty_values(local_base, params) if model == "YorkCalc" else ctm_values(local_base, params)
    fmu = CTY_FMU if model == "YorkCalc" else CTM_FMU
    stop_time = float(table["time_s"].iloc[-1])
    log_path = LOG_DIR / tower / model / "full_period_validation.md"
    result = simulate_case(fmu, values, stop_time, log_path=log_path)
    ts_path = timeseries_dir / f"{tower}_{model}_full_period_timeseries.csv"
    result.to_csv(ts_path, index=False)
    metrics = flatten_metrics(result, tower, model, "full_period")
    metrics["timeseries"] = str(ts_path)
    metrics["period_rows"] = len(table)
    return metrics


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tables_dir = OUT_DIR / "tables"
    timeseries_dir = OUT_DIR / "timeseries"
    tables_dir.mkdir(parents=True, exist_ok=True)
    timeseries_dir.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    parameter_path = REFINED_PARAMETERS if REFINED_PARAMETERS.exists() else BEST_PARAMETERS
    best = pd.read_csv(parameter_path)
    metric_frames = []
    manifest_rows = []

    for csv_path in sorted(TABLES.glob("CT_*_fmu_table.csv")):
        tower = csv_path.name.split("_fmu_table.csv")[0]
        source = pd.read_csv(csv_path)
        if source.empty:
            continue
        table, meta = full_period_table(source)
        table_csv = tables_dir / f"{tower}_full_period_table.csv"
        table_txt = tables_dir / f"{tower}_full_period_table.txt"
        meta_csv = tables_dir / f"{tower}_full_period_time_mapping.csv"
        table.to_csv(table_csv, index=False)
        meta.to_csv(meta_csv, index=False)
        write_dymola_table(table_txt, table)

        # Full-period validation must use the same nominal-value basis as the
        # full-period refinement table. Reusing the calibration-window
        # base_values.json here changes TWatIn/TWatOut/TApp/TRan nominal values
        # after the parameter search and breaks workflow continuity.
        base = base_values(table_txt, table)
        base["yMin"] = Y_MIN_DEFAULT

        for _, row in best.loc[best["tower"] == tower].iterrows():
            model = str(row["model"])
            params = clean_params(row.to_dict())
            metrics = run_one(tower, model, params, table, table_txt, base, timeseries_dir)
            metric_frames.append(metrics)
            manifest_rows.append(
                {
                    "tower": tower,
                    "model": model,
                    "rows": len(table),
                    "stop_time_s": float(table["time_s"].iloc[-1]),
                    "source_elapsed_start_s": float(meta["source_time_s"].iloc[0]),
                    "source_elapsed_end_s": float(meta["source_time_s"].iloc[-1]),
                    "table": str(table_txt),
                    "time_mapping": str(meta_csv),
                    "timeseries": str(timeseries_dir / f"{tower}_{model}_full_period_timeseries.csv"),
                    "parameter_source": str(parameter_path),
                }
            )

    metrics_df = pd.concat(metric_frames, ignore_index=True) if metric_frames else pd.DataFrame()
    manifest_df = pd.DataFrame(manifest_rows)
    metrics_df.to_csv(OUT_DIR / "site_a_full_period_metrics_long.csv", index=False, encoding="utf-8-sig")
    manifest_df.to_csv(OUT_DIR / "site_a_full_period_manifest.csv", index=False, encoding="utf-8-sig")

    print(f"Output: {OUT_DIR}")
    print(f"Parameter source: {parameter_path}")
    if not metrics_df.empty:
        print(metrics_df[["tower", "model", "variable", "N", "RMSE", "CVRMSE_%", "NMBE_%", "R2"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
