"""Prepare Site A pump FMU input tables from structured BMS CSV files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    from audit_site_a_pump_inputs import (
        F_NOMINAL_HZ,
        FLOW_ON_KGPS,
        FREQ_ON_HZ,
        KG_PER_L,
        POWER_ON_W,
        PumpMap,
        build_default_pump_maps,
        find_col,
        find_flow_col,
        numeric,
        read_csv,
    )
except ModuleNotFoundError:
    from scripts.audit_site_a_pump_inputs import (
        F_NOMINAL_HZ,
        FLOW_ON_KGPS,
        FREQ_ON_HZ,
        KG_PER_L,
        POWER_ON_W,
        PumpMap,
        build_default_pump_maps,
        find_col,
        find_flow_col,
        numeric,
        read_csv,
    )


ROOT = Path(__file__).resolve().parents[1]
SITE_A = ROOT / "CT_Model" / "DATA" / "Site_A"
OUT_DIR = ROOT / "outputs" / "pump" / "site_a_tables"

WINDOW_ROWS = 288
WINDOW_STRIDE_ROWS = 12
WINDOW_MIN_SEPARATION_ROWS = 288
REPRESENTATIVE_FEATURES = ["m_flow_kg_s", "y_used", "P_meas_W"]
NUMERIC_FMU_COLUMNS = ["time_s", "m_flow_kg_s", "y_used", "freq_Hz", "P_meas_W"]


@dataclass(frozen=True)
class PumpTableResult:
    table: pd.DataFrame
    window_table: pd.DataFrame
    window_manifest: pd.DataFrame
    qa: dict[str, object]


def contiguous_runs(df: pd.DataFrame, step: float = 300.0) -> list[tuple[int, int]]:
    if df.empty:
        return []
    runs: list[tuple[int, int]] = []
    start = 0
    prev = float(df["time_s"].iloc[0])
    for idx, value in enumerate(df["time_s"].iloc[1:], start=1):
        current = float(value)
        if abs(current - prev - step) > 1e-6:
            runs.append((start, idx - 1))
            start = idx
        prev = current
    runs.append((start, len(df) - 1))
    return runs


def representative_window_candidates(
    table: pd.DataFrame,
    max_rows: int = WINDOW_ROWS,
    stride: int = WINDOW_STRIDE_ROWS,
) -> list[tuple[float, int, int]]:
    features = [col for col in REPRESENTATIVE_FEATURES if col in table.columns]
    if table.empty:
        return []
    if len(table) < max_rows or not features:
        runs = contiguous_runs(table)
        if not runs:
            return []
        start, end = max(runs, key=lambda row: row[1] - row[0])
        return [(0.0, start, min(end, start + max_rows - 1))]

    full = table[features]
    full_mean = full.mean()
    full_q25 = full.quantile(0.25)
    full_q75 = full.quantile(0.75)
    scale = (full_q75 - full_q25).replace(0.0, np.nan)
    scale = scale.fillna(full.std()).replace(0.0, 1.0).fillna(1.0)

    candidates: list[tuple[float, int, int]] = []
    for run_start, run_end in contiguous_runs(table):
        if run_end - run_start + 1 < max_rows:
            continue
        for start in range(run_start, run_end - max_rows + 2, stride):
            win = table.iloc[start:start + max_rows]
            mean_score = ((win[features].mean() - full_mean).abs() / scale).mean()
            q25_score = ((win[features].quantile(0.25) - full_q25).abs() / scale).mean()
            q75_score = ((win[features].quantile(0.75) - full_q75).abs() / scale).mean()
            candidates.append((float(mean_score + 0.5 * q25_score + 0.5 * q75_score), start, start + max_rows - 1))

    if candidates:
        return sorted(candidates, key=lambda row: row[0])

    runs = contiguous_runs(table)
    if not runs:
        return []
    start, end = max(runs, key=lambda row: row[1] - row[0])
    return [(0.0, start, min(end, start + max_rows - 1))]


def select_windows(
    table: pd.DataFrame,
    n_windows: int = 3,
    max_rows: int = WINDOW_ROWS,
    min_separation: int = WINDOW_MIN_SEPARATION_ROWS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected: list[tuple[float, int, int]] = []
    for score, start, end in representative_window_candidates(table, max_rows=max_rows):
        overlaps = any(not (end < prev_start - min_separation or start > prev_end + min_separation) for _, prev_start, prev_end in selected)
        if overlaps:
            continue
        selected.append((score, start, end))
        if len(selected) >= n_windows:
            break

    frames: list[pd.DataFrame] = []
    manifest_rows: list[dict[str, object]] = []
    for window_id, (score, start, end) in enumerate(selected, start=1):
        win = table.iloc[start:end + 1].copy()
        if win.empty:
            continue
        manifest_rows.append(
            {
                "window_id": window_id,
                "representative_score": score,
                "source_start_row": start,
                "source_end_row": end,
                "source_start_datetime": str(win["DateTime"].iloc[0]),
                "source_end_datetime": str(win["DateTime"].iloc[-1]),
                "source_start_time_s": float(win["time_s"].iloc[0]),
                "source_end_time_s": float(win["time_s"].iloc[-1]),
                "rows": len(win),
            }
        )
        frames.append(win)

    if not frames:
        return table.iloc[0:0].copy(), pd.DataFrame(manifest_rows)

    out = pd.concat(frames, ignore_index=True)
    out["time_s"] = np.arange(len(out), dtype=float) * 300.0
    return out, pd.DataFrame(manifest_rows)


def build_pump_table(mapping: PumpMap, site_a: Path = SITE_A) -> PumpTableResult:
    pump_path = site_a / mapping.building / mapping.pump_file
    flow_path = site_a / mapping.building / mapping.flow_file
    if not pump_path.exists():
        return empty_result(mapping, f"missing pump file: {pump_path}")
    if not flow_path.exists():
        return empty_result(mapping, f"missing flow file: {flow_path}")

    pump_df = read_csv(pump_path)
    flow_df = read_csv(flow_path)
    pump_cols = list(pump_df.columns)

    power_col = "P/kw" if "P/kw" in pump_cols else find_col(pump_cols, ["kw"])
    ctrl_col = find_col(pump_cols, ["VSD", "CTRL"])
    sts_col = find_col(pump_cols, ["VSD", "STS"])
    freq_col = sts_col or ctrl_col
    frequency_source = "VSD-STS" if sts_col else "VSD-CTRL" if ctrl_col else ""
    flow_col = find_flow_col(flow_df, mapping.flow_family, mapping.source_kind)

    work = pd.DataFrame({"DateTime": pump_df["DateTime"]})
    work["pump"] = mapping.pump
    work["building"] = mapping.building
    work["pump_type"] = mapping.pump_type
    work["P_meas_W"] = numeric(pump_df, power_col) * 1000.0
    work["freq_Hz"] = numeric(pump_df, freq_col)
    work["y_used"] = (work["freq_Hz"] / F_NOMINAL_HZ).clip(lower=0.0, upper=1.0)
    work["power_source"] = power_col or ""
    work["frequency_source"] = frequency_source
    work["flow_source"] = flow_col or ""

    if flow_col:
        flow = pd.DataFrame(
            {
                "DateTime": flow_df["DateTime"],
                "m_flow_kg_s": numeric(flow_df, flow_col).clip(lower=0.0) * KG_PER_L,
            }
        )
        work = work.merge(flow, on="DateTime", how="left")
    else:
        work["m_flow_kg_s"] = np.nan

    valid = valid_mask(work)
    table = work.loc[valid].copy()
    if not table.empty:
        first = table["DateTime"].iloc[0]
        table["time_s"] = (table["DateTime"] - first).dt.total_seconds()
    else:
        table["time_s"] = pd.Series(dtype=float)
    table["valid_for_fmu"] = True

    table = table[
        [
            "time_s",
            "DateTime",
            "pump",
            "building",
            "pump_type",
            "m_flow_kg_s",
            "y_used",
            "freq_Hz",
            "P_meas_W",
            "valid_for_fmu",
            "flow_source",
            "power_source",
            "frequency_source",
        ]
    ]
    window_table, window_manifest = select_windows(table)
    source_flow = pd.to_numeric(work["m_flow_kg_s"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    source_flow = source_flow[source_flow > FLOW_ON_KGPS]
    source_flow_p95 = float(source_flow.quantile(0.95)) if len(source_flow) else np.nan
    aligned_flow_p95 = float(table["m_flow_kg_s"].quantile(0.95)) if not table.empty else np.nan
    qa = {
        "pump": mapping.pump,
        "building": mapping.building,
        "pump_type": mapping.pump_type,
        "rows_raw": len(work),
        "rows_valid": len(table),
        "valid_%": float(valid.mean() * 100.0) if len(valid) else np.nan,
        "start_valid": str(table["DateTime"].min()) if not table.empty else "",
        "end_valid": str(table["DateTime"].max()) if not table.empty else "",
        "flow_source": flow_col or "",
        "power_source": power_col or "",
        "frequency_source": frequency_source,
        "median_m_flow_kg_s": float(table["m_flow_kg_s"].median()) if not table.empty else np.nan,
        "source_p95_m_flow_kg_s": source_flow_p95,
        "aligned_p95_m_flow_kg_s": aligned_flow_p95,
        "median_y": float(table["y_used"].median()) if not table.empty else np.nan,
        "median_P_meas_W": float(table["P_meas_W"].median()) if not table.empty else np.nan,
        "windows_selected": int(len(window_manifest)),
        "window_rows": int(len(window_table)),
        "notes": note_for_table(mapping, table, flow_col, sts_col, source_flow_p95),
    }
    return PumpTableResult(table=table, window_table=window_table, window_manifest=window_manifest, qa=qa)


def valid_mask(df: pd.DataFrame) -> pd.Series:
    finite_power = df["P_meas_W"].replace([np.inf, -np.inf], np.nan)
    finite_freq = df["freq_Hz"].replace([np.inf, -np.inf], np.nan)
    finite_flow = df["m_flow_kg_s"].replace([np.inf, -np.inf], np.nan)
    valid = finite_power.notna() & finite_freq.notna() & finite_flow.notna()
    valid &= finite_power > POWER_ON_W
    valid &= finite_freq > FREQ_ON_HZ
    valid &= finite_flow > FLOW_ON_KGPS
    return valid


def note_for_table(
    mapping: PumpMap,
    table: pd.DataFrame,
    flow_col: Optional[str],
    sts_col: Optional[str],
    source_flow_p95: float,
) -> str:
    notes: list[str] = []
    if not flow_col:
        notes.append("missing mapped flow column")
    if not sts_col:
        notes.append("missing VSD-STS; used VSD-CTRL if available")
    if len(table) < WINDOW_ROWS:
        notes.append("less than one 24-hour valid window")
    if mapping.pump_type == "HXCWP" and not np.isnan(source_flow_p95) and source_flow_p95 < 10.0:
        notes.append("HXCWP source mapped flow p95 below 10 kg/s; verify HX flow mapping")
    return "; ".join(notes)


def empty_result(mapping: PumpMap, note: str) -> PumpTableResult:
    columns = [
        "time_s",
        "DateTime",
        "pump",
        "building",
        "pump_type",
        "m_flow_kg_s",
        "y_used",
        "freq_Hz",
        "P_meas_W",
        "valid_for_fmu",
        "flow_source",
        "power_source",
        "frequency_source",
    ]
    table = pd.DataFrame(columns=columns)
    qa = {
        "pump": mapping.pump,
        "building": mapping.building,
        "pump_type": mapping.pump_type,
        "rows_raw": 0,
        "rows_valid": 0,
        "valid_%": np.nan,
        "start_valid": "",
        "end_valid": "",
        "flow_source": "",
        "power_source": "",
        "frequency_source": "",
        "median_m_flow_kg_s": np.nan,
        "source_p95_m_flow_kg_s": np.nan,
        "aligned_p95_m_flow_kg_s": np.nan,
        "median_y": np.nan,
        "median_P_meas_W": np.nan,
        "windows_selected": 0,
        "window_rows": 0,
        "notes": note,
    }
    return PumpTableResult(table=table, window_table=table.copy(), window_manifest=pd.DataFrame(), qa=qa)


def write_dymola_table(path: Path, table: pd.DataFrame, table_name: str = "Pump_data") -> None:
    numeric_table = table[NUMERIC_FMU_COLUMNS].copy()
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("#1\n")
        f.write(f"double {table_name}({len(numeric_table)},{len(numeric_table.columns)})\n")
        numeric_table.to_csv(f, header=False, index=False, line_terminator="\n", float_format="%.10g")


def write_markdown_report(qa: pd.DataFrame, path: Path) -> None:
    ranked = qa.sort_values(["rows_valid"], ascending=[False])
    cols = [
        "pump",
        "building",
        "pump_type",
        "rows_valid",
        "windows_selected",
        "median_m_flow_kg_s",
        "source_p95_m_flow_kg_s",
        "aligned_p95_m_flow_kg_s",
        "median_y",
        "median_P_meas_W",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Site A Pump FMU Table QA\n\n")
        f.write("Generated from `CT_Model/DATA/Site_A/{building}` pump and mapped flow files.\n\n")
        f.write(f"- Pumps processed: {len(qa)}\n")
        f.write(f"- Pumps with at least one 24-hour window: {int((qa['windows_selected'] > 0).sum())}\n\n")
        f.write(markdown_table(ranked[cols]))
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
                values.append("" if np.isnan(val) else f"{val:.3g}")
            else:
                values.append(str(val).replace("|", "/"))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    qa_rows: list[dict[str, object]] = []
    for mapping in build_default_pump_maps():
        result = build_pump_table(mapping)
        result.table.to_csv(OUT_DIR / f"{mapping.pump}_fmu_table.csv", index=False)
        write_dymola_table(OUT_DIR / f"{mapping.pump}_fmu_table.txt", result.table)
        result.window_table.to_csv(OUT_DIR / f"{mapping.pump}_window_table.csv", index=False)
        result.window_manifest.to_csv(OUT_DIR / f"{mapping.pump}_window_manifest.csv", index=False)
        qa_rows.append(result.qa)

    qa = pd.DataFrame(qa_rows)
    qa_path = OUT_DIR / "site_a_pump_table_qa.csv"
    report_path = OUT_DIR / "site_a_pump_table_qa.md"
    qa.to_csv(qa_path, index=False)
    write_markdown_report(qa, report_path)

    print(f"Wrote {qa_path}")
    print(f"Wrote {report_path}")
    print(
        qa[
            [
                "pump",
                "building",
                "pump_type",
                "rows_valid",
                "windows_selected",
                "median_m_flow_kg_s",
                "source_p95_m_flow_kg_s",
                "aligned_p95_m_flow_kg_s",
                "median_y",
                "median_P_meas_W",
                "notes",
            ]
        ].to_string(index=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
