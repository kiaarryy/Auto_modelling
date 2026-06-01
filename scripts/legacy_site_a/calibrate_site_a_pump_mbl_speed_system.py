"""Calibrate a SpeedControlled_y-style pump/system-curve candidate.

This candidate is a lightweight runner for the main MBL physical option:
`Buildings.Fluid.Movers.SpeedControlled_y` with a simple system curve. It uses
the same affinity-law assumptions expected from the MBL mover:

- flow approximately scales with normalized speed;
- pressure/head scales with speed squared;
- electrical power scales with speed cubed.

Because Site A has no measured pump head/DP, `head_s` is reported as inferred
only and is not used as a validation target.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TABLE_DIR = ROOT / "outputs" / "pump" / "site_a_tables"
WINDOW_REVIEW = ROOT / "outputs" / "pump" / "stage3_windows" / "site_a_pump_window_review.csv"
OUT_DIR = ROOT / "outputs" / "pump" / "mbl_speed_system"
TIMESERIES_DIR = OUT_DIR / "best_timeseries"

VARIANTS = [
    ("affinity_y3_flow_y", 1.0, 3.0),
    ("low_power_exp", 1.0, 2.7),
    ("high_power_exp", 1.0, 3.3),
    ("sublinear_flow", 0.85, 3.0),
    ("superlinear_flow", 1.15, 3.0),
]


def default_head_nominal_m(pump_type: str) -> float:
    if pump_type == "CHWP":
        return 28.0
    if pump_type == "CDWP":
        return 32.0
    if pump_type == "HXCWP":
        return 24.0
    return 30.0


def clean_table(df: pd.DataFrame) -> pd.DataFrame:
    clean = df.copy()
    for col in ["m_flow_kg_s", "y_used", "P_meas_W"]:
        clean[col] = pd.to_numeric(clean[col], errors="coerce")
    clean = clean.replace([np.inf, -np.inf], np.nan).dropna(subset=["m_flow_kg_s", "y_used", "P_meas_W"])
    return clean[(clean["m_flow_kg_s"] > 0.0) & (clean["y_used"] > 0.0) & (clean["P_meas_W"] > 0.0)].copy()


def robust_ratio_nominal(measured: pd.Series, y: pd.Series, exponent: float) -> float:
    ratio = measured / np.maximum(np.power(y, exponent), 1e-6)
    ratio = pd.to_numeric(ratio, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(ratio.median()) if not ratio.empty else 1.0


def fit_variant(train: pd.DataFrame, variant: str, flow_exp: float, power_exp: float) -> dict[str, float | str]:
    clean = clean_table(train)
    if clean.empty:
        raise ValueError("Cannot fit MBL speed/system candidate on an empty training table")
    pump_type = str(clean["pump_type"].iloc[0]) if "pump_type" in clean else ""
    y = clean["y_used"].clip(lower=0.05, upper=1.2)
    return {
        "variant": variant,
        "pump_type": pump_type,
        "m_flow_nominal": robust_ratio_nominal(clean["m_flow_kg_s"], y, flow_exp),
        "P_nominal": robust_ratio_nominal(clean["P_meas_W"], y, power_exp),
        "head_nominal_m": default_head_nominal_m(pump_type),
        "flow_exp": float(flow_exp),
        "power_exp": float(power_exp),
        "y_min": 0.05,
        "y_max": 1.2,
        "head_status": "inferred_not_measured",
        "mbl_reference": "Buildings.Fluid.Movers.SpeedControlled_y",
    }


def predict_variant(df: pd.DataFrame, params: dict[str, float | str]) -> pd.DataFrame:
    y = pd.to_numeric(df["y_used"], errors="coerce").clip(
        lower=float(params.get("y_min", 0.05)),
        upper=float(params.get("y_max", 1.2)),
    )
    out = pd.DataFrame(index=df.index)
    out["m_flow_s"] = float(params["m_flow_nominal"]) * np.power(y, float(params["flow_exp"]))
    out["P_s"] = float(params["P_nominal"]) * np.power(y, float(params["power_exp"]))
    out["head_s"] = float(params["head_nominal_m"]) * np.power(y, 2.0)
    out["y_s"] = y
    return out[["m_flow_s", "P_s", "head_s", "y_s"]]


def metrics(measured: Iterable[float], predicted: Iterable[float]) -> dict[str, float]:
    meas = pd.to_numeric(pd.Series(measured), errors="coerce")
    pred = pd.to_numeric(pd.Series(predicted), errors="coerce")
    work = pd.DataFrame({"meas": meas, "pred": pred}).replace([np.inf, -np.inf], np.nan).dropna()
    if work.empty:
        return {"n": 0, "rmse": np.nan, "mae": np.nan, "cvrmse_pct": np.nan, "nmbe_pct": np.nan, "r2": np.nan}
    residual = work["pred"] - work["meas"]
    rmse = float(np.sqrt(np.mean(residual**2)))
    mae = float(np.mean(np.abs(residual)))
    mean_meas = float(work["meas"].mean())
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((work["meas"] - mean_meas) ** 2))
    return {
        "n": int(len(work)),
        "rmse": rmse,
        "mae": mae,
        "cvrmse_pct": float(rmse / mean_meas * 100.0) if mean_meas else np.nan,
        "nmbe_pct": float(residual.mean() / mean_meas * 100.0) if mean_meas else np.nan,
        "r2": float(1.0 - ss_res / ss_tot) if ss_tot else np.nan,
    }


def combined_score(row: dict[str, object]) -> float:
    # Flow is weighted equally with power because this candidate predicts flow
    # independently. Head is not scored because no measured head exists.
    return float(row["full_P_cvrmse_pct"]) + float(row["full_flow_cvrmse_pct"])


def select_best_variant(rows: list[dict[str, object]]) -> dict[str, object]:
    best = dict(min(rows, key=combined_score))
    best["combined_full_cvrmse_score"] = combined_score(best)
    best["accepted_full_period"] = bool(
        float(best["full_P_cvrmse_pct"]) <= 15.0
        and float(best["full_flow_cvrmse_pct"]) <= 15.0
        and abs(float(best.get("full_P_nmbe_pct", 0.0))) <= 10.0
    )
    return best


def ready_pumps(window_review_path: Path = WINDOW_REVIEW) -> list[str]:
    if not window_review_path.exists():
        return sorted(path.name.replace("_fmu_table.csv", "") for path in TABLE_DIR.glob("*_fmu_table.csv"))
    review = pd.read_csv(window_review_path)
    return [str(row["pump"]) for _, row in review.iterrows() if str(row.get("ready_for_stage4", "")).lower() == "true"]


def calibrate_pump(pump: str) -> tuple[list[dict[str, object]], dict[str, object], pd.DataFrame]:
    train = clean_table(pd.read_csv(TABLE_DIR / f"{pump}_window_table.csv"))
    full = clean_table(pd.read_csv(TABLE_DIR / f"{pump}_fmu_table.csv"))
    rows: list[dict[str, object]] = []
    params_by_variant: dict[str, dict[str, float | str]] = {}
    for variant, flow_exp, power_exp in VARIANTS:
        params = fit_variant(train, variant, flow_exp=flow_exp, power_exp=power_exp)
        params_by_variant[variant] = params
        cal_pred = predict_variant(train, params)
        full_pred = predict_variant(full, params)
        cal_p = metrics(train["P_meas_W"], cal_pred["P_s"])
        cal_f = metrics(train["m_flow_kg_s"], cal_pred["m_flow_s"])
        full_p = metrics(full["P_meas_W"], full_pred["P_s"])
        full_f = metrics(full["m_flow_kg_s"], full_pred["m_flow_s"])
        row: dict[str, object] = {
            "pump": pump,
            "candidate_id": "mbl_speedcontrolled_y_system_curve",
            "variant": variant,
            "cal_n": cal_p["n"],
            "cal_P_cvrmse_pct": cal_p["cvrmse_pct"],
            "cal_P_nmbe_pct": cal_p["nmbe_pct"],
            "cal_flow_cvrmse_pct": cal_f["cvrmse_pct"],
            "cal_flow_nmbe_pct": cal_f["nmbe_pct"],
            "full_n": full_p["n"],
            "full_P_cvrmse_pct": full_p["cvrmse_pct"],
            "full_P_nmbe_pct": full_p["nmbe_pct"],
            "full_P_r2": full_p["r2"],
            "full_flow_cvrmse_pct": full_f["cvrmse_pct"],
            "full_flow_nmbe_pct": full_f["nmbe_pct"],
            "full_flow_r2": full_f["r2"],
            "head_validation_status": "not_scored_no_measured_head",
        }
        row.update(params)
        rows.append(row)

    best = select_best_variant(rows)
    best_params = params_by_variant[str(best["variant"])]
    pred = predict_variant(full, best_params)
    best_ts = full.copy()
    best_ts["P_s"] = pred["P_s"]
    best_ts["m_flow_s"] = pred["m_flow_s"]
    best_ts["head_s"] = pred["head_s"]
    best_ts["y_s"] = pred["y_s"]
    best_ts["P_residual_W"] = best_ts["P_s"] - best_ts["P_meas_W"]
    best_ts["m_flow_residual_kg_s"] = best_ts["m_flow_s"] - best_ts["m_flow_kg_s"]
    return rows, best, best_ts


def markdown_table(df: pd.DataFrame) -> str:
    headers = list(df.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in df.iterrows():
        values = []
        for col in headers:
            val = row[col]
            if isinstance(val, float):
                values.append("" if np.isnan(val) else f"{val:.4g}")
            else:
                values.append(str(val).replace("|", "/"))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(all_metrics: pd.DataFrame, best: pd.DataFrame, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Site A Pump MBL Speed/System Candidate Report\n\n")
        f.write("Candidate: `Buildings.Fluid.Movers.SpeedControlled_y + Data.Generic + simple system curve`.\n\n")
        f.write("This runner scores independently predicted power and flow. Head is inferred from affinity laws and is not scored because measured pump head/DP is unavailable.\n\n")
        f.write(f"- Pumps calibrated: {len(best)}\n")
        f.write(f"- Accepted pumps under candidate thresholds: {int(best['accepted_full_period'].sum())}\n")
        f.write(f"- Median full P CVRMSE: {best['full_P_cvrmse_pct'].median():.4g}%\n")
        f.write(f"- Median full flow CVRMSE: {best['full_flow_cvrmse_pct'].median():.4g}%\n\n")
        cols = [
            "pump",
            "variant",
            "full_P_cvrmse_pct",
            "full_flow_cvrmse_pct",
            "combined_full_cvrmse_score",
            "accepted_full_period",
            "head_validation_status",
        ]
        f.write("## Best Variants\n\n")
        f.write(markdown_table(best.sort_values("combined_full_cvrmse_score")[cols]))
        f.write("\n\n## All Variant Metrics\n\n")
        metric_cols = ["pump", "variant", "full_P_cvrmse_pct", "full_flow_cvrmse_pct", "full_P_nmbe_pct", "full_flow_nmbe_pct"]
        f.write(markdown_table(all_metrics.sort_values(["pump", "full_P_cvrmse_pct"])[metric_cols]))
        f.write("\n")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TIMESERIES_DIR.mkdir(parents=True, exist_ok=True)
    metric_rows: list[dict[str, object]] = []
    best_rows: list[dict[str, object]] = []
    for pump in ready_pumps():
        rows, best, best_ts = calibrate_pump(pump)
        metric_rows.extend(rows)
        best_rows.append(best)
        best_ts.to_csv(TIMESERIES_DIR / f"{pump}_mbl_speed_system_best_timeseries.csv", index=False)

    all_metrics = pd.DataFrame(metric_rows)
    best = pd.DataFrame(best_rows).sort_values("combined_full_cvrmse_score")
    all_metrics.to_csv(OUT_DIR / "all_candidate_metrics.csv", index=False)
    best.to_csv(OUT_DIR / "best_mbl_speed_system_parameters.csv", index=False)
    best.to_csv(OUT_DIR / "full_period_validation_metrics.csv", index=False)
    write_report(all_metrics, best, OUT_DIR / "site_a_pump_mbl_speed_system_report.md")
    print(f"Wrote {OUT_DIR / 'all_candidate_metrics.csv'}")
    print(f"Wrote {OUT_DIR / 'best_mbl_speed_system_parameters.csv'}")
    print(f"Wrote {OUT_DIR / 'full_period_validation_metrics.csv'}")
    print(f"Wrote {OUT_DIR / 'site_a_pump_mbl_speed_system_report.md'}")
    print(
        best[
            [
                "pump",
                "variant",
                "full_P_cvrmse_pct",
                "full_flow_cvrmse_pct",
                "combined_full_cvrmse_score",
                "accepted_full_period",
                "head_validation_status",
            ]
        ].to_string(index=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
