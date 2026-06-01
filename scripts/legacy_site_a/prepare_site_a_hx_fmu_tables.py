"""Prepare Site A heat exchanger FMU input tables from building-based BMS CSV files."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SITE_A = ROOT / "CT_Model" / "DATA" / "Site_A"
OUT_DIR = ROOT / "outputs" / "heat_exchanger"
TABLE_DIR = OUT_DIR / "fmu_tables"
QA_DIR = OUT_DIR / "qa"
NOMINAL_DIR = OUT_DIR / "nominals"

CP_WATER = 4186.0
KG_PER_L = 0.997
MIN_FLOW_KG_S = 1.0
MIN_DT_C = 0.05
MIN_Q_W = 5000.0
MAX_BALANCE_REL = 0.50

NUMERIC_FMU_COLUMNS = [
    "time_s",
    "T1In_m_C",
    "T1Out_m_C",
    "T2In_m_C",
    "T2Out_m_C",
    "m1_flow_kg_s",
    "m2_flow_kg_s",
    "Q_m_W",
    "Q1_m_W",
    "Q2_m_W",
    "eps_m",
    "dT_lm_m_C",
    "P_aux_W",
    "active_proxy",
]


@dataclass(frozen=True)
class HXMap:
    hx: str
    building: str
    hx_file: str
    hxcwp_file: str


HX_MAPS = [
    HXMap("HX_01", "building1", "HX_01.csv", "HXCWP_01.csv"),
    HXMap("HX_02", "building2", "HX_02.csv", "HXCWP_02.csv"),
    HXMap("HX_03", "building3", "HX_03.csv", "HXCWP_03.csv"),
]


@dataclass
class HXTableResult:
    table: pd.DataFrame
    qa: dict[str, object]
    nominals: dict[str, object]
    scored_mappings: pd.DataFrame


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "DateTime" in df.columns:
        df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
        df = df.dropna(subset=["DateTime"]).sort_values("DateTime")
    return df


def find_col(cols: list[str], include: list[str], exclude: list[str] | None = None) -> str | None:
    exclude = exclude or []
    for col in cols:
        low = col.lower()
        if all(token.lower() in low for token in include) and not any(token.lower() in low for token in exclude):
            return col
    return None


def num(df: pd.DataFrame, col: str | None) -> pd.Series:
    if not col or col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def lps_to_kg_s(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").abs() * KG_PER_L


def _required_raw_columns(df: pd.DataFrame) -> dict[str, str | None]:
    cols = list(df.columns)
    return {
        "cdw_flow": find_col(cols, ["cdw", "wfm"]),
        "chw_flow": find_col(cols, ["chw", "wfm"]),
        "cdw_rwt": find_col(cols, ["cdw", "rwt"]),
        "cdw_swt": find_col(cols, ["cdw", "swt"]),
        "chw_rwt": find_col(cols, ["chw", "rwt"]),
        "chw_swt": find_col(cols, ["chw", "swt"]),
        "p_aux": find_col(cols, ["P/kw"]) or ("P/kw" if "P/kw" in df.columns else None),
    }


def _heat_balance(q1: pd.Series, q2: pd.Series) -> pd.Series:
    denom = pd.concat([q1.abs(), q2.abs()], axis=1).max(axis=1).replace(0.0, np.nan)
    return (q1 - q2).abs() / denom


def select_temperature_mapping(df: pd.DataFrame, hx: str) -> tuple[dict[str, str], pd.DataFrame]:
    """Choose CHW/CDW inlet-outlet direction by positive heat and energy balance.

    Side 1 is CHW, interpreted as the stream being cooled by the HX.
    Side 2 is CDW, interpreted as the stream being warmed by the HX.
    """

    raw = _required_raw_columns(df)
    required = ["cdw_flow", "chw_flow", "cdw_rwt", "cdw_swt", "chw_rwt", "chw_swt"]
    missing = [key for key in required if raw[key] is None]
    if missing:
        return {}, pd.DataFrame(
            [{"hx": hx, "status": "blocked_missing_temperature_or_flow_fields", "missing": "; ".join(missing)}]
        )

    m1 = lps_to_kg_s(num(df, raw["chw_flow"]))
    m2 = lps_to_kg_s(num(df, raw["cdw_flow"]))
    chw_pairs = [(raw["chw_rwt"], raw["chw_swt"]), (raw["chw_swt"], raw["chw_rwt"])]
    cdw_pairs = [(raw["cdw_rwt"], raw["cdw_swt"]), (raw["cdw_swt"], raw["cdw_rwt"])]

    rows: list[dict[str, object]] = []
    for t1_in, t1_out in chw_pairs:
        for t2_in, t2_out in cdw_pairs:
            t1i = num(df, t1_in)
            t1o = num(df, t1_out)
            t2i = num(df, t2_in)
            t2o = num(df, t2_out)
            q1 = m1 * CP_WATER * (t1i - t1o)
            q2 = m2 * CP_WATER * (t2o - t2i)
            base = (
                m1.gt(MIN_FLOW_KG_S)
                & m2.gt(MIN_FLOW_KG_S)
                & t1i.notna()
                & t1o.notna()
                & t2i.notna()
                & t2o.notna()
            )
            usable = base & q1.gt(MIN_Q_W) & q2.gt(MIN_Q_W)
            bal = _heat_balance(q1, q2)
            rows.append(
                {
                    "hx": hx,
                    "status": "ok",
                    "T1In_C": t1_in,
                    "T1Out_C": t1_out,
                    "T2In_C": t2_in,
                    "T2Out_C": t2_out,
                    "usable_rows": int(usable.sum()),
                    "base_rows": int(base.sum()),
                    "median_balance_rel": float(bal.loc[usable].median()) if usable.any() else np.nan,
                    "median_Q1_W": float(q1.loc[usable].median()) if usable.any() else np.nan,
                    "median_Q2_W": float(q2.loc[usable].median()) if usable.any() else np.nan,
                }
            )

    scored = pd.DataFrame(rows).sort_values(
        by=["usable_rows", "median_balance_rel"],
        ascending=[False, True],
        na_position="last",
    )
    best = scored.iloc[0].to_dict()
    mapping = {
        "T1In_C": str(best["T1In_C"]),
        "T1Out_C": str(best["T1Out_C"]),
        "T2In_C": str(best["T2In_C"]),
        "T2Out_C": str(best["T2Out_C"]),
        "m1_flow_lps": str(raw["chw_flow"]),
        "m2_flow_lps": str(raw["cdw_flow"]),
        "P_aux_kW": str(raw["p_aux"] or ""),
    }
    return mapping, scored


def lmtd(delta_a: pd.Series, delta_b: pd.Series) -> pd.Series:
    da = pd.to_numeric(delta_a, errors="coerce")
    db = pd.to_numeric(delta_b, errors="coerce")
    close = (da - db).abs() < 1e-9
    valid = (da > 0.0) & (db > 0.0)
    ratio = (da / db).where(valid, np.nan)
    out = (da - db) / np.log(ratio)
    out = out.where(~close, (da + db) / 2.0)
    out = out.where(valid & np.isfinite(out), np.nan)
    return out


def valid_mask(df: pd.DataFrame, max_balance_rel: float = MAX_BALANCE_REL) -> pd.Series:
    needed = ["m1_flow_kg_s", "m2_flow_kg_s", "T1In_m_C", "T1Out_m_C", "T2In_m_C", "T2Out_m_C", "Q1_m_W", "Q2_m_W"]
    ok = df[needed].replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    ok &= df["m1_flow_kg_s"].gt(MIN_FLOW_KG_S)
    ok &= df["m2_flow_kg_s"].gt(MIN_FLOW_KG_S)
    ok &= (df["T1In_m_C"] - df["T1Out_m_C"]).gt(MIN_DT_C)
    ok &= (df["T2Out_m_C"] - df["T2In_m_C"]).gt(MIN_DT_C)
    ok &= df["Q1_m_W"].gt(MIN_Q_W)
    ok &= df["Q2_m_W"].gt(MIN_Q_W)
    ok &= _heat_balance(df["Q1_m_W"], df["Q2_m_W"]).le(max_balance_rel)
    return ok


def compute_metrics(measured: pd.Series, simulated: pd.Series) -> dict[str, float]:
    obs = pd.to_numeric(measured, errors="coerce")
    sim = pd.to_numeric(simulated, errors="coerce")
    mask = obs.notna() & sim.notna()
    obs = obs.loc[mask].astype(float)
    sim = sim.loc[mask].astype(float)
    if obs.empty:
        return {"N": 0, "RMSE": np.nan, "MAE": np.nan, "MBE": np.nan, "NMBE": np.nan, "CVRMSE": np.nan, "MAPE": np.nan, "R2": np.nan}
    err = sim - obs
    rmse = float(math.sqrt(float((err**2).mean())))
    mae = float(err.abs().mean())
    mbe = float(err.mean())
    mean_obs = float(obs.mean())
    nmb = mbe / mean_obs * 100.0 if abs(mean_obs) > 1e-12 else np.nan
    cvrmse = rmse / mean_obs * 100.0 if abs(mean_obs) > 1e-12 else np.nan
    nonzero = obs.abs() > 1e-12
    mape = float((err.loc[nonzero].abs() / obs.loc[nonzero].abs()).mean() * 100.0) if nonzero.any() else np.nan
    ss_res = float((err**2).sum())
    ss_tot = float(((obs - mean_obs) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else np.nan
    return {"N": int(mask.sum()), "RMSE": rmse, "MAE": mae, "MBE": mbe, "NMBE": nmb, "CVRMSE": cvrmse, "MAPE": mape, "R2": r2}


def estimate_nominals(table: pd.DataFrame, hx: str) -> dict[str, object]:
    work = table.loc[table.get("valid_for_fmu", pd.Series(True, index=table.index)).astype(bool)].copy()
    if work.empty:
        return {"hx": hx, "status": "blocked_no_valid_rows"}

    c1 = work["m1_flow_kg_s"] * CP_WATER
    c2 = work["m2_flow_kg_s"] * CP_WATER
    c_min = pd.concat([c1, c2], axis=1).min(axis=1)
    d_t_in = (work["T1In_m_C"] - work["T2In_m_C"]).abs().replace(0.0, np.nan)
    eps = (work["Q_m_W"].abs() / (c_min * d_t_in)).replace([np.inf, -np.inf], np.nan).clip(0.05, 0.98)
    dt_a = (work["T1In_m_C"] - work["T2Out_m_C"]).abs()
    dt_b = (work["T1Out_m_C"] - work["T2In_m_C"]).abs()
    ua = (work["Q_m_W"].abs() / lmtd(dt_a, dt_b)).replace([np.inf, -np.inf], np.nan)

    return {
        "hx": hx,
        "status": "ready",
        "rows_valid": int(len(work)),
        "m1_flow_nominal": float(work["m1_flow_kg_s"].quantile(0.95)),
        "m2_flow_nominal": float(work["m2_flow_kg_s"].quantile(0.95)),
        "Q_flow_nominal": float(work["Q_m_W"].abs().quantile(0.95)),
        "eps_nominal": float(eps.median()) if eps.notna().any() else 0.8,
        "UA_nominal_initial": float(ua.median()) if ua.notna().any() else np.nan,
        "T_a1_nominal": float(work["T1In_m_C"].median() + 273.15),
        "T_b1_nominal": float(work["T1Out_m_C"].median() + 273.15),
        "T_a2_nominal": float(work["T2In_m_C"].median() + 273.15),
        "T_b2_nominal": float(work["T2Out_m_C"].median() + 273.15),
        "dp1_nominal": 0.0,
        "dp2_nominal": 0.0,
    }


def _load_hxcwp(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["DateTime", "hxcwp_freq_Hz", "hxcwp_P_W"])
    pump = read_csv(path)
    cols = list(pump.columns)
    freq_col = find_col(cols, ["VSD", "STS"]) or find_col(cols, ["VSD", "CTRL"])
    p_col = find_col(cols, ["P/kw"]) or ("P/kw" if "P/kw" in cols else None)
    return pd.DataFrame(
        {
            "DateTime": pump["DateTime"],
            "hxcwp_freq_Hz": num(pump, freq_col).clip(lower=0.0),
            "hxcwp_P_W": num(pump, p_col).clip(lower=0.0) * 1000.0,
        }
    )


def build_hx_table(mapping: HXMap) -> HXTableResult:
    hx_path = SITE_A / mapping.building / mapping.hx_file
    raw = read_csv(hx_path)
    colmap, scored = select_temperature_mapping(raw, mapping.hx)

    if not colmap:
        qa = {
            "hx": mapping.hx,
            "status": "blocked_missing_temperature_fields",
            "rows_raw": len(raw),
            "source": str(hx_path),
        }
        return HXTableResult(pd.DataFrame(columns=NUMERIC_FMU_COLUMNS), qa, {"hx": mapping.hx, "status": qa["status"]}, scored)

    out = pd.DataFrame({"DateTime": raw["DateTime"]})
    out["T1In_m_C"] = num(raw, colmap["T1In_C"])
    out["T1Out_m_C"] = num(raw, colmap["T1Out_C"])
    out["T2In_m_C"] = num(raw, colmap["T2In_C"])
    out["T2Out_m_C"] = num(raw, colmap["T2Out_C"])
    out["m1_flow_kg_s"] = lps_to_kg_s(num(raw, colmap["m1_flow_lps"]))
    out["m2_flow_kg_s"] = lps_to_kg_s(num(raw, colmap["m2_flow_lps"]))
    out["P_aux_W"] = num(raw, colmap.get("P_aux_kW", "")).clip(lower=0.0) * 1000.0

    pump = _load_hxcwp(SITE_A / mapping.building / mapping.hxcwp_file)
    out = out.merge(pump, on="DateTime", how="left")
    out["P_aux_W"] = out["P_aux_W"].fillna(out["hxcwp_P_W"])
    out["Q1_m_W"] = out["m1_flow_kg_s"] * CP_WATER * (out["T1In_m_C"] - out["T1Out_m_C"])
    out["Q2_m_W"] = out["m2_flow_kg_s"] * CP_WATER * (out["T2Out_m_C"] - out["T2In_m_C"])
    out["Q_m_W"] = (out["Q1_m_W"] + out["Q2_m_W"]) / 2.0
    c_min = pd.concat([out["m1_flow_kg_s"] * CP_WATER, out["m2_flow_kg_s"] * CP_WATER], axis=1).min(axis=1)
    out["eps_m"] = (out["Q_m_W"].abs() / (c_min * (out["T1In_m_C"] - out["T2In_m_C"]).abs().replace(0.0, np.nan))).clip(0.0, 1.5)
    out["dT_lm_m_C"] = lmtd((out["T1In_m_C"] - out["T2Out_m_C"]).abs(), (out["T1Out_m_C"] - out["T2In_m_C"]).abs())
    out["active_proxy"] = (
        out["P_aux_W"].fillna(0.0).gt(1000.0)
        | out["hxcwp_freq_Hz"].fillna(0.0).gt(1.0)
        | out["Q_m_W"].abs().gt(MIN_Q_W)
    ).astype(float)
    out["valid_for_fmu"] = valid_mask(out) & out["active_proxy"].gt(0.0)
    valid = out["valid_for_fmu"]
    work = out.loc[valid].copy()
    if not work.empty:
        t0 = work["DateTime"].iloc[0]
        work["time_s"] = (work["DateTime"] - t0).dt.total_seconds()
    else:
        work["time_s"] = pd.Series(dtype=float)

    table_cols = ["DateTime", *NUMERIC_FMU_COLUMNS, "valid_for_fmu"]
    table = work[table_cols].copy()
    nominals = estimate_nominals(table, mapping.hx)
    qa = {
        "hx": mapping.hx,
        "status": "ready" if not table.empty else "blocked_no_valid_rows",
        "source": str(hx_path),
        "rows_raw": int(len(raw)),
        "rows_valid": int(valid.sum()),
        "valid_%": float(valid.mean() * 100.0),
        "start_valid": str(table["DateTime"].min()) if not table.empty else "",
        "end_valid": str(table["DateTime"].max()) if not table.empty else "",
        "T1In_col": colmap["T1In_C"],
        "T1Out_col": colmap["T1Out_C"],
        "T2In_col": colmap["T2In_C"],
        "T2Out_col": colmap["T2Out_C"],
        "m1_flow_col": colmap["m1_flow_lps"],
        "m2_flow_col": colmap["m2_flow_lps"],
        "median_balance_rel": float(_heat_balance(out.loc[valid, "Q1_m_W"], out.loc[valid, "Q2_m_W"]).median()) if valid.any() else np.nan,
        "median_Q_m_W": float(table["Q_m_W"].median()) if not table.empty else np.nan,
        "p95_m1_flow_kg_s": float(table["m1_flow_kg_s"].quantile(0.95)) if not table.empty else np.nan,
        "p95_m2_flow_kg_s": float(table["m2_flow_kg_s"].quantile(0.95)) if not table.empty else np.nan,
    }
    return HXTableResult(table, qa, nominals, scored)


def write_dymola_table(path: Path, table: pd.DataFrame, table_name: str = "HX_data") -> None:
    numeric = table[NUMERIC_FMU_COLUMNS].copy().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("#1\n")
        f.write(f"double {table_name}({len(numeric)},{len(numeric.columns)})\n")
        numeric.to_csv(f, header=False, index=False, line_terminator="\n", float_format="%.10g")


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._\n"
    headers = list(df.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in headers) + " |")
    return "\n".join(lines) + "\n"


def write_report(qa: pd.DataFrame, nominals: pd.DataFrame, path: Path) -> None:
    cols = ["hx", "status", "rows_raw", "rows_valid", "valid_%", "median_balance_rel", "median_Q_m_W"]
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Site A Heat Exchanger Data QA\n\n")
        f.write("## QA Summary\n\n")
        f.write(markdown_table(qa[[c for c in cols if c in qa.columns]]))
        f.write("\n## Nominal Parameters\n\n")
        keep = ["hx", "status", "m1_flow_nominal", "m2_flow_nominal", "Q_flow_nominal", "eps_nominal", "UA_nominal_initial"]
        f.write(markdown_table(nominals[[c for c in keep if c in nominals.columns]]))
        f.write("\n## Notes\n\n")
        f.write("- Side 1 is CHW; side 2 is CDW. Inlet/outlet direction is selected by positive heat transfer and energy balance.\n")
        f.write("- HX_03 is expected to be blocked if the local CSV still lacks both-side temperature fields.\n")


def main() -> int:
    for directory in [TABLE_DIR, QA_DIR, NOMINAL_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

    qa_rows: list[Mapping[str, object]] = []
    nominal_rows: list[Mapping[str, object]] = []
    scored_frames: list[pd.DataFrame] = []
    for hx_map in HX_MAPS:
        result = build_hx_table(hx_map)
        qa_rows.append(result.qa)
        nominal_rows.append(result.nominals)
        if not result.scored_mappings.empty:
            scored_frames.append(result.scored_mappings)
        if not result.table.empty:
            csv_path = TABLE_DIR / f"{hx_map.hx}_fmu_table.csv"
            txt_path = TABLE_DIR / f"{hx_map.hx}_fmu_table.txt"
            time_path = TABLE_DIR / f"{hx_map.hx}_time_mapping.csv"
            result.table.to_csv(csv_path, index=False, encoding="utf-8-sig")
            result.table[["DateTime", "time_s"]].to_csv(time_path, index=False, encoding="utf-8-sig")
            write_dymola_table(txt_path, result.table)

    qa_df = pd.DataFrame(qa_rows)
    nom_df = pd.DataFrame(nominal_rows)
    qa_df.to_csv(QA_DIR / "site_a_hx_input_qa.csv", index=False, encoding="utf-8-sig")
    nom_df.to_csv(NOMINAL_DIR / "site_a_hx_nominals.csv", index=False, encoding="utf-8-sig")
    if scored_frames:
        pd.concat(scored_frames, ignore_index=True).to_csv(QA_DIR / "site_a_hx_mapping_candidates.csv", index=False, encoding="utf-8-sig")
    write_report(qa_df, nom_df, QA_DIR / "site_a_hx_input_qa.md")

    print(f"Output: {OUT_DIR}")
    print(qa_df[["hx", "status", "rows_raw", "rows_valid", "valid_%"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
