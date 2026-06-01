"""Estimate Site A pump nominal values from prepared FMU input tables."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TABLE_DIR = ROOT / "outputs" / "pump" / "site_a_tables"
TABLE_QA = TABLE_DIR / "site_a_pump_table_qa.csv"
OUT_DIR = ROOT / "outputs" / "pump" / "nominals"

F_NOMINAL_HZ = 50.0
PERCENTILE_METHOD = "nearest"


def pct(series: Iterable[float], q: float) -> float:
    clean = pd.to_numeric(pd.Series(series), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return float("nan")
    return float(np.nanpercentile(clean.to_numpy(dtype=float), q, method=PERCENTILE_METHOD))


def estimate_nominals(table: pd.DataFrame, pump: str, table_qa: dict[str, object] | None = None) -> dict[str, object]:
    table_qa = table_qa or {}
    clean = table.copy()
    for col in ["m_flow_kg_s", "y_used", "freq_Hz", "P_meas_W"]:
        clean[col] = pd.to_numeric(clean[col], errors="coerce")
    clean = clean.replace([np.inf, -np.inf], np.nan).dropna(subset=["m_flow_kg_s", "y_used", "freq_Hz", "P_meas_W"])
    clean = clean[(clean["m_flow_kg_s"] > 0.0) & (clean["y_used"] > 0.0) & (clean["P_meas_W"] > 0.0)].copy()

    first = clean.iloc[0] if not clean.empty else {}
    m_flow_p95 = pct(clean["m_flow_kg_s"], 95)
    p_p95 = pct(clean["P_meas_W"], 95)
    y_p95 = pct(clean["y_used"], 95)
    freq_p95 = pct(clean["freq_Hz"], 95)

    notes: list[str] = [
        "head/dp not measured; dp_nominal and head_nominal cannot be independently estimated",
    ]
    if len(clean) < 288:
        notes.append("less than one 24-hour valid window")
    if str(first.get("pump_type", "")) == "HXCWP" and m_flow_p95 < 10.0:
        notes.append("HXCWP low flow p95; verify mapped HX flow before hydraulic modelling")
    raw_qa_note = table_qa.get("notes", "")
    qa_note = "" if pd.isna(raw_qa_note) else str(raw_qa_note).strip()
    if qa_note and qa_note.lower() != "nan":
        notes.append(f"table QA: {qa_note}")

    return {
        "pump": pump,
        "building": first.get("building", ""),
        "pump_type": first.get("pump_type", ""),
        "rows_valid": int(len(clean)),
        "table_qa_rows_valid": table_qa.get("rows_valid", np.nan),
        "table_qa_source_p95_m_flow_kg_s": table_qa.get("source_p95_m_flow_kg_s", np.nan),
        "table_qa_aligned_p95_m_flow_kg_s": table_qa.get("aligned_p95_m_flow_kg_s", np.nan),
        "freq_nominal_Hz": F_NOMINAL_HZ,
        "freq_p95_Hz": freq_p95,
        "y_nominal_basis": "freq_Hz / 50Hz",
        "y_p95": y_p95,
        "y_min_recommended": 0.05,
        "y_max_recommended": 1.20,
        "m_flow_nominal_kg_s": m_flow_p95,
        "m_flow_p50_kg_s": pct(clean["m_flow_kg_s"], 50),
        "m_flow_p95_kg_s": m_flow_p95,
        "m_flow_p99_kg_s": pct(clean["m_flow_kg_s"], 99),
        "P_nominal_W": p_p95,
        "P_p50_W": pct(clean["P_meas_W"], 50),
        "P_p95_W": p_p95,
        "P_p99_W": pct(clean["P_meas_W"], 99),
        "head_available": False,
        "dp_nominal_Pa": np.nan,
        "head_nominal_m": np.nan,
        "dp_nominal_Pa_status": "not_measured",
        "head_nominal_m_status": "not_measured",
        "recommended_first_model": "empirical_power_from_flow_and_speed",
        "future_hydraulic_model_requirement": "measured pump head/DP or an explicitly assumed system curve",
        "notes": "; ".join(notes),
    }


def estimate_all(table_dir: Path = TABLE_DIR, table_qa_path: Path = TABLE_QA) -> pd.DataFrame:
    qa_by_pump: dict[str, dict[str, object]] = {}
    if table_qa_path.exists():
        qa = pd.read_csv(table_qa_path)
        qa_by_pump = {str(row["pump"]): row.to_dict() for _, row in qa.iterrows()}
    rows: list[dict[str, object]] = []
    for path in sorted(table_dir.glob("*_fmu_table.csv")):
        pump = path.name.replace("_fmu_table.csv", "")
        table = pd.read_csv(path)
        rows.append(estimate_nominals(table, pump=pump, table_qa=qa_by_pump.get(pump)))
    return pd.DataFrame(rows)


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


def write_report(nominals: pd.DataFrame, path: Path) -> None:
    cols = [
        "pump",
        "building",
        "pump_type",
        "rows_valid",
        "table_qa_source_p95_m_flow_kg_s",
        "m_flow_nominal_kg_s",
        "P_nominal_W",
        "freq_nominal_Hz",
        "freq_p95_Hz",
        "head_available",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Site A Pump Nominal Parameter Estimates\n\n")
        f.write("Nominals are estimated from prepared full-valid-period pump FMU tables.\n\n")
        f.write("- `m_flow_nominal_kg_s`: 95th percentile of valid mapped measured flow.\n")
        f.write("- `P_nominal_W`: 95th percentile of valid measured electrical pump power.\n")
        f.write("- `freq_nominal_Hz`: fixed at 50 Hz from project assumption.\n")
        f.write("- `dp_nominal_Pa` and `head_nominal_m`: not estimated because pump head/DP is not measured.\n\n")
        f.write(markdown_table(nominals.sort_values(["pump_type", "pump"])[cols]))
        f.write("\n")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nominals = estimate_all()
    csv_path = OUT_DIR / "site_a_pump_nominals.csv"
    md_path = OUT_DIR / "site_a_pump_nominals.md"
    nominals.to_csv(csv_path, index=False)
    write_report(nominals, md_path)
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    print(
        nominals[
            [
                "pump",
                "building",
                "pump_type",
                "rows_valid",
                "m_flow_nominal_kg_s",
                "P_nominal_W",
                "freq_nominal_Hz",
                "freq_p95_Hz",
                "head_available",
                "notes",
            ]
        ].to_string(index=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
