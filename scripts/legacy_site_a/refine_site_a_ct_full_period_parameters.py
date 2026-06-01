"""Refine Site A cooling tower parameters against full-period measured data."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping

import pandas as pd

from calibrate_site_a_ct_fmus import (
    CTM_FMU,
    CTY_FMU,
    LOG_DIR as CAL_LOG_DIR,
    OUT_DIR as CAL_DIR,
    TABLES,
    base_values,
    build_candidates,
    ctm_values,
    cty_values,
    estimate_pfan_nominal,
    fan_curve,
    flatten_metrics,
    merkel_fan_curve,
    metrics_wide,
    simulate_case,
    write_dymola_table,
)
from simulate_site_a_ct_full_period import TABLE_COLUMNS, full_period_table


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "cooling_tower" / "auto_model_site_a_full_period_refined"
PARAM_OUT = CAL_DIR / "site_a_best_parameters_full_period_refined.csv"
LOG_DIR = CAL_LOG_DIR / "full_period_refinement"


def run_full_period_search(
    tower: str,
    model: str,
    table: pd.DataFrame,
    table_path: Path,
    base: Mapping[str, object],
    timeseries_dir: Path,
) -> tuple[Dict[str, object], pd.DataFrame, pd.DataFrame]:
    fmu = CTY_FMU if model == "YorkCalc" else CTM_FMU
    value_builder = cty_values if model == "YorkCalc" else ctm_values
    stop_time = float(table["time_s"].iloc[-1])

    all_rows = []
    best_thermal = None
    best_thermal_df = None
    best_thermal_score = (float("inf"), float("inf"))

    for idx, candidate in enumerate(build_candidates(model, base)):
        try:
            values = value_builder(base, candidate)
            log_path = LOG_DIR / tower / model / f"thermal_{idx}.md"
            df = simulate_case(fmu, values, stop_time, log_path=log_path)
            met = metrics_wide(df)
            row = {
                "tower": tower,
                "model": model,
                "stage": "thermal",
                "candidate": f"thermal_{idx}",
                **candidate,
                **met,
            }
            all_rows.append(row)
            score = (met.get("CVRMSE_%_Q", float("inf")), met.get("RMSE_TOut", float("inf")))
            if score < best_thermal_score:
                best_thermal_score = score
                best_thermal = dict(candidate)
                best_thermal_df = df
        except Exception as exc:
            all_rows.append(
                {
                    "tower": tower,
                    "model": model,
                    "stage": "thermal",
                    "candidate": f"thermal_{idx}",
                    "error": str(exc),
                    **candidate,
                }
            )

    if best_thermal is None:
        raise RuntimeError(f"No successful full-period thermal candidate for {tower} {model}")

    fan_alphas = [0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.3, 2.6, 3.0, 3.4]
    best = None
    best_df = None
    best_score = float("inf")
    for alpha in fan_alphas:
        pfan = estimate_pfan_nominal(table, alpha, n_fan=float(base["nFan"]))
        if model == "YorkCalc":
            fan_params = {"PFan_nominal": pfan, **fan_curve(alpha)}
        else:
            fan_params = {"merkel.PFan_nominal": pfan, **merkel_fan_curve(alpha)}
        candidate = {**best_thermal, **fan_params, "fan_alpha": alpha}
        try:
            values = value_builder(base, candidate)
            log_path = LOG_DIR / tower / model / f"fan_{alpha:g}.md"
            df = simulate_case(fmu, values, stop_time, log_path=log_path)
            met = metrics_wide(df)
            row = {
                "tower": tower,
                "model": model,
                "stage": "fan",
                "candidate": f"fan_{alpha:g}",
                **candidate,
                **met,
            }
            all_rows.append(row)
            if met.get("score", float("inf")) < best_score:
                best_score = met["score"]
                best = dict(candidate)
                best_df = df
        except Exception as exc:
            all_rows.append(
                {
                    "tower": tower,
                    "model": model,
                    "stage": "fan",
                    "candidate": f"fan_{alpha:g}",
                    "error": str(exc),
                    **candidate,
                }
            )

    if best is None:
        best = best_thermal
        best_df = best_thermal_df

    ts_path = timeseries_dir / f"{tower}_{model}_full_period_refined_timeseries.csv"
    best_df.to_csv(ts_path, index=False)
    best_metrics = flatten_metrics(best_df, tower, model, "full_period_refined")
    best_metrics["timeseries"] = str(ts_path)
    best_row = {"tower": tower, "model": model, "score": best_score, "timeseries": str(ts_path), **best}
    return best_row, pd.DataFrame(all_rows), best_metrics


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tables_dir = OUT_DIR / "tables"
    timeseries_dir = OUT_DIR / "timeseries"
    tables_dir.mkdir(parents=True, exist_ok=True)
    timeseries_dir.mkdir(parents=True, exist_ok=True)

    best_rows = []
    candidate_frames = []
    metric_frames = []
    manifest_rows = []

    for csv_path in sorted(TABLES.glob("CT_*_fmu_table.csv")):
        tower = csv_path.name.split("_fmu_table.csv")[0]
        source = pd.read_csv(csv_path)
        if source.empty:
            continue
        table, meta = full_period_table(source[TABLE_COLUMNS])
        table_csv = tables_dir / f"{tower}_full_period_refinement_table.csv"
        table_txt = tables_dir / f"{tower}_full_period_refinement_table.txt"
        table.to_csv(table_csv, index=False)
        write_dymola_table(table_txt, table)
        base = base_values(table_txt, table)

        for model in ["Merkel", "YorkCalc"]:
            best, candidates, metrics = run_full_period_search(
                tower=tower,
                model=model,
                table=table,
                table_path=table_txt,
                base=base,
                timeseries_dir=timeseries_dir,
            )
            best_rows.append(best)
            candidate_frames.append(candidates)
            metric_frames.append(metrics)
            manifest_rows.append(
                {
                    "tower": tower,
                    "model": model,
                    "rows": len(table),
                    "source_elapsed_start_s": float(meta["source_time_s"].iloc[0]),
                    "source_elapsed_end_s": float(meta["source_time_s"].iloc[-1]),
                    "table": str(table_txt),
                    "timeseries": best["timeseries"],
                }
            )

    candidates_df = pd.concat(candidate_frames, ignore_index=True) if candidate_frames else pd.DataFrame()
    metrics_df = pd.concat(metric_frames, ignore_index=True) if metric_frames else pd.DataFrame()
    best_df = pd.DataFrame(best_rows)
    manifest_df = pd.DataFrame(manifest_rows)

    candidates_df.to_csv(OUT_DIR / "site_a_full_period_refined_candidate_metrics.csv", index=False, encoding="utf-8-sig")
    metrics_df.to_csv(OUT_DIR / "site_a_full_period_refined_metrics_long.csv", index=False, encoding="utf-8-sig")
    best_df.to_csv(PARAM_OUT, index=False, encoding="utf-8-sig")
    best_df.to_csv(OUT_DIR / "site_a_best_parameters_full_period_refined.csv", index=False, encoding="utf-8-sig")
    manifest_df.to_csv(OUT_DIR / "site_a_full_period_refinement_manifest.csv", index=False, encoding="utf-8-sig")

    print(f"Output: {OUT_DIR}")
    print(f"Refined parameters: {PARAM_OUT}")
    if not metrics_df.empty:
        print(metrics_df[["tower", "model", "variable", "N", "RMSE", "CVRMSE_%", "NMBE_%", "R2"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
