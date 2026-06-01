"""Batch calibrate Site A cooling tower Merkel and YorkCalc FMUs on measured data."""

from __future__ import annotations

import itertools
import json
import logging
import math
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import Dict, Iterable, List, Mapping, Sequence

import numpy as np
import pandas as pd
from fmpy import simulate_fmu


ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "outputs" / "cooling_tower" / "site_a_tables"
OUT_DIR = ROOT / "outputs" / "cooling_tower" / "auto_model_site_a"
LOG_DIR = ROOT / "outputs" / "cooling_tower" / "logs" / "auto_model_site_a"
FMU_DIR = ROOT / "Cali_EIR_BSU_CH1" / "Modelica"
CTM_FMU = FMU_DIR / "CTM_0FMU.fmu"
CTY_FMU = FMU_DIR / "CTY_0FMU.fmu"

OUTPUTS = ["TOut_m", "TOut_s", "Q_m", "Q_s", "P_m", "P_s"]
PAIR_MAP = {"TOut": ("TOut_s", "TOut_m"), "Q": ("Q_s", "Q_m"), "P": ("P_s", "P_m")}
EXTERNAL_TOTAL_SCALE = 2.0
Y_MIN_DEFAULT = 0.05
TOUT_KELVIN_OFFSET = 273.15
TOUT_SCORE_WEIGHT = 5.0
DEFAULT_MERKEL_CWAT = {
    "merkel.UACor.cWatFra[1]": 0.1082,
    "merkel.UACor.cWatFra[2]": 1.667,
    "merkel.UACor.cWatFra[3]": -0.7713,
}
WINDOW_REPRESENTATIVE_FEATURES = [
    "TRan_C",
    "TAppAct_C",
    "mdot_cell_kgps",
    "y_used",
    "PFan_meas_W",
    "Q_flow_W",
]
CALIBRATION_WINDOWS = 3
WINDOW_ROWS = 288
WINDOW_STRIDE_ROWS = 12
WINDOW_MIN_SEPARATION_ROWS = 288


def find_longest_contiguous(df: pd.DataFrame, step: float = 300.0) -> tuple[int, int]:
    start = 0
    run = 1
    best = (0, 0, 1)
    prev = None
    for idx, t in enumerate(df["time_s"]):
        if idx == 0:
            prev = t
            continue
        if abs(t - prev - step) < 1e-6:
            run += 1
        else:
            if run > best[2]:
                best = (start, idx - 1, run)
            start = idx
            run = 1
        prev = t
    if run > best[2]:
        best = (start, len(df) - 1, run)
    return best[0], best[1]


def representative_window_candidates(
    table: pd.DataFrame,
    max_rows: int = WINDOW_ROWS,
    stride: int = WINDOW_STRIDE_ROWS,
) -> list[tuple[float, int, int]]:
    features = [col for col in WINDOW_REPRESENTATIVE_FEATURES if col in table.columns]
    if len(table) < max_rows or not features:
        start, end = find_longest_contiguous(table)
        return [(0.0, start, min(end, start + max_rows - 1))]

    full = table[features]
    full_mean = full.mean()
    full_q25 = full.quantile(0.25)
    full_q75 = full.quantile(0.75)
    scale = (full_q75 - full_q25).replace(0.0, np.nan).fillna(full.std()).replace(0.0, 1.0).fillna(1.0)

    candidates: list[tuple[float, int, int]] = []
    for run_start, run_end in contiguous_runs(table):
        if run_end - run_start + 1 < max_rows:
            continue
        for start in range(run_start, run_end - max_rows + 2, stride):
            win = table.iloc[start:start + max_rows]
            mean_score = ((win[features].mean() - full_mean).abs() / scale).mean()
            q25_score = ((win[features].quantile(0.25) - full_q25).abs() / scale).mean()
            q75_score = ((win[features].quantile(0.75) - full_q75).abs() / scale).mean()
            score = float(mean_score + 0.5 * q25_score + 0.5 * q75_score)
            candidates.append((score, start, start + max_rows - 1))

    if not candidates:
        start, end = find_longest_contiguous(table)
        return [(0.0, start, min(end, start + max_rows - 1))]
    return sorted(candidates, key=lambda row: row[0])


