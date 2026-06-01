"""Prepare Site A cooling tower FMU input tables from structured BMS CSV files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SITE_A = ROOT / "CT_Model" / "DATA" / "Site_A"
OUT_DIR = ROOT / "outputs" / "cooling_tower" / "site_a_tables"
WET_BULB = SITE_A / "WET_BALL" / "OUTDOOR" / "Local_IO.RF1-OUTDOOR_202405_202504_with_Twb.csv"

CP_WATER = 4186.0
KG_PER_L = 0.997
F_NOM_HZ = 50.0
FAN_ON_HZ = 1.0


@dataclass(frozen=True)
class TowerMap:
    tower: str
    ct_file: str
    chiller_file: str
    hx_file: Optional[str]
    n_fans: int = 2


TOWER_MAPS = [
    TowerMap("CT_01", "CT_01.csv", "CH_01.csv", "HX_01.csv"),
    TowerMap("CT_02", "CT_02.csv", "CH_02.csv", None),
    TowerMap("CT_03", "CT_03.csv", "CH_03.csv", None),
    TowerMap("CT_04", "CT_04.csv", "CH_04.csv", "HX_02.csv"),
    TowerMap("CT_05", "CT_05.csv", "CH_05.csv", None),
    TowerMap("CT_06", "CT_06.csv", "CH_06.csv", "HX_03.csv"),
    TowerMap("CT_07", "CT_07.csv", "CH_07.csv", None),
]


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
    return df.dropna(subset=["DateTime"]).sort_values("DateTime")


def find_col(cols: List[str], include: List[str], exclude: Optional[List[str]] = None) -> Optional[str]:
    exclude = exclude or []
    for col in cols:
        low = col.lower()
        if all(tok.lower() in low for tok in include) and not any(tok.lower() in low for tok in exclude):
            return col
    return None


def find_cols(cols: List[str], include: List[str], exclude: Optional[List[str]] = None) -> List[str]:
    exclude = exclude or []
    out = []
    for col in cols:
        low = col.lower()
        if all(tok.lower() in low for tok in include) and not any(tok.lower() in low for tok in exclude):
            out.append(col)
    return out


def num(df: pd.DataFrame, col: Optional[str]) -> pd.Series:
    if not col or col not in df:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def positive_lps_to_kg_s(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").clip(lower=0.0) * KG_PER_L


def load_wetbulb() -> pd.DataFrame:
    wet = read_csv(WET_BULB)
    return wet[["DateTime", "Twb (°C)"]].rename(columns={"Twb (°C)": "Twb_C"})


def flow_from_file(path: Path, pattern: str) -> pd.DataFrame:
    df = read_csv(path)
    col = find_col(list(df.columns), [pattern, "WFM"])
    if col is None:
        # More generic fallback for HX names where CDWS-WFM/CDW-WFM differs.
        col = find_col(list(df.columns), ["CDW", "WFM"])
    flow = positive_lps_to_kg_s(num(df, col))
    return pd.DataFrame({"DateTime": df["DateTime"], path.stem + "_flow_kg_s": flow, path.stem + "_flow_col": col or ""})


def build_tower_table(mapping: TowerMap, wet: pd.DataFrame) -> tuple[pd.DataFrame, Dict[str, object]]:
    ct = read_csv(SITE_A / "cooling_tower" / mapping.ct_file)
    cols = list(ct.columns)
    t_in_col = find_col(cols, ["CDWR-WTS"])
    t_out_col = find_col(cols, ["CDWS-WTS"])
    p_col = find_col(cols, ["P/kw"]) or "P/kw"
    bypass_cols = find_cols(cols, ["BPV"])
    fan_ctrl_cols = find_cols(cols, ["VSD-CTRL"])
    fan_sts_cols = find_cols(cols, ["VSD-STS"])
    fan_cols = fan_ctrl_cols or fan_sts_cols

    df = pd.DataFrame({"DateTime": ct["DateTime"]})
    df["Tin_C"] = num(ct, t_in_col)
    df["Tout_m_C"] = num(ct, t_out_col)
    df["PFan_meas_W"] = num(ct, p_col) * 1000.0
    if bypass_cols:
        df["bypass_pct"] = ct[bypass_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    else:
        df["bypass_pct"] = np.nan

    if fan_cols:
        fan_frame = ct[fan_cols].apply(pd.to_numeric, errors="coerce").clip(lower=0.0)
        df["fanHz"] = fan_frame.replace(0.0, np.nan).mean(axis=1).fillna(fan_frame.max(axis=1))
        if len(fan_cols) == 1 and mapping.n_fans == 2:
            df["fans_on_count"] = np.where(df["fanHz"] > FAN_ON_HZ, 2, 0)
        else:
            df["fans_on_count"] = (fan_frame > FAN_ON_HZ).sum(axis=1).clip(upper=mapping.n_fans)
    else:
        df["fanHz"] = np.nan
        df["fans_on_count"] = np.nan
    df["y_used"] = (df["fanHz"] / F_NOM_HZ).clip(lower=0.0, upper=1.0)

    df = df.merge(wet, on="DateTime", how="left")

    ch_flow = flow_from_file(SITE_A / "chiller" / mapping.chiller_file, "CDW")
    df = df.merge(ch_flow.drop(columns=[mapping.chiller_file.replace(".csv", "") + "_flow_col"], errors="ignore"), on="DateTime", how="left")
    flow_cols = [c for c in df.columns if c.endswith("_flow_kg_s")]

    hx_col = ""
    if mapping.hx_file:
        hx_path = SITE_A / "heat_exchanger" / mapping.hx_file
        hx_flow = flow_from_file(hx_path, "CDW")
        hx_col = str(hx_flow.iloc[0].get(hx_path.stem + "_flow_col", "")) if not hx_flow.empty else ""
        df = df.merge(hx_flow.drop(columns=[hx_path.stem + "_flow_col"], errors="ignore"), on="DateTime", how="left")
        flow_cols = [c for c in df.columns if c.endswith("_flow_kg_s")]

    df["m_flow_total_kg_s"] = df[flow_cols].sum(axis=1, min_count=1)
    df["m_flow_cell_kg_s"] = df["m_flow_total_kg_s"] / float(mapping.n_fans)
    df["TRan_C"] = df["Tin_C"] - df["Tout_m_C"]
    df["TAppAct_C"] = df["Tout_m_C"] - df["Twb_C"]
    df["Q_flow_W"] = df["m_flow_total_kg_s"] * CP_WATER * df["TRan_C"]

    valid = (
        df[["Tin_C", "Tout_m_C", "Twb_C", "m_flow_cell_kg_s", "y_used", "PFan_meas_W", "Q_flow_W"]]
        .replace([np.inf, -np.inf], np.nan)
        .notna()
        .all(axis=1)
    )
    valid &= df["m_flow_total_kg_s"] > 1.0
    valid &= df["y_used"] > 0.02
    valid &= df["fans_on_count"] > 0
    valid &= df["TRan_C"] > 0.05
    valid &= df["TAppAct_C"] >= 0.0
    valid &= df["PFan_meas_W"] > 0.0
    df["valid_for_fmu"] = valid

    work = df.loc[valid].copy()
    if not work.empty:
        t0 = work["DateTime"].iloc[0]
        work["time_s"] = (work["DateTime"] - t0).dt.total_seconds()
    else:
        work["time_s"] = []

    table = pd.DataFrame({
        "time_s": work["time_s"],
        "Tin_C": work["Tin_C"],
        "Tout_meas_C": work["Tout_m_C"],
        "Twb_C": work["Twb_C"],
        "TRan_C": work["TRan_C"],
        "TAppAct_C": work["TAppAct_C"],
        "mdot_cell_kgps": work["m_flow_cell_kg_s"],
        "y_used": work["y_used"],
        "fanHz": work["fanHz"],
        "fans_on_count": work["fans_on_count"],
        "Q_flow_W": work["Q_flow_W"],
        "PFan_meas_W": work["PFan_meas_W"],
    })

    qa = {
        "tower": mapping.tower,
        "rows_raw": len(df),
        "rows_valid": int(valid.sum()),
        "valid_%": float(valid.mean() * 100.0),
        "start_valid": str(work["DateTime"].min()) if not work.empty else "",
        "end_valid": str(work["DateTime"].max()) if not work.empty else "",
        "ct_tin_col": t_in_col or "",
        "ct_tout_col": t_out_col or "",
        "fan_cols": "; ".join(fan_cols),
        "flow_sources": "; ".join(flow_cols),
        "hx_flow_col": hx_col,
        "median_m_flow_total_kg_s": float(work["m_flow_total_kg_s"].median()) if not work.empty else np.nan,
        "median_m_flow_cell_kg_s": float(work["m_flow_cell_kg_s"].median()) if not work.empty else np.nan,
        "median_y": float(work["y_used"].median()) if not work.empty else np.nan,
        "median_PFan_W": float(work["PFan_meas_W"].median()) if not work.empty else np.nan,
        "median_TApp_C": float(work["TAppAct_C"].median()) if not work.empty else np.nan,
        "median_TRan_C": float(work["TRan_C"].median()) if not work.empty else np.nan,
    }
    return table, qa


def write_dymola_table(path: Path, table: pd.DataFrame, table_name: str = "CT_data") -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("#1\n")
        f.write(f"double {table_name}({len(table)},{len(table.columns)})\n")
        table.to_csv(f, header=False, index=False, line_terminator="\n", float_format="%.10g")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wet = load_wetbulb()
    qa_rows = []
    for mapping in TOWER_MAPS:
        table, qa = build_tower_table(mapping, wet)
        csv_path = OUT_DIR / f"{mapping.tower}_fmu_table.csv"
        txt_path = OUT_DIR / f"{mapping.tower}_fmu_table.txt"
        table.to_csv(csv_path, index=False)
        write_dymola_table(txt_path, table)
        qa_rows.append(qa)
    qa_df = pd.DataFrame(qa_rows)
    qa_df.to_csv(OUT_DIR / "site_a_ct_table_qa.csv", index=False, encoding="utf-8-sig")
    print(f"Output: {OUT_DIR}")
    print(qa_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
