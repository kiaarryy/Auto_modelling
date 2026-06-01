"""Audit Site A cooling tower CSV inputs for FMU simulation readiness."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SITE_A = ROOT / "CT_Model" / "DATA" / "Site_A"
CT_DIR = SITE_A / "cooling_tower"
WET_BULB = SITE_A / "WET_BALL" / "OUTDOOR" / "Local_IO.RF1-OUTDOOR_202405_202504_with_Twb.csv"
OUT_DIR = ROOT / "outputs" / "cooling_tower" / "site_a_input_audit"


def columns_matching(columns: Iterable[str], *needles: str) -> List[str]:
    matches = []
    for col in columns:
        low = col.lower()
        if all(needle.lower() in low for needle in needles):
            matches.append(col)
    return matches


def first_existing(df: pd.DataFrame, columns: List[str]) -> pd.Series:
    if not columns:
        return pd.Series(index=df.index, dtype=float)
    return pd.to_numeric(df[columns[0]], errors="coerce")


def combined_non_null_rate(df: pd.DataFrame, columns: List[str]) -> float:
    if not columns:
        return 0.0
    return float(df[columns].apply(pd.to_numeric, errors="coerce").notna().any(axis=1).mean())


def all_non_null_rate(df: pd.DataFrame, columns: List[str]) -> float:
    if not columns:
        return 0.0
    return float(df[columns].apply(pd.to_numeric, errors="coerce").notna().all(axis=1).mean())


def load_wetbulb() -> pd.DataFrame:
    wet = pd.read_csv(WET_BULB)
    wet["DateTime"] = pd.to_datetime(wet["DateTime"], errors="coerce")
    wet["Twb"] = pd.to_numeric(wet.get("Twb (°C)"), errors="coerce")
    return wet[["DateTime", "Twb"]].dropna(subset=["DateTime"])


def audit_file(path: Path, wet: pd.DataFrame) -> Dict[str, object]:
    df = pd.read_csv(path)
    df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
    cols = list(df.columns)

    fan_ctrl = [c for c in cols if "VSD-CTRL" in c]
    fan_status = [c for c in cols if "VSD-STS" in c]
    bypass = [c for c in cols if "BPV" in c]
    t_in = [c for c in cols if "CDWR-WTS" in c]
    t_out = [c for c in cols if "CDWS-WTS" in c]
    pressure = [c for c in cols if "WPS" in c]
    power = [c for c in cols if c.lower() == "p/kw"]
    run = [c for c in cols if "RUN-" in c]
    wet_cols = [c for c in cols if "twb" in c.lower() or "wet" in c.lower()]
    flow = [
        c for c in cols
        if any(tok in c.lower() for tok in ["flow", "wfm", "lps", "kg/s", "kg_s", "m3/s", "m^3/s"])
        and "bpv" not in c.lower()
    ]

    merged = df[["DateTime"]].merge(wet, on="DateTime", how="left")
    tower_id = path.stem
    fan_names = []
    for c in fan_ctrl + fan_status:
        part = c.split(".")[0]
        if part not in fan_names:
            fan_names.append(part)

    row = {
        "file": path.name,
        "tower": tower_id,
        "rows": len(df),
        "start": df["DateTime"].min(),
        "end": df["DateTime"].max(),
        "columns": len(cols),
        "fan_signal_columns": "; ".join(fan_ctrl),
        "fan_status_columns": "; ".join(fan_status),
        "fan_signal_any_non_null_%": combined_non_null_rate(df, fan_ctrl) * 100.0,
        "fan_status_any_non_null_%": combined_non_null_rate(df, fan_status) * 100.0,
        "bypass_columns": "; ".join(bypass),
        "bypass_any_non_null_%": combined_non_null_rate(df, bypass) * 100.0,
        "T_in_columns_CDWR": "; ".join(t_in),
        "T_in_non_null_%": combined_non_null_rate(df, t_in) * 100.0,
        "T_out_columns_CDWS": "; ".join(t_out),
        "T_out_non_null_%": combined_non_null_rate(df, t_out) * 100.0,
        "pressure_columns_not_flow": "; ".join(pressure),
        "power_columns": "; ".join(power),
        "power_non_null_%": combined_non_null_rate(df, power) * 100.0,
        "wetbulb_columns_inside_ct_csv": "; ".join(wet_cols),
        "wetbulb_inside_ct_non_null_%": combined_non_null_rate(df, wet_cols) * 100.0,
        "wetbulb_join_non_null_%": float(merged["Twb"].notna().mean() * 100.0),
        "flow_columns": "; ".join(flow),
        "flow_any_non_null_%": combined_non_null_rate(df, flow) * 100.0,
        "run_columns": "; ".join(run),
        "run_any_non_null_%": combined_non_null_rate(df, run) * 100.0,
        "fmuready_without_external_flow": bool(t_in and t_out and power and fan_ctrl and (flow or False) and merged["Twb"].notna().any()),
        "missing_for_fmu": "",
    }

    missing = []
    if not t_in:
        missing.append("T_in/CDWR")
    if not t_out:
        missing.append("T_out/CDWS")
    if not power:
        missing.append("P/kw")
    if not fan_ctrl and not fan_status:
        missing.append("fan signal/status")
    if not flow:
        missing.append("tower water flow")
    if merged["Twb"].notna().mean() == 0:
        missing.append("wet-bulb join")
    row["missing_for_fmu"] = "; ".join(missing)
    return row


def write_report(audit: pd.DataFrame, wet: pd.DataFrame) -> None:
    lines = [
        "# Site A Cooling Tower Input Audit",
        "",
        f"- Source folder: `{SITE_A}`",
        f"- Cooling tower CSV folder: `{CT_DIR}`",
        f"- Wet-bulb file: `{WET_BULB}`",
        f"- Wet-bulb rows: {len(wet)}",
        f"- Wet-bulb valid rate: {wet['Twb'].notna().mean() * 100.0:.2f}%",
        "",
        "## Summary",
        "",
        "- `CT_01..CT_07.csv` contain tower inlet/outlet temperatures, fan signal/status information, and `P/kw` fan power.",
        "- Wet-bulb temperature is available in the separate `WET_BALL` file and can be joined by `DateTime`; it is not embedded in the CT CSV files.",
        "- None of the seven CT CSV files contains a tower water flow column (`WFM`, `flow`, `lps`, `kg/s`, or similar). The `CDWS-WPS` columns are pressure, not flow.",
        "- Therefore the current blocking input for FMU simulation is tower water flow. If no tower-specific flow meter exists, a flow allocation rule from system/chiller/HX flow is required.",
        "",
        "## Per-file Readiness",
        "",
        "| file | T_in % | T_out % | fan signal % | fan status % | P % | wet-bulb join % | flow % | missing |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for _, row in audit.iterrows():
        lines.append(
            f"| {row['file']} | {row['T_in_non_null_%']:.1f} | {row['T_out_non_null_%']:.1f} | "
            f"{row['fan_signal_any_non_null_%']:.1f} | {row['fan_status_any_non_null_%']:.1f} | "
            f"{row['power_non_null_%']:.1f} | {row['wetbulb_join_non_null_%']:.1f} | "
            f"{row['flow_any_non_null_%']:.1f} | {row['missing_for_fmu']} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "`flow` is the actual mass-flow input required by the FMU. `allocation` is only needed when this tower-specific flow is not directly measured; it is the rule used to estimate each tower's flow share from a larger system or branch flow.",
    ]
    (OUT_DIR / "site_a_ct_input_audit.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wet = load_wetbulb()
    rows = [audit_file(path, wet) for path in sorted(CT_DIR.glob("CT_*.csv"))]
    audit = pd.DataFrame(rows)
    audit.to_csv(OUT_DIR / "site_a_ct_input_audit.csv", index=False, encoding="utf-8-sig")
    write_report(audit, wet)
    print(f"CSV: {OUT_DIR / 'site_a_ct_input_audit.csv'}")
    print(f"Report: {OUT_DIR / 'site_a_ct_input_audit.md'}")
    print(audit[[
        "file", "T_in_non_null_%", "T_out_non_null_%", "fan_signal_any_non_null_%",
        "fan_status_any_non_null_%", "power_non_null_%", "wetbulb_join_non_null_%",
        "flow_any_non_null_%", "missing_for_fmu"
    ]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