def select_windows(
    table: pd.DataFrame,
    n_windows: int = CALIBRATION_WINDOWS,
    max_rows: int = WINDOW_ROWS,
    min_separation: int = WINDOW_MIN_SEPARATION_ROWS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected: list[tuple[float, int, int]] = []
    for score, start, end in representative_window_candidates(table, max_rows=max_rows):
        overlaps = any(not (end < s - min_separation or start > e + min_separation) for _, s, e in selected)
        if overlaps:
            continue
        selected.append((score, start, end))
        if len(selected) >= n_windows:
            break

    if not selected:
        start, end = find_longest_contiguous(table)
        selected = [(0.0, start, min(end, start + max_rows - 1))]

    frames = []
    manifest_rows = []
    for idx, (score, start, end) in enumerate(selected, start=1):
        win = table.iloc[start:end + 1].copy()
        manifest_rows.append(
            {
                "window_id": idx,
                "representative_score": score,
                "source_start_row": start,
                "source_end_row": end,
                "source_start_time_s": float(win["time_s"].iloc[0]),
                "source_end_time_s": float(win["time_s"].iloc[-1]),
                "rows": len(win),
            }
        )
        frames.append(win)

    out = pd.concat(frames, ignore_index=True)
    out["time_s"] = np.arange(len(out), dtype=float) * 300.0
    return out, pd.DataFrame(manifest_rows)


def select_window(table: pd.DataFrame, max_rows: int = WINDOW_ROWS, stride: int = WINDOW_STRIDE_ROWS) -> pd.DataFrame:
    out, _ = select_windows(table, n_windows=1, max_rows=max_rows, min_separation=max_rows)
    return out


def contiguous_runs(df: pd.DataFrame, step: float = 300.0) -> list[tuple[int, int]]:
    runs = []
    start = 0
    prev = None
    for idx, t in enumerate(df["time_s"]):
        if idx == 0:
            prev = t
            continue
        if abs(t - prev - step) > 1e-6:
            runs.append((start, idx - 1))
            start = idx
        prev = t
    runs.append((start, len(df) - 1))
    return runs


def write_dymola_table(path: Path, table: pd.DataFrame) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("#1\n")
        f.write(f"double CT_data({len(table)},{len(table.columns)})\n")
        table.to_csv(f, header=False, index=False, line_terminator="\n", float_format="%.10g")


def fan_curve(alpha: float) -> Dict[str, float]:
    rv = [0.0, 0.1, 0.3, 0.6, 1.0]
    return {f"fanRelPow_r_P[{i+1}]": float(v**alpha) for i, v in enumerate(rv)}


def merkel_fan_curve(alpha: float) -> Dict[str, float]:
    rv = [0.0, 0.1, 0.3, 0.6, 1.0]
    return {f"merkel.fanRelPow.r_P[{i+1}]": float(v**alpha) for i, v in enumerate(rv)}


def estimate_pfan_nominal(table: pd.DataFrame, alpha: float, n_fan: float = 2.0) -> float:
    y = table["y_used"].clip(lower=0.05, upper=1.0)
    rel = y**alpha
    est = table["PFan_meas_W"] / (n_fan * rel)
    est = est.replace([np.inf, -np.inf], np.nan).dropna()
    est = est[est > 0]
    return float(est.median()) if len(est) else float(table["PFan_meas_W"].median() / n_fan)


def base_values(table_path: Path, table: pd.DataFrame) -> Dict[str, float | str]:
    return {
        "table_path": str(table_path).replace("\\", "/"),
        "m_flow_nominal": float(table["mdot_cell_kgps"].median()),
        "TAirInWB_nominal": float(table["Twb_C"].median() + 273.15),
        "TApp_nominal": float(table["TAppAct_C"].median()),
        "TRan_nominal": float(table["TRan_C"].median()),
        "TWatIn_nominal": float(table["Tin_C"].median() + 273.15),
        "TWatOut_nominal": float(table["Tout_meas_C"].median() + 273.15),
        # yMin is a physical/control lower bound, not a calibration-window
        # statistic. A high-speed 24 h window can otherwise make full-period
        # low-speed validation points fall below the model's operating range.
        "yMin": Y_MIN_DEFAULT,
        "nFan": 2.0,
        "fraFreCon": 0.1,
    }


def simulate_case(
    fmu: Path,
    start_values: Mapping[str, object],
    stop_time: float,
    log_path: Path | None = None,
) -> pd.DataFrame:
    out_buf = StringIO()
    err_buf = StringIO()
    log_buf = StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.INFO)
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    root_logger.addHandler(handler)
    if previous_level > logging.INFO:
        root_logger.setLevel(logging.INFO)
    try:
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            result = simulate_fmu(
                str(fmu),
                start_time=0,
                stop_time=stop_time,
                output_interval=300,
                output=OUTPUTS,
                start_values=dict(start_values),
                fmi_type="CoSimulation",
            )
    except Exception as exc:
        if log_path is not None:
            write_fmu_log(log_path, fmu, start_values, stop_time, out_buf, err_buf, log_buf, exception=exc)
        raise
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(previous_level)
    if log_path is not None:
        write_fmu_log(log_path, fmu, start_values, stop_time, out_buf, err_buf, log_buf)
    df = pd.DataFrame.from_records(result)
    # Site A measured Q/P are total tower values for two fans. Keep FMU thermal
    # calculations at one-fan/one-cell scale and apply the total scale here.
    df["Q_s"] = df["Q_s"] * EXTERNAL_TOTAL_SCALE
    df["P_s"] = df["P_s"] * EXTERNAL_TOTAL_SCALE
    return df


