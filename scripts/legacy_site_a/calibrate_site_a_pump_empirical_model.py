"""Calibrate empirical pump power models and validate over full valid periods."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TABLE_DIR = ROOT / "outputs" / "pump" / "site_a_tables"
WINDOW_REVIEW = ROOT / "outputs" / "pump" / "stage3_windows" / "site_a_pump_window_review.csv"
OUT_DIR = ROOT / "outputs" / "pump" / "auto_model_site_a"
TIMESERIES_DIR = OUT_DIR / "best_timeseries"

MODEL_FAMILIES = ["affinity_y3", "speed_poly", "flow_speed_5term"]
ACCEPT_CVRMSE_PCT = 10.0
ACCEPT_ABS_NMBE_PCT = 5.0


def design_matrix(df: pd.DataFrame, family: str, m_flow_nominal: float) -> tuple[np.ndarray, list[str]]:
    y = pd.to_numeric(df["y_used"], errors="coerce").to_numpy(dtype=float)
    phi = pd.to_numeric(df["m_flow_kg_s"], errors="coerce").to_numpy(dtype=float) / max(m_flow_nominal, 1e-6)
    if family == "affinity_y3":
        return np.column_stack([y**3]), ["c3"]
    if family == "speed_poly":
        return np.column_stack([np.ones_like(y), y, y**3]), ["c0", "c2", "c3"]
    if family == "flow_speed_5term":
        return np.column_stack([np.ones_like(y), phi, y, y**3, phi * y]), ["c0", "c1", "c2", "c3", "c4"]
    raise ValueError(f"Unknown model family: {family}")


def fit_model_family(train: pd.DataFrame, family: str) -> dict[str, float | str]:
    clean = clean_table(train)
    if clean.empty:
        raise ValueError("Cannot fit pump model on an empty training table")
    m_flow_nominal = float(clean["m_flow_kg_s"].median())
    x, names = design_matrix(clean, family, m_flow_nominal)
    y_meas = clean["P_meas_W"].to_numpy(dtype=float)
    raw_beta, *_ = np.linalg.lstsq(x, y_meas, rcond=None)
    p_nominal = float(max(np.nanmax(np.abs(raw_beta)), np.nanmedian(y_meas), 1.0))
    params: dict[str, float | str] = {
        "family": family,
        "P_nominal": p_nominal,
        "m_flow_nominal": m_flow_nominal,
        "y_min": 0.05,
        "y_max": 1.20,
        "c0": 0.0,
        "c1": 0.0,
        "c2": 0.0,
        "c3": 0.0,
        "c4": 0.0,
    }
    for name, beta in zip(names, raw_beta):
        params[name] = float(beta / p_nominal)
    return params


def clean_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["m_flow_kg_s", "y_used", "P_meas_W"]
    clean = df.copy()
    for col in cols:
        clean[col] = pd.to_numeric(clean[col], errors="coerce")
    clean = clean.replace([np.inf, -np.inf], np.nan).dropna(subset=cols)
    return clean[(clean["m_flow_kg_s"] > 0.0) & (clean["y_used"] > 0.0) & (clean["P_meas_W"] > 0.0)].copy()


def predict_power(df: pd.DataFrame, params: dict[str, float | str]) -> pd.Series:
    clean = df.copy()
    y = pd.to_numeric(clean["y_used"], errors="coerce").clip(
        lower=float(params.get("y_min", 0.05)),
        upper=float(params.get("y_max", 1.20)),
    )
    m_flow = pd.to_numeric(clean["m_flow_kg_s"], errors="coerce").clip(lower=0.0)
    phi = m_flow / max(float(params["m_flow_nominal"]), 1e-6)
    rel = (
        float(params.get("c0", 0.0))
        + float(params.get("c1", 0.0)) * phi
        + float(params.get("c2", 0.0)) * y
        + float(params.get("c3", 0.0)) * y**3
        + float(params.get("c4", 0.0)) * phi * y
    )
    pred = float(params["P_nominal"]) * rel
    return pred.clip(lower=0.0)


def metrics(measured: Iterable[float], predicted: Iterable[float]) -> dict[str, float]:
    meas = pd.to_numeric(pd.Series(measured), errors="coerce")
    pred = pd.to_numeric(pd.Series(predicted), errors="coerce")
    work = pd.DataFrame({"meas": meas, "pred": pred}).replace([np.inf, -np.inf], np.nan).dropna()
    if work.empty:
        return {"n": 0, "rmse_W": np.nan, "mae_W": np.nan, "cvrmse_pct": np.nan, "nmbe_pct": np.nan, "r2": np.nan}
    residual = work["pred"] - work["meas"]
    rmse = float(np.sqrt(np.mean(residual**2)))
    mae = float(np.mean(np.abs(residual)))
    mean_meas = float(work["meas"].mean())
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((work["meas"] - mean_meas) ** 2))
    return {
        "n": int(len(work)),
        "rmse_W": rmse,
        "mae_W": mae,
        "cvrmse_pct": float(rmse / mean_meas * 100.0) if mean_meas else np.nan,
        "nmbe_pct": float(residual.mean() / mean_meas * 100.0) if mean_meas else np.nan,
        "r2": float(1.0 - ss_res / ss_tot) if ss_tot else np.nan,
    }


def ready_pumps(window_review_path: Path = WINDOW_REVIEW) -> list[str]:
    if not window_review_path.exists():
        return sorted(path.name.replace("_fmu_table.csv", "") for path in TABLE_DIR.glob("*_fmu_table.csv"))
    review = pd.read_csv(window_review_path)
    return [str(row["pump"]) for _, row in review.iterrows() if str(row.get("ready_for_stage4", "")).lower() == "true"]


def calibrate_pump(pump: str) -> tuple[list[dict[str, object]], dict[str, object], pd.DataFrame]:
    train = pd.read_csv(TABLE_DIR / f"{pump}_window_table.csv")
    full = pd.read_csv(TABLE_DIR / f"{pump}_fmu_table.csv")
    train = clean_table(train)
    full = clean_table(full)
    rows: list[dict[str, object]] = []
    params_by_family: dict[str, dict[str, float | str]] = {}
    for family in MODEL_FAMILIES:
        params = fit_model_family(train, family)
        params_by_family[family] = params
        cal_pred = predict_power(train, params)
        val_pred = predict_power(full, params)
        cal_metrics = metrics(train["P_meas_W"], cal_pred)
        val_metrics = metrics(full["P_meas_W"], val_pred)
        row: dict[str, object] = {"pump": pump, "family": family}
        row.update({f"cal_{k}": v for k, v in cal_metrics.items()})
        row.update({f"full_{k}": v for k, v in val_metrics.items()})
        row.update({k: v for k, v in params.items() if k != "family"})
        rows.append(row)

    cal_selected = min(rows, key=lambda row: float(row["cal_cvrmse_pct"]))
    best_row = select_best_candidate(rows)
    best_row["calibration_selected_family"] = cal_selected["family"]
    best_row["selection_basis"] = "full_period_validation_cvrmse"
    best_params = params_by_family[str(best_row["family"])]
    best_ts = full.copy()
    best_ts["P_sim_W"] = predict_power(best_ts, best_params)
    best_ts["P_residual_W"] = best_ts["P_sim_W"] - best_ts["P_meas_W"]
    best = dict(best_row)
    return rows, best, best_ts


def select_best_candidate(rows: list[dict[str, object]]) -> dict[str, object]:
    ranked = sorted(rows, key=lambda row: (float(row["full_cvrmse_pct"]), abs(float(row["full_nmbe_pct"]))))
    best = dict(ranked[0])
    best["accepted_full_period"] = (
        float(best["full_cvrmse_pct"]) <= ACCEPT_CVRMSE_PCT
        and abs(float(best["full_nmbe_pct"])) <= ACCEPT_ABS_NMBE_PCT
    )
    best["overfit_warning"] = bool(float(best["full_cvrmse_pct"]) > max(3.0 * float(best["cal_cvrmse_pct"]), ACCEPT_CVRMSE_PCT))
    return best


def write_report(all_metrics: pd.DataFrame, best: pd.DataFrame, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Site A Pump Empirical Auto-Modelling Report\n\n")
        f.write("Model target: measured electrical pump power `P_meas_W` from measured flow and normalized speed.\n\n")
        f.write(f"- Pumps calibrated: {len(best)}\n")
        f.write(f"- Candidate families per pump: {len(MODEL_FAMILIES)}\n")
        f.write(f"- Full-period accepted pumps: {int(best['accepted_full_period'].sum())}\n")
        f.write(f"- Best median full-period CVRMSE: {best['full_cvrmse_pct'].median():.3g}%\n")
        f.write(f"- Best median full-period NMBE: {best['full_nmbe_pct'].median():.3g}%\n\n")
        f.write(
            "Selection uses full-period validation CVRMSE for final recommendation. "
            "The calibration-window-selected family is preserved separately to expose overfitting.\n\n"
        )
        cols = [
            "pump",
            "family",
            "calibration_selected_family",
            "cal_cvrmse_pct",
            "full_cvrmse_pct",
            "full_nmbe_pct",
            "full_r2",
            "full_n",
            "accepted_full_period",
        ]
        f.write("## Best Models\n\n")
        f.write(markdown_table(best.sort_values("full_cvrmse_pct")[cols]))
        f.write("\n\n## Candidate Metrics\n\n")
        candidate_cols = ["pump", "family", "cal_cvrmse_pct", "full_cvrmse_pct", "full_nmbe_pct", "full_r2", "full_n"]
        f.write(markdown_table(all_metrics.sort_values(["pump", "cal_cvrmse_pct"])[candidate_cols]))
        f.write("\n")


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


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TIMESERIES_DIR.mkdir(parents=True, exist_ok=True)
    metric_rows: list[dict[str, object]] = []
    best_rows: list[dict[str, object]] = []
    for pump in ready_pumps():
        rows, best, best_ts = calibrate_pump(pump)
        metric_rows.extend(rows)
        best_rows.append(best)
        best_ts.to_csv(TIMESERIES_DIR / f"{pump}_best_full_timeseries.csv", index=False)

    all_metrics = pd.DataFrame(metric_rows)
    best = pd.DataFrame(best_rows).sort_values("full_cvrmse_pct")
    all_metrics.to_csv(OUT_DIR / "all_candidate_metrics.csv", index=False)
    best.to_csv(OUT_DIR / "best_pump_parameters.csv", index=False)
    best.to_csv(OUT_DIR / "full_period_validation_metrics.csv", index=False)
    write_report(all_metrics, best, OUT_DIR / "site_a_pump_auto_model_report.md")
    print(f"Wrote {OUT_DIR / 'all_candidate_metrics.csv'}")
    print(f"Wrote {OUT_DIR / 'best_pump_parameters.csv'}")
    print(f"Wrote {OUT_DIR / 'full_period_validation_metrics.csv'}")
    print(f"Wrote {OUT_DIR / 'site_a_pump_auto_model_report.md'}")
    print(
        best[
            [
                "pump",
                "family",
                "calibration_selected_family",
                "cal_cvrmse_pct",
                "full_cvrmse_pct",
                "full_nmbe_pct",
                "full_r2",
                "full_n",
                "accepted_full_period",
            ]
        ].to_string(index=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
