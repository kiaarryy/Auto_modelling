"""Prepare measured steady chiller data for ElectricEIR FMU simulation.

The script reads the 14 steady-state CSV files under the read-only reference
folder, normalizes them into the ``AllData2`` table shape expected by the
current ElectricEIR FMU, and estimates measured nominal values for each chiller.

No file under ``Cali_EIR_BSU_CH1`` is modified.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STEADY_DIR = ROOT / "Cali_EIR_BSU_CH1" / "ChillerData" / "steady"
DEFAULT_TABLE_DIR = ROOT / "outputs" / "electric_eir" / "chiller_tables"
DEFAULT_NOMINALS = ROOT / "outputs" / "electric_eir" / "nominals" / "eir_measured_nominals.xlsx"

TABLE_COLUMNS = [
    "Time",
    "CHWS",
    "CHWR",
    "CDWS",
    "CDWR",
    "CHW",
    "CDW",
    "P/kw",
    "VSD",
    "deltaT_chw",
    "deltaT_cdw",
    "Q_evap_kW",
]

FMU_NOMINAL_COLUMNS = [
    "datChi.QEva_flow_nominal",
    "datChi.COP_nominal",
    "datChi.PLRMax",
    "datChi.PLRMinUnl",
    "datChi.PLRMin",
    "datChi.etaMotor",
    "datChi.mEva_flow_nominal",
    "datChi.mCon_flow_nominal",
    "datChi.TEvaLvg_nominal",
    "datChi.TEvaLvgMin",
    "datChi.TEvaLvgMax",
    "datChi.TConEnt_nominal",
    "datChi.TConEntMin",
    "datChi.TConEntMax",
]

EEIR_FMU_NOMINAL_COLUMNS = [
    "datchi.PLRMax",
    "datchi.PLRMinUnl",
    "datchi.PLRMin",
    "datchi.TEvaLvg_nominal",
    "datchi.TEvaLvgMin",
    "datchi.TEvaLvgMax",
    "datchi.TConLvg_nominal",
    "datchi.TConLvgMin",
    "datchi.TConLvgMax",
]


@dataclass
class ColumnMap:
    chws: Optional[str]
    chwr: Optional[str]
    cdws: Optional[str]
    cdwr: Optional[str]
    chw: Optional[str]
    cdw: Optional[str]
    p_kw: Optional[str]
    q_kw: Optional[str]
    vsd: Optional[str]
    is_steady: Optional[str]
    on_flag: Optional[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare measured steady-state chiller data for ElectricEIR FMU runs."
    )
    parser.add_argument("--steady-dir", type=Path, default=DEFAULT_STEADY_DIR)
    parser.add_argument("--table-dir", type=Path, default=DEFAULT_TABLE_DIR)
    parser.add_argument("--nominals-output", type=Path, default=DEFAULT_NOMINALS)
    parser.add_argument("--min-valid-points", type=int, default=30)
    parser.add_argument(
        "--filter-mode",
        choices=["flags", "physical"],
        default="flags",
        help=(
            "flags: require is_steady/on_flag when present; "
            "physical: treat *_steady.csv as prefiltered and only require physical validity."
        ),
    )
    return parser.parse_args()


def find_chiller_files(steady_dir: Path) -> List[Path]:
    patterns = [
        re.compile(r"^BSU_CH\d+_steady\.csv$", re.I),
        re.compile(r"^CH_\d{2}_steady\.csv$", re.I),
        re.compile(r"^WKGO_BF\d+_steady\.csv$", re.I),
    ]
    files = [
        path
        for path in steady_dir.glob("*_steady.csv")
        if path.is_file()
        and path.stat().st_size > 0
        and any(pattern.match(path.name) for pattern in patterns)
    ]
    return sorted(files, key=lambda path: path.name)


def chiller_name(path: Path) -> str:
    suffix = "_steady.csv"
    return path.name[: -len(suffix)] if path.name.endswith(suffix) else path.stem


def find_col(columns: Sequence[str], patterns: Sequence[str]) -> Optional[str]:
    for pattern in patterns:
        rx = re.compile(pattern, re.I)
        for column in columns:
            if rx.search(column):
                return column
    return None


def build_column_map(columns: Sequence[str]) -> ColumnMap:
    return ColumnMap(
        chws=find_col(columns, [r"CHWS-WTS", r"CHWS_TEMP"]),
        chwr=find_col(columns, [r"CHWR-WTS", r"CHWR_TEMP"]),
        # WKGO files use CWR/CWS names from the cooling-water loop. For the
        # ElectricEIR FMU, CDWS should be the colder condenser entering water,
        # which corresponds to CWR_TEMP in these files.
        cdws=find_col(columns, [r"CDWS-WTS", r"CDWS_TEMP", r"CWR_TEMP"]),
        cdwr=find_col(columns, [r"CDWR-WTS", r"CDWR_TEMP", r"CWS_TEMP"]),
        chw=find_col(columns, [r"CHW-WFM", r"CHW_FLOW"]),
        cdw=find_col(columns, [r"CDW-WFM", r"CW_FLOW"]),
        p_kw="P/kw" if "P/kw" in columns else ("P_KW" if "P_KW" in columns else find_col(columns, [r"(^|[^A-Z])P(/|_|-| )?k?w"])),
        q_kw="Q_evap_kW" if "Q_evap_kW" in columns else find_col(columns, [r"BLDG-LOAD"]),
        vsd=find_col(columns, [r"VSD-STS", r"FLOAD-AMP", r"RUN_STS"]),
        is_steady="is_steady" if "is_steady" in columns else None,
        on_flag="on_flag" if "on_flag" in columns else None,
    )


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def required_missing(mapping: ColumnMap) -> List[str]:
    required = {
        "CHWS": mapping.chws,
        "CHWR": mapping.chwr,
        "CDWS": mapping.cdws,
        "CDWR": mapping.cdwr,
        "CHW": mapping.chw,
        "CDW": mapping.cdw,
        "P/kw": mapping.p_kw,
    }
    return [name for name, column in required.items() if column is None]


def sample_seconds(df: pd.DataFrame, default: float) -> float:
    if "DateTime" not in df.columns:
        return default
    dt = pd.to_datetime(df["DateTime"], errors="coerce")
    diffs = dt.diff().dt.total_seconds()
    diffs = diffs[(diffs > 0) & np.isfinite(diffs)]
    if diffs.empty:
        return default
    value = float(diffs.median())
    return value if value > 0 else default


def normalize_dataframe(df: pd.DataFrame, mapping: ColumnMap) -> pd.DataFrame:
    chws = numeric(df[mapping.chws])
    chwr = numeric(df[mapping.chwr])
    cdws = numeric(df[mapping.cdws])
    cdwr = numeric(df[mapping.cdwr])
    chw = numeric(df[mapping.chw])
    cdw = numeric(df[mapping.cdw])
    p_kw = numeric(df[mapping.p_kw])
    if mapping.vsd:
        vsd = numeric(df[mapping.vsd]).fillna(1.0)
    else:
        vsd = pd.Series(1.0, index=df.index)

    delta_t_chw = numeric(df["deltaT_chw"]) if "deltaT_chw" in df.columns else chwr - chws
    delta_t_cdw = numeric(df["deltaT_cdw"]) if "deltaT_cdw" in df.columns else cdwr - cdws

    q_existing = numeric(df[mapping.q_kw]) if mapping.q_kw else pd.Series(np.nan, index=df.index)
    q_computed = chw * 4.186 * delta_t_chw
    q_kw = q_existing.where(q_existing.notna(), q_computed)

    return pd.DataFrame(
        {
            "CHWS": chws,
            "CHWR": chwr,
            "CDWS": cdws,
            "CDWR": cdwr,
            "CHW": chw,
            "CDW": cdw,
            "P/kw": p_kw,
            "VSD": vsd,
            "deltaT_chw": delta_t_chw,
            "deltaT_cdw": delta_t_cdw,
            "Q_evap_kW": q_kw,
        }
    )


def valid_mask(
    raw: pd.DataFrame,
    normalized: pd.DataFrame,
    mapping: ColumnMap,
    filter_mode: str,
) -> pd.Series:
    mask = pd.Series(True, index=raw.index)
    if filter_mode == "flags" and mapping.is_steady:
        mask &= numeric(raw[mapping.is_steady]).fillna(0).astype(bool)
    if filter_mode == "flags" and mapping.on_flag:
        mask &= numeric(raw[mapping.on_flag]).fillna(0).astype(bool)

    required_numeric = [
        "CHWS",
        "CHWR",
        "CDWS",
        "CDWR",
        "CHW",
        "CDW",
        "P/kw",
        "deltaT_chw",
        "deltaT_cdw",
        "Q_evap_kW",
    ]
    for column in required_numeric:
        mask &= normalized[column].notna() & np.isfinite(normalized[column])

    mask &= normalized["P/kw"] > 0
    mask &= normalized["CHW"] > 0
    mask &= normalized["CDW"] > 0
    mask &= normalized["deltaT_chw"] > 0
    mask &= normalized["Q_evap_kW"] > 0
    return mask


def make_table(valid: pd.DataFrame, dt_seconds: float) -> pd.DataFrame:
    table = valid[TABLE_COLUMNS[1:]].copy()
    table.insert(0, "Time", np.arange(len(table), dtype=float) * dt_seconds)
    return table[TABLE_COLUMNS]


def write_modelica_table(table: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("#1\n")
        handle.write(f"double AllData2({len(table)},12)\n")
        handle.write("#" + "\t".join(TABLE_COLUMNS) + "\n")
        for _, row in table.iterrows():
            handle.write("\t".join(format_float(row[column]) for column in TABLE_COLUMNS))
            handle.write("\n")


def format_float(value: Any) -> str:
    if pd.isna(value):
        return "NaN"
    return f"{float(value):.10g}"


def estimate_nominals(chiller: str, source_file: str, table_path: Path, table: pd.DataFrame, dt_seconds: float) -> Dict[str, Any]:
    nominal_index = table["Q_evap_kW"].idxmax()
    row = table.loc[nominal_index]
    q_nom_kw = float(row["Q_evap_kW"])
    p_nom_kw = float(row["P/kw"])
    positive_plr = table["Q_evap_kW"] / q_nom_kw
    positive_plr = positive_plr[(positive_plr > 0) & np.isfinite(positive_plr)]
    plr_min = max(0.05, float(positive_plr.min())) if not positive_plr.empty else 0.05

    nominal = {
        "Chiller": chiller,
        "Status": "prepared",
        "SourceFile": source_file,
        "TablePath": str(table_path),
        "ValidRows": int(len(table)),
        "SampleSeconds": float(dt_seconds),
        "StopTime": float(table["Time"].iloc[-1]) if len(table) else 0.0,
        "NominalRowInPreparedTable": int(nominal_index) + 1,
        "Q_nominal_kW": q_nom_kw,
        "P_nominal_kW": p_nom_kw,
        "COP_nominal_measured": q_nom_kw / p_nom_kw,
        "mEva_flow_nominal_lps": float(row["CHW"]),
        "mCon_flow_nominal_lps": float(row["CDW"]),
        "TEvaLvg_nominal_C": float(row["CHWS"]),
        "TConEnt_nominal_C": float(row["CDWS"]),
        "TConLvg_nominal_C": float(row["CDWR"]),
        "datChi.QEva_flow_nominal": -q_nom_kw * 1000.0,
        "datChi.COP_nominal": q_nom_kw / p_nom_kw,
        "datChi.PLRMax": 1.0,
        "datChi.PLRMinUnl": plr_min,
        "datChi.PLRMin": plr_min,
        "datChi.etaMotor": 1.0,
        "datChi.mEva_flow_nominal": float(row["CHW"]),
        "datChi.mCon_flow_nominal": float(row["CDW"]),
        "datChi.TEvaLvg_nominal": float(row["CHWS"]) + 273.15,
        "datChi.TEvaLvgMin": float(table["CHWS"].min()) + 273.15,
        "datChi.TEvaLvgMax": float(table["CHWS"].max()) + 273.15,
        "datChi.TConEnt_nominal": float(row["CDWS"]) + 273.15,
        "datChi.TConEntMin": float(table["CDWS"].min()) + 273.15,
        "datChi.TConEntMax": float(table["CDWS"].max()) + 273.15,
        "datchi.PLRMax": 1.0,
        "datchi.PLRMinUnl": plr_min,
        "datchi.PLRMin": plr_min,
        "datchi.TEvaLvg_nominal": float(row["CHWS"]) + 273.15,
        "datchi.TEvaLvgMin": float(table["CHWS"].min()) + 273.15,
        "datchi.TEvaLvgMax": float(table["CHWS"].max()) + 273.15,
        "datchi.TConLvg_nominal": float(row["CDWR"]) + 273.15,
        "datchi.TConLvgMin": float(table["CDWR"].min()) + 273.15,
        "datchi.TConLvgMax": float(table["CDWR"].max()) + 273.15,
    }
    return nominal


def prepare_one(path: Path, table_dir: Path, min_valid_points: int, filter_mode: str) -> Dict[str, Any]:
    raw = pd.read_csv(path)
    name = chiller_name(path)
    mapping = build_column_map(list(raw.columns))
    missing = required_missing(mapping)
    default_dt = 1800.0 if name.startswith("BSU_") else 300.0
    dt_seconds = sample_seconds(raw, default_dt)

    qa: Dict[str, Any] = {
        "Chiller": name,
        "SourceFile": str(path),
        "TotalRows": int(len(raw)),
        "SampleSeconds": dt_seconds,
        "FilterMode": filter_mode,
        "CHWS": mapping.chws,
        "CHWR": mapping.chwr,
        "CDWS": mapping.cdws,
        "CDWR": mapping.cdwr,
        "CHW": mapping.chw,
        "CDW": mapping.cdw,
        "P/kw": mapping.p_kw,
        "Q_or_Load": mapping.q_kw,
        "VSD": mapping.vsd,
        "is_steady": mapping.is_steady,
        "on_flag": mapping.on_flag,
        "MissingColumns": ", ".join(missing),
    }

    if missing:
        qa.update({"Status": "skipped", "ValidRows": 0, "SkipReason": "missing required columns"})
        return qa

    normalized = normalize_dataframe(raw, mapping)
    mask = valid_mask(raw, normalized, mapping, filter_mode)
    valid = normalized.loc[mask].copy().reset_index(drop=True)
    qa["ValidRows"] = int(len(valid))

    if len(valid) < min_valid_points:
        qa.update(
            {
                "Status": "skipped",
                "SkipReason": f"valid rows < {min_valid_points}",
            }
        )
        return qa

    table = make_table(valid, dt_seconds)
    table_path = table_dir / f"{name}_ChillerData.txt"
    write_modelica_table(table, table_path)
    nominal = estimate_nominals(name, path.name, table_path, table, dt_seconds)

    qa.update(
        {
            "Status": "prepared",
            "SkipReason": "",
            "TablePath": str(table_path),
            "StopTime": nominal["StopTime"],
            "Q_nominal_kW": nominal["Q_nominal_kW"],
            "COP_nominal_measured": nominal["COP_nominal_measured"],
        }
    )
    nominal.update(qa)
    return nominal


def split_outputs(rows: Sequence[Dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    all_df = pd.DataFrame(rows)
    qa_cols = [
        "Chiller",
        "Status",
        "SkipReason",
        "SourceFile",
        "TotalRows",
        "ValidRows",
        "SampleSeconds",
        "FilterMode",
        "StopTime",
        "MissingColumns",
        "CHWS",
        "CHWR",
        "CDWS",
        "CDWR",
        "CHW",
        "CDW",
        "P/kw",
        "Q_or_Load",
        "VSD",
        "is_steady",
        "on_flag",
    ]
    qa_df = all_df[[col for col in qa_cols if col in all_df.columns]].copy()

    nominal_cols = [
        "Chiller",
        "Status",
        "SourceFile",
        "TablePath",
        "ValidRows",
        "SampleSeconds",
        "StopTime",
        "NominalRowInPreparedTable",
        "Q_nominal_kW",
        "P_nominal_kW",
        "COP_nominal_measured",
        "mEva_flow_nominal_lps",
        "mCon_flow_nominal_lps",
        "TEvaLvg_nominal_C",
        "TConEnt_nominal_C",
        "TConLvg_nominal_C",
        *FMU_NOMINAL_COLUMNS,
        *EEIR_FMU_NOMINAL_COLUMNS,
    ]
    nominal_df = all_df[all_df["Status"].eq("prepared")].copy()
    nominal_df = nominal_df[[col for col in nominal_cols if col in nominal_df.columns]]
    return nominal_df, qa_df


def write_workbook(rows: Sequence[Dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nominal_df, qa_df = split_outputs(rows)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        nominal_df.to_excel(writer, sheet_name="Nominals", index=False)
        qa_df.to_excel(writer, sheet_name="QA", index=False)


def main() -> int:
    args = parse_args()
    if not args.steady_dir.exists():
        raise FileNotFoundError(args.steady_dir)

    files = find_chiller_files(args.steady_dir)
    if not files:
        raise FileNotFoundError(f"No chiller steady CSV files found in {args.steady_dir}")

    rows: List[Dict[str, Any]] = []
    for path in files:
        row = prepare_one(path, args.table_dir, args.min_valid_points, args.filter_mode)
        rows.append(row)
        print(
            f"{row['Chiller']}: {row['Status']} "
            f"valid={row.get('ValidRows', 0)} "
            f"{row.get('SkipReason', '')}"
        )

    write_workbook(rows, args.nominals_output)
    prepared = sum(1 for row in rows if row.get("Status") == "prepared")
    skipped = len(rows) - prepared
    print(f"Prepared: {prepared}; skipped: {skipped}")
    print(f"Nominals workbook: {args.nominals_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