def write_fmu_log(
    log_path: Path,
    fmu: Path,
    start_values: Mapping[str, object],
    stop_time: float,
    stdout_buf: StringIO,
    stderr_buf: StringIO,
    logging_buf: StringIO,
    exception: Exception | None = None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fmu": str(fmu),
        "stop_time": stop_time,
        "start_values": {str(k): v for k, v in start_values.items()},
    }
    parts = [
        "# FMU simulation log",
        "",
        "## Metadata",
        "```json",
        json.dumps(payload, indent=2, default=str),
        "```",
        "",
        "## Python logging",
        "```text",
        logging_buf.getvalue().strip(),
        "```",
        "",
        "## stdout",
        "```text",
        stdout_buf.getvalue().strip(),
        "```",
        "",
        "## stderr",
        "```text",
        stderr_buf.getvalue().strip(),
        "```",
    ]
    if exception is not None:
        parts.extend(["", "## Exception", "```text", repr(exception), "```"])
    log_path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def metric_row(label: str, sim: Sequence[float], mea: Sequence[float]) -> Dict[str, float | int | str]:
    s = pd.to_numeric(pd.Series(sim), errors="coerce").to_numpy(float)
    m = pd.to_numeric(pd.Series(mea), errors="coerce").to_numpy(float)
    mask = np.isfinite(s) & np.isfinite(m)
    s = s[mask]
    m = m[mask]
    if label == "TOut":
        s = s - TOUT_KELVIN_OFFSET
        m = m - TOUT_KELVIN_OFFSET
    if len(s) == 0:
        return {"variable": label, "N": 0, "RMSE": math.nan, "MAE": math.nan, "MBE": math.nan,
                "NMBE_%": math.nan, "CVRMSE_%": math.nan, "MAPE_%": math.nan, "R2": math.nan}
    err = s - m
    mean_m = float(np.mean(m))
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((m - mean_m) ** 2))
    nz = np.abs(m) > 1e-9
    return {
        "variable": label,
        "N": int(len(s)),
        "RMSE": float(np.sqrt(np.mean(err**2))),
        "MAE": float(np.mean(np.abs(err))),
        "MBE": float(np.mean(err)),
        "NMBE_%": float(np.mean(err) / mean_m * 100.0) if mean_m else math.nan,
        "CVRMSE_%": float(np.sqrt(np.mean(err**2)) / mean_m * 100.0) if mean_m else math.nan,
        "MAPE_%": float(np.mean(np.abs(err[nz] / m[nz])) * 100.0) if np.any(nz) else math.nan,
        "R2": float(1.0 - ss_res / ss_tot) if ss_tot else math.nan,
    }


def metrics_wide(df: pd.DataFrame) -> Dict[str, float]:
    work = df[df["time"] >= 300].copy()
    out: Dict[str, float] = {}
    for label, (sim_col, mea_col) in PAIR_MAP.items():
        row = metric_row(label, work[sim_col], work[mea_col])
        for key, value in row.items():
            if key != "variable":
                out[f"{key}_{label}"] = value
    out["score"] = (
        out.get("CVRMSE_%_Q", 999.0)
        + out.get("CVRMSE_%_P", 999.0)
        + TOUT_SCORE_WEIGHT * out.get("RMSE_TOut", 999.0)
    )
    return out


