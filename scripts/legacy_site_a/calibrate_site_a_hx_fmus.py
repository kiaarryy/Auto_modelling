"""Calibrate Site A heat exchanger candidate FMUs on prepared measured tables."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

try:
    from prepare_site_a_hx_fmu_tables import compute_metrics, write_dymola_table
except ImportError:  # Allows importing as scripts.calibrate_site_a_hx_fmus in tests.
    from scripts.prepare_site_a_hx_fmu_tables import compute_metrics, write_dymola_table


ROOT = Path(__file__).resolve().parents[1]
HX_OUT = ROOT / "outputs" / "heat_exchanger"
TABLE_DIR = HX_OUT / "fmu_tables"
NOMINALS = HX_OUT / "nominals" / "site_a_hx_nominals.csv"
OUT_DIR = HX_OUT / "calibration"
LOG_DIR = HX_OUT / "logs" / "calibration"
FMU_DIR = HX_OUT / "modelica_interface" / "fmu"
PLATE_FMU = FMU_DIR / "SiteAHXPlateEffectivenessNTU.fmu"
CONST_FMU = FMU_DIR / "SiteAHXConstantEffectiveness.fmu"

PAIR_MAP = {
    "T1Out": ("T1Out_s", "T1Out_m"),
    "T2Out": ("T2Out_s", "T2Out_m"),
    "Q": ("Q_s", "Q_m"),
}
WINDOW_ROWS = 288
WINDOW_STRIDE_ROWS = 12


def contiguous_runs(df: pd.DataFrame, step: float = 300.0) -> list[tuple[int, int]]:
    if df.empty:
        return []
    runs = []
    start = 0
    prev = float(df["time_s"].iloc[0])
    for idx, value in enumerate(df["time_s"].iloc[1:], start=1):
        cur = float(value)
        if abs(cur - prev - step) > 1e-6:
            runs.append((start, idx - 1))
            start = idx
        prev = cur
    runs.append((start, len(df) - 1))
    return runs


def select_window(table: pd.DataFrame, max_rows: int = WINDOW_ROWS, stride: int = WINDOW_STRIDE_ROWS) -> tuple[pd.DataFrame, dict[str, object]]:
    features = [c for c in ["T1In_m_C", "T1Out_m_C", "T2In_m_C", "T2Out_m_C", "m1_flow_kg_s", "m2_flow_kg_s", "Q_m_W"] if c in table]
    if table.empty:
        return table.copy(), {"rows": 0}
    if len(table) <= max_rows or not features:
        out = table.iloc[:max_rows].copy()
        out["time_s"] = np.arange(len(out), dtype=float) * 300.0
        return out, {"source_start_row": 0, "source_end_row": len(out) - 1, "rows": len(out), "representative_score": 0.0}

    full_mean = table[features].mean()
    scale = table[features].std().replace(0.0, 1.0).fillna(1.0)
    candidates: list[tuple[float, int, int]] = []
    for run_start, run_end in contiguous_runs(table):
        if run_end - run_start + 1 < max_rows:
            continue
        for start in range(run_start, run_end - max_rows + 2, stride):
            win = table.iloc[start : start + max_rows]
            score = float(((win[features].mean() - full_mean).abs() / scale).mean())
            candidates.append((score, start, start + max_rows - 1))
    if not candidates:
        start = 0
        end = min(len(table), max_rows) - 1
    else:
        _, start, end = sorted(candidates, key=lambda row: row[0])[0]
    out = table.iloc[start : end + 1].copy()
    out["time_s"] = np.arange(len(out), dtype=float) * 300.0
    return out, {"source_start_row": start, "source_end_row": end, "rows": len(out), "representative_score": sorted(candidates, key=lambda row: row[0])[0][0] if candidates else 0.0}


def build_candidate_grid(nominals: Mapping[str, object]) -> list[dict[str, float | str]]:
    eps0 = float(nominals.get("eps_nominal", 0.8))
    q0 = float(nominals.get("Q_flow_nominal", 1_000_000.0))
    m1 = float(nominals.get("m1_flow_nominal", 100.0))
    m2 = float(nominals.get("m2_flow_nominal", 100.0))
    grid: list[dict[str, float | str]] = []
    for q_scale in [0.7, 1.0, 1.3]:
        for flow_scale in [0.85, 1.0, 1.15]:
            grid.append(
                {
                    "model": "PlateEffectivenessNTU",
                    "m1_flow_nominal": m1 * flow_scale,
                    "m2_flow_nominal": m2 * flow_scale,
                    "Q_flow_nominal": q0 * q_scale,
                    "T_a1_nominal": float(nominals.get("T_a1_nominal", 295.15)),
                    "T_b1_nominal": float(nominals.get("T_b1_nominal", 290.15)),
                    "T_a2_nominal": float(nominals.get("T_a2_nominal", 285.15)),
                    "T_b2_nominal": float(nominals.get("T_b2_nominal", 290.15)),
                    "dp1_nominal": float(nominals.get("dp1_nominal", 0.0)),
                    "dp2_nominal": float(nominals.get("dp2_nominal", 0.0)),
                    "n1": 0.8,
                    "n2": 0.8,
                    "r_nominal": 1.0,
                }
            )
    for eps_scale in [0.75, 0.9, 1.0, 1.1, 1.25]:
        grid.append(
            {
                "model": "ConstantEffectiveness",
                "m1_flow_nominal": m1,
                "m2_flow_nominal": m2,
                "dp1_nominal": float(nominals.get("dp1_nominal", 0.0)),
                "dp2_nominal": float(nominals.get("dp2_nominal", 0.0)),
                "eps": float(np.clip(eps0 * eps_scale, 0.05, 0.98)),
            }
        )
    return grid


def start_values(table_txt: Path, candidate: Mapping[str, object]) -> dict[str, object]:
    values = {k: v for k, v in candidate.items() if k != "model"}
    values["table_path"] = str(table_txt.resolve()).replace("\\", "/")
    return values


def simulate_case(
    fmu: Path,
    values: Mapping[str, object],
    stop_time: float,
    log_path: Path | None = None,
    output_interval: float = 300.0,
) -> pd.DataFrame:
    try:
        from fmpy import simulate_fmu
    except ImportError as exc:  # pragma: no cover - depends on runtime environment.
        raise RuntimeError("fmpy is required to simulate HX FMUs") from exc

    out_buf = StringIO()
    err_buf = StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        result = simulate_fmu(
            str(fmu),
            start_values=dict(values),
            start_time=0.0,
            stop_time=stop_time,
            output=list({name for pair in PAIR_MAP.values() for name in pair}),
            output_interval=output_interval,
        )
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("STDOUT:\n" + out_buf.getvalue() + "\nSTDERR:\n" + err_buf.getvalue(), encoding="utf-8")
    return pd.DataFrame(result)


def flatten_metrics(result: pd.DataFrame, hx: str, model: str, period: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for variable, (sim_col, meas_col) in PAIR_MAP.items():
        if sim_col not in result or meas_col not in result:
            continue
        metric = compute_metrics(result[meas_col], result[sim_col])
        metric.update({"hx": hx, "model": model, "period": period, "variable": variable})
        rows.append(metric)
    return rows


def score_metrics(rows: list[dict[str, object]]) -> float:
    by_var = {row["variable"]: row for row in rows}
    t1 = float(by_var.get("T1Out", {}).get("CVRMSE", np.inf))
    t2 = float(by_var.get("T2Out", {}).get("CVRMSE", np.inf))
    q = float(by_var.get("Q", {}).get("CVRMSE", np.inf))
    return 2.0 * t1 + 2.0 * t2 + q


def select_best_candidate(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {}
    return sorted(rows, key=lambda row: float(row.get("score", np.inf)))[0]


def select_best_candidate_by_model(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if not rows:
        return []
    best_rows: list[dict[str, object]] = []
    models = sorted({str(row.get("model", "")) for row in rows})
    for model in models:
        model_rows = [row for row in rows if str(row.get("model", "")) == model]
        if model_rows:
            best_rows.append(select_best_candidate(model_rows))
    return best_rows


def _fmu_for_model(model: str) -> Path:
    return PLATE_FMU if model == "PlateEffectivenessNTU" else CONST_FMU


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not PLATE_FMU.exists() or not CONST_FMU.exists():
        print(f"Missing FMUs in {FMU_DIR}. Export Dymola FMUs first, then rerun.")
        return 2
    if not NOMINALS.exists():
        print(f"Missing nominal file: {NOMINALS}. Run prepare_site_a_hx_fmu_tables.py first.")
        return 1

    nominals = pd.read_csv(NOMINALS)
    all_metrics: list[dict[str, object]] = []
    best_rows: list[dict[str, object]] = []
    all_parameter_rows: list[dict[str, object]] = []
    model_best_rows: list[dict[str, object]] = []
    parameter_rows: list[dict[str, object]] = []
    failure_rows: list[dict[str, object]] = []

    for table_csv in sorted(TABLE_DIR.glob("HX_*_fmu_table.csv")):
        hx = table_csv.name.split("_fmu_table.csv")[0]
        table = pd.read_csv(table_csv)
        if table.empty:
            continue
        window, manifest = select_window(table)
        win_csv = OUT_DIR / f"{hx}_calibration_window.csv"
        win_txt = OUT_DIR / f"{hx}_calibration_window.txt"
        window.to_csv(win_csv, index=False, encoding="utf-8-sig")
        write_dymola_table(win_txt, window)
        nom_row = nominals.loc[nominals["hx"] == hx]
        if nom_row.empty or str(nom_row.iloc[0].get("status", "")) != "ready":
            continue
        candidate_results: list[dict[str, object]] = []
        for idx, candidate in enumerate(build_candidate_grid(nom_row.iloc[0].to_dict()), start=1):
            model = str(candidate["model"])
            values = start_values(win_txt, candidate)
            try:
                result = simulate_case(_fmu_for_model(model), values, float(window["time_s"].iloc[-1]), LOG_DIR / hx / model / f"candidate_{idx}.md")
            except Exception as exc:  # noqa: BLE001 - candidate-level FMU failures should not stop the batch.
                failure_rows.append(
                    {
                        "hx": hx,
                        "candidate_id": idx,
                        "model": model,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        **{k: v for k, v in candidate.items() if k != "model"},
                    }
                )
                continue
            metrics = flatten_metrics(result, hx, model, "calibration")
            score = score_metrics(metrics)
            for row in metrics:
                row.update({"candidate_id": idx, "score": score})
                all_metrics.append(row)
            candidate_result = {"hx": hx, "candidate_id": idx, "model": model, "score": score, "timeseries": "", **{k: v for k, v in candidate.items() if k != "model"}, **manifest}
            candidate_results.append(candidate_result)
            all_parameter_rows.append(candidate_result)
        best = select_best_candidate(candidate_results)
        if best:
            best_rows.append(best)
            parameter_rows.append(best)
        model_best_rows.extend(select_best_candidate_by_model(candidate_results))

    pd.DataFrame(all_metrics).to_csv(OUT_DIR / "site_a_hx_all_candidate_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(all_parameter_rows).to_csv(OUT_DIR / "site_a_hx_all_candidate_parameters.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(model_best_rows).to_csv(OUT_DIR / "site_a_hx_model_best_parameters.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(best_rows).to_csv(OUT_DIR / "site_a_hx_best_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(parameter_rows).to_csv(OUT_DIR / "site_a_hx_best_parameters.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(failure_rows).to_csv(OUT_DIR / "site_a_hx_failed_candidates.csv", index=False, encoding="utf-8-sig")
    print(f"Output: {OUT_DIR}")
    if failure_rows:
        print(f"Failed candidates: {len(failure_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
