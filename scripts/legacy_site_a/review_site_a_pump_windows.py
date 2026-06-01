"""Review Site A pump calibration-window artifacts for Stage 3 readiness."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TABLE_DIR = ROOT / "outputs" / "pump" / "site_a_tables"
OUT_DIR = ROOT / "outputs" / "pump" / "stage3_windows"


def summarize_pump_windows(table_dir: Path = TABLE_DIR) -> pd.DataFrame:
    qa_path = table_dir / "site_a_pump_table_qa.csv"
    qa = pd.read_csv(qa_path) if qa_path.exists() else pd.DataFrame()
    qa_by_pump = {str(row["pump"]): row for _, row in qa.iterrows()} if not qa.empty and "pump" in qa else {}

    rows: list[dict[str, object]] = []
    for manifest_path in sorted(table_dir.glob("*_window_manifest.csv")):
        pump = manifest_path.name.replace("_window_manifest.csv", "")
        manifest = pd.read_csv(manifest_path) if manifest_path.stat().st_size else pd.DataFrame()
        window_path = table_dir / f"{pump}_window_table.csv"
        window_table = pd.read_csv(window_path) if window_path.exists() else pd.DataFrame()
        qa_row = qa_by_pump.get(pump)
        notes = str(qa_row["notes"]) if qa_row is not None and "notes" in qa_row else ""
        rows.append(
            {
                "pump": pump,
                "pump_type": str(qa_row["pump_type"]) if qa_row is not None and "pump_type" in qa_row else "",
                "rows_valid": int(qa_row["rows_valid"]) if qa_row is not None and "rows_valid" in qa_row else 0,
                "windows_selected": int(len(manifest)),
                "window_rows": int(manifest["rows"].sum()) if "rows" in manifest else 0,
                "min_window_rows": int(manifest["rows"].min()) if "rows" in manifest and len(manifest) else 0,
                "best_representative_score": float(manifest["representative_score"].min()) if "representative_score" in manifest and len(manifest) else np.nan,
                "first_window_start": str(manifest["source_start_datetime"].iloc[0]) if "source_start_datetime" in manifest and len(manifest) else "",
                "last_window_end": str(manifest["source_end_datetime"].iloc[-1]) if "source_end_datetime" in manifest and len(manifest) else "",
                "mean_window_flow_kg_s": mean_or_nan(window_table, "m_flow_kg_s"),
                "mean_window_y": mean_or_nan(window_table, "y_used"),
                "mean_window_P_meas_W": mean_or_nan(window_table, "P_meas_W"),
                "ready_for_stage4": is_ready_for_stage4(manifest, notes),
                "notes": "" if notes == "nan" else notes,
            }
        )
    return pd.DataFrame(rows).sort_values(["ready_for_stage4", "rows_valid"], ascending=[False, False])


def mean_or_nan(df: pd.DataFrame, col: str) -> float:
    if col not in df or df.empty:
        return float("nan")
    return float(pd.to_numeric(df[col], errors="coerce").mean())


def is_ready_for_stage4(manifest: pd.DataFrame, notes: str) -> bool:
    if manifest.empty or "rows" not in manifest:
        return False
    has_24h = bool((pd.to_numeric(manifest["rows"], errors="coerce") >= 288).any())
    mapping_risk = "verify" in str(notes).lower() or "missing" in str(notes).lower()
    low_window = "less than one 24-hour" in str(notes).lower()
    return has_24h and not mapping_risk and not low_window


def write_markdown_report(summary: pd.DataFrame, path: Path) -> None:
    cols = [
        "pump",
        "pump_type",
        "rows_valid",
        "windows_selected",
        "min_window_rows",
        "best_representative_score",
        "mean_window_flow_kg_s",
        "mean_window_y",
        "mean_window_P_meas_W",
        "ready_for_stage4",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Site A Pump Stage 3 Window Review\n\n")
        f.write("A pump is Stage 4 ready when it has at least one 24-hour window and no mapping-risk notes.\n\n")
        f.write(f"- Pumps reviewed: {len(summary)}\n")
        f.write(f"- Stage 4 ready: {int(summary['ready_for_stage4'].sum()) if 'ready_for_stage4' in summary else 0}\n\n")
        f.write(markdown_table(summary[cols] if not summary.empty else pd.DataFrame(columns=cols)))
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
    summary = summarize_pump_windows(TABLE_DIR)
    csv_path = OUT_DIR / "site_a_pump_window_review.csv"
    md_path = OUT_DIR / "site_a_pump_window_review.md"
    summary.to_csv(csv_path, index=False)
    write_markdown_report(summary, md_path)
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    if not summary.empty:
        print(summary[["pump", "pump_type", "rows_valid", "windows_selected", "min_window_rows", "ready_for_stage4", "notes"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