def flatten_metrics(df: pd.DataFrame, tower: str, model: str, candidate: str) -> pd.DataFrame:
    work = df[df["time"] >= 300].copy()
    rows = []
    for label, (sim_col, mea_col) in PAIR_MAP.items():
        row = metric_row(label, work[sim_col], work[mea_col])
        row["tower"] = tower
        row["model"] = model
        row["candidate"] = candidate
        rows.append(row)
    return pd.DataFrame(rows)


def cty_values(base: Mapping[str, object], params: Mapping[str, object]) -> Dict[str, object]:
    values = {
        "tableFileName": base["table_path"],
        "m_flow_nominal": base["m_flow_nominal"],
        "TAirInWB_nominal": base["TAirInWB_nominal"],
        "TWatIn_nominal_start": base["TWatIn_nominal"],
        "TWatOut_nominal_start": base["TWatOut_nominal"],
        "yMin": base["yMin"],
        # The current CTY FMU still multiplies output expressions by nFan.
        # Force one-fan outputs here, then apply EXTERNAL_TOTAL_SCALE once.
        "nFan": 1.0,
        "fraFreCon": base["fraFreCon"],
    }
    values.update({k: v for k, v in params.items() if k not in {"fan_alpha", "kUA_scale_proxy"}})
    return values


def ctm_values(base: Mapping[str, object], params: Mapping[str, object]) -> Dict[str, object]:
    values = {
        "Tout1.fileName": base["table_path"],
        "merkel.TAirInWB_nominal": base["TAirInWB_nominal"],
        "merkel.TWatIn_nominal": base["TWatIn_nominal"],
        "merkel.TWatOut_nominal": base["TWatOut_nominal"],
        "merkel.yMin": base["yMin"],
        "merkel.fraFreCon": base["fraFreCon"],
    }
    values.update({k: v for k, v in params.items() if k not in {"fan_alpha", "kUA_scale_proxy"}})
    return values


def run_search_for_model(
    tower: str,
    model: str,
    fmu: Path,
    table: pd.DataFrame,
    base: Mapping[str, object],
    thermal_candidates: Iterable[Dict[str, object]],
    fan_alphas: Iterable[float],
    timeseries_dir: Path,
    log_dir: Path,
) -> tuple[Dict[str, object], pd.DataFrame, pd.DataFrame]:
    stop_time = float(table["time_s"].iloc[-1])
    all_rows: List[Dict[str, object]] = []
    best_thermal = None
    best_thermal_df = None
    best_thermal_score = (float("inf"), float("inf"))

    value_builder = cty_values if model == "YorkCalc" else ctm_values

    for idx, candidate in enumerate(thermal_candidates):
        try:
            log_path = log_dir / tower / model / f"thermal_{idx}.md"
            df = simulate_case(fmu, value_builder(base, candidate), stop_time, log_path=log_path)
            met = metrics_wide(df)
            row = {"tower": tower, "model": model, "stage": "thermal", "candidate": f"thermal_{idx}", **candidate, **met}
            all_rows.append(row)
            thermal_score = (met.get("CVRMSE_%_Q", float("inf")), met.get("RMSE_TOut", float("inf")))
            if thermal_score < best_thermal_score:
                best_thermal_score = thermal_score
                best_thermal = dict(candidate)
                best_thermal_df = df
        except Exception as exc:
            all_rows.append({"tower": tower, "model": model, "stage": "thermal", "candidate": f"thermal_{idx}", "error": str(exc), **candidate})

    if best_thermal is None:
        raise RuntimeError(f"No successful thermal candidate for {tower} {model}")

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
            log_path = log_dir / tower / model / f"fan_{alpha:g}.md"
            df = simulate_case(fmu, value_builder(base, candidate), stop_time, log_path=log_path)
            met = metrics_wide(df)
            row = {"tower": tower, "model": model, "stage": "fan", "candidate": f"fan_{alpha:g}", **candidate, **met}
            all_rows.append(row)
            if met.get("score", float("inf")) < best_score:
                best_score = met["score"]
                best = dict(candidate)
                best_df = df
        except Exception as exc:
            all_rows.append({"tower": tower, "model": model, "stage": "fan", "candidate": f"fan_{alpha:g}", "error": str(exc), **candidate})

    if best is None:
        best = best_thermal
        best_df = best_thermal_df

    ts_path = timeseries_dir / f"{tower}_{model}_best_timeseries.csv"
    best_df.to_csv(ts_path, index=False)
    best_metrics = flatten_metrics(best_df, tower, model, "best")
    best_metrics["timeseries"] = str(ts_path)
    best_row = {"tower": tower, "model": model, "score": best_score, "timeseries": str(ts_path), **best}
    return best_row, pd.DataFrame(all_rows), best_metrics


