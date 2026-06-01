"""Generate a concise Site A heat exchanger auto-modelling report."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
HX_OUT = ROOT / "outputs" / "heat_exchanger"
QA_PATH = HX_OUT / "qa" / "site_a_hx_input_qa.csv"
METRICS_PATH = HX_OUT / "validation" / "site_a_hx_full_period_metrics.csv"
PARAMS_PATH = HX_OUT / "calibration" / "site_a_hx_best_parameters.csv"
FAILURES_PATH = HX_OUT / "calibration" / "site_a_hx_failed_candidates.csv"
CANDIDATE_METRICS_PATH = HX_OUT / "calibration" / "site_a_hx_all_candidate_metrics.csv"
POWER_METRICS_PATH = HX_OUT / "power_diagnostic" / "site_a_hx_aux_power_metrics.csv"
REPORT_PATH = HX_OUT / "site_a_hx_auto_modelling_report.md"


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._\n"
    headers = list(df.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in df.iterrows():
        values = []
        for col in headers:
            value = row.get(col, "")
            if isinstance(value, float):
                value = f"{value:.6g}"
            values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def build_report_text(
    qa: pd.DataFrame,
    metrics: pd.DataFrame,
    params: pd.DataFrame,
    failures: pd.DataFrame,
    candidate_metrics: pd.DataFrame | None = None,
    power_metrics: pd.DataFrame | None = None,
) -> str:
    candidate_metrics = candidate_metrics if candidate_metrics is not None else pd.DataFrame()
    power_metrics = power_metrics if power_metrics is not None else pd.DataFrame()
    qa_cols = [c for c in ["hx", "status", "rows_raw", "rows_valid", "valid_%", "median_balance_rel", "median_Q_m_W"] if c in qa.columns]
    param_cols = [c for c in ["hx", "model", "score", "eps", "m1_flow_nominal", "m2_flow_nominal", "Q_flow_nominal"] if c in params.columns]
    metric_cols = [c for c in ["hx", "model", "variable", "N", "RMSE", "MAE", "MBE", "NMBE", "CVRMSE", "R2", "timeseries"] if c in metrics.columns]
    power_cols = [c for c in ["hx", "model", "variable", "N", "RMSE", "MAE", "MBE", "NMBE", "CVRMSE", "R2"] if c in power_metrics.columns]
    failure_count = len(failures)
    failure_summary = failures.groupby(["hx", "model"]).size().reset_index(name="failed_candidates") if not failures.empty and {"hx", "model"}.issubset(failures.columns) else pd.DataFrame()
    calibration_model_comparison = summarize_candidate_models(candidate_metrics)
    full_period_model_comparison = summarize_full_period_models(metrics)

    return "\n".join(
        [
            "# Site A Heat Exchanger Auto-Modelling Report",
            "",
            "## Status",
            "",
            "- `HX_01` and `HX_02` have completed FMU-based calibration and chunked full-period validation.",
            "- `HX_03` remains blocked because the local CSV lacks both-side temperature fields.",
            "- Final model selection should be read from the full-period model comparison table when multiple model types are present there.",
            f"- Failed candidate count: `{failure_count}`. Failed candidates are retained for diagnosis and do not stop the batch.",
            "",
            "## Data QA",
            "",
            markdown_table(qa[qa_cols] if qa_cols else qa),
            "",
            "## Recommended Full-Period Best Models",
            "",
            markdown_table(full_period_model_comparison.loc[full_period_model_comparison["rank_within_hx"] == 1] if not full_period_model_comparison.empty and "rank_within_hx" in full_period_model_comparison else pd.DataFrame()),
            "",
            "## Calibration-Window Best FMU Parameters",
            "",
            markdown_table(params[param_cols] if param_cols else params),
            "",
            "## Calibration Candidate Model Comparison",
            "",
            markdown_table(calibration_model_comparison),
            "",
            "## Full-Period Model Comparison",
            "",
            markdown_table(full_period_model_comparison),
            "",
            "## Full-Period FMU Metrics",
            "",
            markdown_table(metrics[metric_cols] if metric_cols else metrics),
            "",
            "## Auxiliary Power Diagnostic",
            "",
            "The MBL heat exchanger candidates do not simulate electrical power. The table below is a separate constant-power diagnostic for the measured `P/kw`/HXCWP auxiliary power signal, not a physical HX FMU output.",
            "",
            markdown_table(power_metrics[power_cols] if power_cols else power_metrics),
            "",
            "## Failed Candidate Summary",
            "",
            markdown_table(failure_summary),
            "",
            "## Notes",
            "",
            "- Full-period FMU validation is run in 24-hour chunks because large `CombiTimeTable` files can fail during FMU initialization.",
            "- Measured outlet temperatures and measured Q are used only as scoring outputs, not as model inputs.",
            "- `AlgebraicEffectiveness` remains a diagnostic baseline; it is not a Buildings heat exchanger FMU candidate.",
            "- Auxiliary power figures, when present, are generated from the separate `ConstantAuxPowerDiagnostic` time series.",
            "",
        ]
    )


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def summarize_candidate_models(candidate_metrics: pd.DataFrame) -> pd.DataFrame:
    if candidate_metrics.empty or not {"hx", "model", "candidate_id", "score"}.issubset(candidate_metrics.columns):
        return pd.DataFrame()
    work = candidate_metrics[["hx", "model", "candidate_id", "score"]].drop_duplicates().copy()
    work["score"] = pd.to_numeric(work["score"], errors="coerce")
    idx = work.groupby(["hx", "model"])["score"].idxmin()
    out = work.loc[idx].sort_values(["hx", "score"]).reset_index(drop=True)
    out["rank_within_hx"] = out.groupby("hx")["score"].rank(method="first").astype(int)
    return out[["hx", "rank_within_hx", "model", "candidate_id", "score"]]


def summarize_full_period_models(metrics: pd.DataFrame) -> pd.DataFrame:
    required = {"hx", "model", "variable", "CVRMSE"}
    if metrics.empty or not required.issubset(metrics.columns):
        return pd.DataFrame()
    work = metrics.copy()
    work["CVRMSE"] = pd.to_numeric(work["CVRMSE"], errors="coerce")
    piv = work.pivot_table(
        index=[col for col in ["hx", "model", "candidate_id"] if col in work.columns],
        columns="variable",
        values="CVRMSE",
        aggfunc="min",
    ).reset_index()
    for col in ["T1Out", "T2Out", "Q"]:
        if col not in piv.columns:
            piv[col] = pd.NA
    t1 = pd.to_numeric(piv["T1Out"], errors="coerce")
    t2 = pd.to_numeric(piv["T2Out"], errors="coerce")
    q = pd.to_numeric(piv["Q"], errors="coerce")
    piv["score"] = 2.0 * t1.fillna(0.0) + 2.0 * t2.fillna(0.0) + q.fillna(0.0)
    piv = piv.sort_values(["hx", "score"]).reset_index(drop=True)
    piv["rank_within_hx"] = piv.groupby("hx")["score"].rank(method="first").astype(int)
    cols = [c for c in ["hx", "rank_within_hx", "model", "candidate_id", "score", "T1Out", "T2Out", "Q"] if c in piv.columns]
    return piv[cols]


def main() -> int:
    qa = read_csv_or_empty(QA_PATH)
    metrics = read_csv_or_empty(METRICS_PATH)
    params = read_csv_or_empty(PARAMS_PATH)
    failures = read_csv_or_empty(FAILURES_PATH)
    candidate_metrics = read_csv_or_empty(CANDIDATE_METRICS_PATH)
    power_metrics = read_csv_or_empty(POWER_METRICS_PATH)
    REPORT_PATH.write_text(build_report_text(qa, metrics, params, failures, candidate_metrics, power_metrics), encoding="utf-8")
    print(f"Output: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
