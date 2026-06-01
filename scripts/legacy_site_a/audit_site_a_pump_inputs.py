"""Audit Site A pump input data and measured-flow mappings.

The script is intentionally read-only with respect to source data. It writes QA
artifacts under outputs/pump/qa so the pump FMU workflow can start from a
traceable inventory of available fields and usable points.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SITE_A = ROOT / "CT_Model" / "DATA" / "Site_A"
OUT_DIR = ROOT / "outputs" / "pump" / "qa"

KG_PER_L = 0.997
F_NOMINAL_HZ = 50.0
POWER_ON_W = 1000.0
FREQ_ON_HZ = 1.0
FLOW_ON_KGPS = 1.0


@dataclass(frozen=True)
class PumpMap:
    pump: str
    building: str
    pump_type: str
    pump_file: str
    flow_file: str
    flow_family: str
    source_kind: str


def build_default_pump_maps() -> list[PumpMap]:
    """Return the Site A pump-to-flow mapping confirmed for pump modelling."""
    maps: list[PumpMap] = []
    for idx in range(1, 4):
        maps.append(PumpMap(f"CHWP_{idx:02d}", "building1", "CHWP", f"CHWP_{idx:02d}.csv", f"CH_{idx:02d}.csv", "CHW", "CH"))
        maps.append(PumpMap(f"CDWP_{idx:02d}", "building1", "CDWP", f"CDWP_{idx:02d}.csv", f"CH_{idx:02d}.csv", "CDW", "CH"))
    maps.append(PumpMap("HXCWP_01", "building1", "HXCWP", "HXCWP_01.csv", "HX_01.csv", "CDW", "HX"))

    for idx in range(4, 6):
        maps.append(PumpMap(f"CHWP_{idx:02d}", "building2", "CHWP", f"CHWP_{idx:02d}.csv", f"CH_{idx:02d}.csv", "CHW", "CH"))
        maps.append(PumpMap(f"CDWP_{idx:02d}", "building2", "CDWP", f"CDWP_{idx:02d}.csv", f"CH_{idx:02d}.csv", "CDW", "CH"))
    maps.append(PumpMap("HXCWP_02", "building2", "HXCWP", "HXCWP_02.csv", "HX_02.csv", "CDW", "HX"))

    for idx in range(6, 8):
        maps.append(PumpMap(f"CHWP_{idx:02d}", "building3", "CHWP", f"CHWP_{idx:02d}.csv", f"CH_{idx:02d}.csv", "CHW", "CH"))
        maps.append(PumpMap(f"CDWP_{idx:02d}", "building3", "CDWP", f"CDWP_{idx:02d}.csv", f"CH_{idx:02d}.csv", "CDW", "CH"))
    maps.append(PumpMap("HXCWP_03", "building3", "HXCWP", "HXCWP_03.csv", "HX_03.csv", "CDW", "HX"))
    return maps


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "DateTime" in df.columns:
        df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
        df = df.dropna(subset=["DateTime"]).sort_values("DateTime")
    return df


def find_col(cols: Iterable[str], include: list[str], exclude: Optional[list[str]] = None) -> Optional[str]:
    exclude = exclude or []
    for col in cols:
        low = col.lower()
        if all(tok.lower() in low for tok in include) and not any(tok.lower() in low for tok in exclude):
            return col
    return None


def numeric(df: pd.DataFrame, col: Optional[str]) -> pd.Series:
    if not col or col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def percentile(series: pd.Series, q: float) -> float:
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return float("nan")
    return float(np.nanpercentile(clean.to_numpy(dtype=float), q, method="nearest"))


def find_flow_col(flow_df: pd.DataFrame, flow_family: str, source_kind: str) -> Optional[str]:
    cols = list(flow_df.columns)
    if source_kind == "HX":
        return find_col(cols, ["CDW", "WFM"])
    return find_col(cols, [flow_family, "WFM"])


def summarize_pump(
    pump: str,
    building: str,
    pump_type: str,
    pump_df: pd.DataFrame,
    flow_df: pd.DataFrame,
    flow_family: str,
    source_kind: str,
) -> dict[str, object]:
    pump_cols = list(pump_df.columns)
    flow_cols = list(flow_df.columns)

    power_col = "P/kw" if "P/kw" in pump_cols else find_col(pump_cols, ["kw"])
    ctrl_col = find_col(pump_cols, ["VSD", "CTRL"])
    sts_col = find_col(pump_cols, ["VSD", "STS"])
    run_col = find_col(pump_cols, ["RUN", "TIME"]) or find_col(pump_cols, ["RUN", "HOUR"])
    spd_sp_col = find_col(pump_cols, ["SPD", "SP"])
    flow_col = find_flow_col(flow_df, flow_family, source_kind)

    freq_col = sts_col or ctrl_col
    frequency_source = "VSD-STS" if sts_col else "VSD-CTRL" if ctrl_col else ""

    work = pd.DataFrame({"DateTime": pump_df["DateTime"] if "DateTime" in pump_df else pd.Series(dtype="datetime64[ns]")})
    work["P_m_W"] = numeric(pump_df, power_col) * 1000.0
    work["freq_Hz"] = numeric(pump_df, freq_col)
    work["freq_ctrl_Hz"] = numeric(pump_df, ctrl_col)
    work["freq_sts_Hz"] = numeric(pump_df, sts_col)

    if "DateTime" in flow_df and flow_col:
        flow = pd.DataFrame(
            {
                "DateTime": flow_df["DateTime"],
                "m_flow_m_kg_s": numeric(flow_df, flow_col).clip(lower=0.0) * KG_PER_L,
            }
        )
        work = work.merge(flow, on="DateTime", how="left")
    else:
        work["m_flow_m_kg_s"] = np.nan

    finite_power = work["P_m_W"].replace([np.inf, -np.inf], np.nan)
    finite_freq = work["freq_Hz"].replace([np.inf, -np.inf], np.nan)
    finite_flow = work["m_flow_m_kg_s"].replace([np.inf, -np.inf], np.nan)

    valid_power = finite_power.notna() & (finite_power > POWER_ON_W)
    valid_freq = finite_freq.notna() & (finite_freq > FREQ_ON_HZ)
    valid_flow = finite_flow.notna() & (finite_flow > FLOW_ON_KGPS)
    valid_basic = valid_power & valid_freq & valid_flow

    y = (finite_freq / F_NOMINAL_HZ).clip(lower=0.0)
    notes: list[str] = []
    if not flow_col:
        notes.append("missing mapped flow column")
    if not sts_col:
        notes.append("missing VSD-STS; used VSD-CTRL if available")
    if int(valid_basic.sum()) < 1000:
        notes.append("low aligned valid count")
    if pump_type == "HXCWP" and valid_flow.any() and percentile(finite_flow[valid_flow], 95) < 10.0:
        notes.append("HXCWP mapped flow p95 below 10 kg/s; verify HX flow mapping")

    return {
        "pump": pump,
        "building": building,
        "pump_type": pump_type,
        "rows": int(len(work)),
        "time_start": str(work["DateTime"].min()) if "DateTime" in work and len(work) else "",
        "time_end": str(work["DateTime"].max()) if "DateTime" in work and len(work) else "",
        "power_col": power_col or "",
        "freq_ctrl_col": ctrl_col or "",
        "freq_sts_col": sts_col or "",
        "frequency_source": frequency_source,
        "run_col": run_col or "",
        "spd_sp_col": spd_sp_col or "",
        "mapped_flow_col": flow_col or "",
        "power_nonnull": int(work["P_m_W"].notna().sum()),
        "freq_nonnull": int(work["freq_Hz"].notna().sum()),
        "flow_nonnull": int(work["m_flow_m_kg_s"].notna().sum()),
        "power_gt_1kW": int(valid_power.sum()),
        "freq_gt_1Hz": int(valid_freq.sum()),
        "flow_gt_1kgps": int(valid_flow.sum()),
        "aligned_valid_basic": int(valid_basic.sum()),
        "aligned_valid_pct": float(valid_basic.mean() * 100.0) if len(work) else float("nan"),
        "p95_power_kW": percentile(finite_power[valid_power] / 1000.0, 95),
        "p95_freq_Hz": percentile(finite_freq[valid_freq], 95),
        "p95_y": percentile(y[valid_freq], 95),
        "p95_flow_kg_s": percentile(finite_flow[valid_flow], 95),
        "max_power_kW": percentile(finite_power / 1000.0, 100),
        "max_freq_Hz": percentile(finite_freq, 100),
        "max_flow_kg_s": percentile(finite_flow, 100),
        "notes": "; ".join(notes),
    }


def audit_site_a(site_a: Path = SITE_A) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for mapping in build_default_pump_maps():
        pump_path = site_a / mapping.building / mapping.pump_file
        flow_path = site_a / mapping.building / mapping.flow_file
        if not pump_path.exists():
            rows.append(
                {
                    "pump": mapping.pump,
                    "building": mapping.building,
                    "pump_type": mapping.pump_type,
                    "rows": 0,
                    "notes": f"missing pump file: {pump_path}",
                }
            )
            continue
        if not flow_path.exists():
            rows.append(
                {
                    "pump": mapping.pump,
                    "building": mapping.building,
                    "pump_type": mapping.pump_type,
                    "rows": 0,
                    "notes": f"missing flow file: {flow_path}",
                }
            )
            continue
        rows.append(
            summarize_pump(
                pump=mapping.pump,
                building=mapping.building,
                pump_type=mapping.pump_type,
                pump_df=read_csv(pump_path),
                flow_df=read_csv(flow_path),
                flow_family=mapping.flow_family,
                source_kind=mapping.source_kind,
            )
        )
    return pd.DataFrame(rows)


def write_markdown_report(df: pd.DataFrame, path: Path) -> None:
    ranked = df.sort_values(["pump_type", "aligned_valid_basic"], ascending=[True, False])
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Site A Pump Input QA\n\n")
        f.write("Source data: `CT_Model/DATA/Site_A/{building}`\n\n")
        f.write("Thresholds: power > 1 kW, frequency > 1 Hz, flow > 1 kg/s. Frequency nominal is 50 Hz.\n\n")
        f.write("## Summary\n\n")
        f.write(f"- Pumps audited: {len(df)}\n")
        f.write(f"- CHWP: {int((df['pump_type'] == 'CHWP').sum())}\n")
        f.write(f"- CDWP: {int((df['pump_type'] == 'CDWP').sum())}\n")
        f.write(f"- HXCWP: {int((df['pump_type'] == 'HXCWP').sum())}\n\n")
        f.write("## Candidate Ranking\n\n")
        cols = [
            "pump",
            "building",
            "pump_type",
            "aligned_valid_basic",
            "p95_power_kW",
            "p95_freq_Hz",
            "p95_flow_kg_s",
            "notes",
        ]
        f.write(markdown_table(ranked[cols]))
        f.write("\n")


def markdown_table(df: pd.DataFrame) -> str:
    """Render a small markdown table without optional pandas dependencies."""
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
    qa = audit_site_a()
    csv_path = OUT_DIR / "site_a_pump_input_qa.csv"
    md_path = OUT_DIR / "site_a_pump_input_qa.md"
    qa.to_csv(csv_path, index=False)
    write_markdown_report(qa, md_path)
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    print(qa[["pump", "building", "pump_type", "aligned_valid_basic", "p95_power_kW", "p95_freq_Hz", "p95_flow_kg_s", "notes"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