def build_candidates(model: str, base: Mapping[str, object]) -> List[Dict[str, object]]:
    if model == "YorkCalc":
        tapps = [max(0.2, float(base["TApp_nominal"]) * f) for f in [0.25, 0.5, 0.75, 1.0, 1.25]]
        trans = [max(0.3, float(base["TRan_nominal"]) * f) for f in [0.6, 0.85, 1.0, 1.2]]
        return [{"TApp_nominal": ta, "TRan_nominal": tr} for ta, tr in itertools.product(tapps, trans)]
    rats = [0.8, 1.0, 1.2, 1.5, 1.8]
    scales = [0.75, 1.0, 1.25, 1.5]
    out = []
    for rat, scale in itertools.product(rats, scales):
        candidate = {"merkel.ratWatAir_nominal": rat}
        for name, value in DEFAULT_MERKEL_CWAT.items():
            candidate[name] = value * scale
        candidate["kUA_scale_proxy"] = scale
        out.append(candidate)
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    windows_dir = OUT_DIR / "tables"
    timeseries_dir = OUT_DIR / "best_timeseries"
    windows_dir.mkdir(parents=True, exist_ok=True)
    timeseries_dir.mkdir(parents=True, exist_ok=True)

    best_rows = []
    candidate_frames = []
    metric_frames = []
    fan_alphas = [1.2, 1.6, 2.0, 2.5, 3.0]

    for csv_path in sorted(TABLES.glob("CT_*_fmu_table.csv")):
        tower = csv_path.name.split("_fmu_table.csv")[0]
        source = pd.read_csv(csv_path)
        if len(source) < 24:
            continue
        table, window_manifest = select_windows(source)
        table_path = windows_dir / f"{tower}_calibration_window.txt"
        write_dymola_table(table_path, table)
        base = base_values(table_path, table)
        (windows_dir / f"{tower}_base_values.json").write_text(json.dumps(base, indent=2), encoding="utf-8")
        table.to_csv(windows_dir / f"{tower}_calibration_window.csv", index=False)
        window_manifest.to_csv(windows_dir / f"{tower}_calibration_windows_manifest.csv", index=False)

        for model, fmu in [("Merkel", CTM_FMU), ("YorkCalc", CTY_FMU)]:
            best, candidates, best_metrics = run_search_for_model(
                tower=tower,
                model=model,
                fmu=fmu,
                table=table,
                base=base,
                thermal_candidates=build_candidates(model, base),
                fan_alphas=fan_alphas,
                timeseries_dir=timeseries_dir,
                log_dir=LOG_DIR / "calibration",
            )
            best_rows.append(best)
            candidate_frames.append(candidates)
            metric_frames.append(best_metrics)

    candidates_df = pd.concat(candidate_frames, ignore_index=True) if candidate_frames else pd.DataFrame()
    metrics_df = pd.concat(metric_frames, ignore_index=True) if metric_frames else pd.DataFrame()
    best_df = pd.DataFrame(best_rows)
    candidates_df.to_csv(OUT_DIR / "site_a_candidate_metrics.csv", index=False, encoding="utf-8-sig")
    metrics_df.to_csv(OUT_DIR / "site_a_best_metrics_long.csv", index=False, encoding="utf-8-sig")
    best_df.to_csv(OUT_DIR / "site_a_best_parameters.csv", index=False, encoding="utf-8-sig")

    print(f"Output: {OUT_DIR}")
    print(metrics_df[["tower", "model", "variable", "N", "RMSE", "CVRMSE_%", "NMBE_%", "R2"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
