"""Recalculate manuscript Tables 4, 5, and 6 from best metrics.

Input:
    outputs/comparison/two_type/best_metrics_two_type_current.xlsx

Output:
    outputs/comparison/two_type/manuscript_tables_4_5_6_recalculated.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "outputs" / "comparison" / "two_type" / "best_metrics_two_type_current.xlsx"
DEFAULT_OUTPUT = ROOT / "outputs" / "comparison" / "two_type" / "manuscript_tables_4_5_6_recalculated.xlsx"

SITE_ORDER = ["A", "B", "C"]
MODEL_ORDER = ["EEIR", "EIR"]
GL14_CVRMSE_LIMIT = 30.0
GL14_NMBE_LIMIT = 5.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recalculate manuscript Tables 4-6.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def site_letter(site: str) -> str:
    text = str(site)
    if text.lower().startswith("site "):
        return text.split()[-1]
    return text


def load_metrics(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_excel(path, sheet_name="All Projects")
    df["Site letter"] = df["Site"].map(site_letter)
    df["GL14"] = (df["CVRMSE"] <= GL14_CVRMSE_LIMIT) & (df["NMBE"].abs() <= GL14_NMBE_LIMIT)
    return df


def table_site_model(
    df: pd.DataFrame,
    variables: Dict[str, str],
    columns: List[str],
) -> pd.DataFrame:
    rows = []
    for site in SITE_ORDER:
        for model in MODEL_ORDER:
            part = df[(df["Site letter"].eq(site)) & (df["Model type"].eq(model))]
            row = {"Site": site, "Model": model}
            for prefix, key_variable in variables.items():
                sub = part[part["Key variable"].eq(key_variable)]
                row[f"{prefix} CVRMSE (%)"] = float(sub["CVRMSE"].median()) if not sub.empty else np.nan
                row[f"{prefix} NMBE (%)"] = float(sub["NMBE"].median()) if not sub.empty else np.nan
                row[f"{prefix} R2"] = float(sub["R2"].median()) if not sub.empty else np.nan
                row[f"{prefix} GL14 (%)"] = float(sub["GL14"].mean() * 100.0) if not sub.empty else np.nan
            rows.append(row)
    out = pd.DataFrame(rows)
    return out[columns]


def build_table4(df: pd.DataFrame) -> pd.DataFrame:
    return table_site_model(
        df,
        {"Pchiller": "Power_kW", "COP": "COP"},
        [
            "Site",
            "Model",
            "Pchiller CVRMSE (%)",
            "Pchiller NMBE (%)",
            "Pchiller R2",
            "Pchiller GL14 (%)",
            "COP CVRMSE (%)",
            "COP NMBE (%)",
            "COP R2",
            "COP GL14 (%)",
        ],
    )


def build_table5(df: pd.DataFrame) -> pd.DataFrame:
    return table_site_model(
        df,
        {"Qevap": "Q_evap_kW"},
        [
            "Site",
            "Model",
            "Qevap CVRMSE (%)",
            "Qevap NMBE (%)",
            "Qevap R2",
            "Qevap GL14 (%)",
        ],
    )


def primary_pivot(df: pd.DataFrame) -> pd.DataFrame:
    primary = df[df["Key variable"].isin(["Power_kW", "COP"])].copy()
    pivot = primary.pivot_table(
        index=["Project", "Site", "Site letter", "Equipment", "Raw chiller", "Model type"],
        columns="Key variable",
        values=["CVRMSE", "NMBE", "R2", "GL14"],
        aggfunc="first",
    ).reset_index()
    pivot.columns = ["_".join(str(x) for x in col if str(x)) for col in pivot.columns.to_flat_index()]
    pivot = pivot.rename(
        columns={
            "CVRMSE_Power_kW": "Pchiller CVRMSE (%)",
            "NMBE_Power_kW": "Pchiller NMBE (%)",
            "R2_Power_kW": "Pchiller R2",
            "GL14_Power_kW": "Pchiller GL14 bool",
            "CVRMSE_COP": "COP CVRMSE (%)",
            "NMBE_COP": "COP NMBE (%)",
            "R2_COP": "COP R2",
            "GL14_COP": "COP GL14 bool",
        }
    )
    pivot["Pass count"] = pivot["Pchiller GL14 bool"].astype(int) + pivot["COP GL14 bool"].astype(int)
    pivot["Weighted score"] = (
        0.6 * (pivot["Pchiller CVRMSE (%)"] + pivot["Pchiller NMBE (%)"].abs())
        + 0.4 * (pivot["COP CVRMSE (%)"] + pivot["COP NMBE (%)"].abs())
    )
    return pivot


def build_table6(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pivot = primary_pivot(df)
    details = pivot.sort_values(
        ["Site letter", "Equipment", "Model type"],
        key=lambda s: s.map({v: i for i, v in enumerate(SITE_ORDER + MODEL_ORDER)}).fillna(s)
        if s.name in {"Site letter", "Model type"}
        else s,
    ).copy()

    selected_rows = []
    for _, group in pivot.groupby(["Site letter", "Equipment"], sort=False):
        chosen = group.sort_values(
            ["Pass count", "Weighted score", "Pchiller CVRMSE (%)", "COP CVRMSE (%)"],
            ascending=[False, True, True, True],
        ).iloc[0]
        selected_rows.append(chosen)

    selected = pd.DataFrame(selected_rows).sort_values(
        ["Site letter", "Equipment"],
        key=lambda s: s.map({site: i for i, site in enumerate(SITE_ORDER)}).fillna(s)
        if s.name == "Site letter"
        else s,
    )
    table6 = pd.DataFrame(
        {
            "Site": selected["Site letter"],
            "Circuit": selected["Equipment"],
            "Selected model": selected["Model type"],
            "Pchiller CVRMSE (%)": selected["Pchiller CVRMSE (%)"],
            "Pchiller NMBE (%)": selected["Pchiller NMBE (%)"],
            "Pchiller GL14": np.where(selected["Pchiller GL14 bool"], "Pass", "Fail"),
            "COP CVRMSE (%)": selected["COP CVRMSE (%)"],
            "COP NMBE (%)": selected["COP NMBE (%)"],
            "COP GL14": np.where(selected["COP GL14 bool"], "Pass", "Fail"),
            "Pass count": selected["Pass count"],
            "Weighted score": selected["Weighted score"],
        }
    )
    return table6, details


def round_for_manuscript(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_bool_dtype(out[col]):
            continue
        if pd.api.types.is_numeric_dtype(out[col]):
            if col in {"Pchiller R2", "COP R2", "Qevap R2", "Weighted score"}:
                out[col] = out[col].round(4)
            elif col == "Pass count":
                out[col] = out[col].astype(int)
            else:
                out[col] = out[col].round(2)
    return out


def write_outputs(table4: pd.DataFrame, table5: pd.DataFrame, table6: pd.DataFrame, details: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        round_for_manuscript(table4).to_excel(writer, sheet_name="Table 4", index=False)
        round_for_manuscript(table5).to_excel(writer, sheet_name="Table 5", index=False)
        round_for_manuscript(table6).to_excel(writer, sheet_name="Table 6", index=False)
        round_for_manuscript(details).to_excel(writer, sheet_name="Selection details", index=False)

    for name, frame in {
        "table4_recalculated.csv": round_for_manuscript(table4),
        "table5_recalculated.csv": round_for_manuscript(table5),
        "table6_recalculated.csv": round_for_manuscript(table6),
    }.items():
        frame.to_csv(output.parent / name, index=False)


def main() -> int:
    args = parse_args()
    df = load_metrics(args.input)
    table4 = build_table4(df)
    table5 = build_table5(df)
    table6, details = build_table6(df)
    write_outputs(table4, table5, table6, details, args.output)
    print(f"Output workbook: {args.output}")
    print(f"Table 4 rows: {len(table4)}")
    print(f"Table 5 rows: {len(table5)}")
    print(f"Table 6 rows: {len(table6)}")
    print("Selected model counts:", table6["Selected model"].value_counts().to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
