"""Run full-period Site A heat exchanger FMU simulations with calibrated parameters."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

try:
    from calibrate_site_a_hx_fmus import (
        CONST_FMU,
        OUT_DIR as CAL_DIR,
        PLATE_FMU,
        TABLE_DIR,
        flatten_metrics,
        simulate_case,
        start_values,
    )
    from prepare_site_a_hx_fmu_tables import NUMERIC_FMU_COLUMNS, write_dymola_table
except ImportError:
    from scripts.calibrate_site_a_hx_fmus import (
        CONST_FMU,
        OUT_DIR as CAL_DIR,
        PLATE_FMU,
        TABLE_DIR,
        flatten_metrics,
        simulate_case,
        start_values,
    )
    from scripts.prepare_site_a_hx_fmu_tables import NUMERIC_FMU_COLUMNS, write_dymola_table


ROOT = Path(__file__).resolve().parents[1]
HX_OUT = ROOT / "outputs" / "heat_exchanger"
OUT_DIR = HX_OUT / "validation"
TIMESERIES_DIR = HX_OUT / "best_timeseries"
LOG_DIR = HX_OUT / "logs" / "full_period_validation"
BEST_PARAMETERS = CAL_DIR / "site_a_hx_best_parameters.csv"
MODEL_BEST_PARAMETERS = CAL_DIR / "site_a_hx_model_best_parameters.csv"
CHUNK_ROWS = 288


def clean_params(row: Mapping[str, object]) -> dict[str, object]:
    skip = {
        "hx",
        "model",
        "score",
        "timeseries",
        "candidate_id",
        "source_start_row",
        "source_end_row",
        "rows",
        "representative_score",
    }
    out: dict[str, object] = {}
    for key, value in row.items():
        if key in skip or pd.isna(value):
            continue
        out[key] = float(value) if isinstance(value, (int, float, np.number)) else value
    return out


def full_period_table(source: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    keep = ["DateTime", *[col for col in NUMERIC_FMU_COLUMNS if col in source.columns]]
    work = source[keep].copy()
    meta = pd.DataFrame(
        {
            "DateTime": work["DateTime"] if "DateTime" in work else "",
            "source_time_s": work["time_s"].to_numpy(float),
        }
    )
    work["time_s"] = np.arange(len(work), dtype=float) * 300.0
    return work, meta


def iter_chunk_tables(source: pd.DataFrame, chunk_rows: int = CHUNK_ROWS) -> list[tuple[int, pd.DataFrame, pd.DataFrame]]:
    chunks: list[tuple[int, pd.DataFrame, pd.DataFrame]] = []
    for start in range(0, len(source), chunk_rows):
        chunk_source = source.iloc[start : start + chunk_rows].copy()
        table, mapping = full_period_table(chunk_source)
        mapping["global_row"] = np.arange(start, start + len(mapping), dtype=int)
        chunks.append((start, table, mapping))
    return chunks


def _fmu_for_model(model: str) -> Path:
    return PLATE_FMU if model == "PlateEffectivenessNTU" else CONST_FMU


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TIMESERIES_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    parameter_source = MODEL_BEST_PARAMETERS if MODEL_BEST_PARAMETERS.exists() else BEST_PARAMETERS
    if not parameter_source.exists():
        print(f"Missing calibration parameters: {parameter_source}")
        return 2
    if not PLATE_FMU.exists() or not CONST_FMU.exists():
        print(f"Missing FMUs in {PLATE_FMU.parent}. Export Dymola FMUs first, then rerun.")
        return 2

    best = pd.read_csv(parameter_source)
    metrics_rows: list[dict[str, object]] = []
    manifest_rows: list[dict[str, object]] = []
    failed_chunk_rows: list[dict[str, object]] = []
    tables_dir = OUT_DIR / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    for table_csv in sorted(TABLE_DIR.glob("HX_*_fmu_table.csv")):
        hx = table_csv.name.split("_fmu_table.csv")[0]
        source = pd.read_csv(table_csv)
        if source.empty:
            continue
        rows = best.loc[best["hx"] == hx]
        if rows.empty:
            continue
        full_table, full_mapping = full_period_table(source)
        table_csv_out = tables_dir / f"{hx}_full_period_table.csv"
        mapping_csv = tables_dir / f"{hx}_full_period_time_mapping.csv"
        full_table.to_csv(table_csv_out, index=False, encoding="utf-8-sig")
        full_mapping.to_csv(mapping_csv, index=False, encoding="utf-8-sig")
        for _, row in rows.iterrows():
            model = str(row["model"])
            params = clean_params(row.to_dict())
            candidate = {"model": model, **params}
            result_frames: list[pd.DataFrame] = []
            chunk_manifest_rows: list[dict[str, object]] = []
            for chunk_id, (start_row, table, mapping) in enumerate(iter_chunk_tables(source), start=1):
                if table.empty:
                    continue
                table_txt = tables_dir / f"{hx}_{model}_chunk_{chunk_id:04d}.txt"
                write_dymola_table(table_txt, table)
                values = start_values(table_txt, candidate)
                try:
                    result = simulate_case(
                        _fmu_for_model(model),
                        values,
                        float(table["time_s"].iloc[-1]),
                        LOG_DIR / hx / model / f"chunk_{chunk_id:04d}.md",
                    )
                except Exception as exc:  # noqa: BLE001 - full-period validation should keep other chunks/models.
                    failed_chunk_rows.append(
                        {
                            "hx": hx,
                            "model": model,
                            "candidate_id": row.get("candidate_id", ""),
                            "chunk_id": chunk_id,
                            "source_start_row": start_row,
                            "source_end_row": start_row + len(table) - 1,
                            "rows": len(table),
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            "table": str(table_txt),
                        }
                    )
                    continue
                if "time" in result.columns:
                    result["time"] = pd.to_numeric(result["time"], errors="coerce") + float(start_row * 300)
                result["chunk_id"] = chunk_id
                result["source_start_row"] = start_row
                result_frames.append(result)
                chunk_manifest_rows.append(
                    {
                        "hx": hx,
                        "model": model,
                        "chunk_id": chunk_id,
                        "source_start_row": start_row,
                        "source_end_row": start_row + len(table) - 1,
                        "rows": len(table),
                        "table": str(table_txt),
                    }
                )
            if not result_frames:
                continue
            result = pd.concat(result_frames, ignore_index=True)
            ts_path = TIMESERIES_DIR / f"{hx}_{model}_full_period_timeseries.csv"
            result.to_csv(ts_path, index=False, encoding="utf-8-sig")
            metrics = flatten_metrics(result, hx, model, "full_period")
            for metric in metrics:
                metric["candidate_id"] = row.get("candidate_id", "")
                metric["timeseries"] = str(ts_path)
                metrics_rows.append(metric)
            manifest_rows.append(
                {
                    "hx": hx,
                    "model": model,
                    "candidate_id": row.get("candidate_id", ""),
                    "rows": len(full_table),
                    "simulated_rows": len(result),
                    "stop_time_s": float(full_table["time_s"].iloc[-1]),
                    "chunk_rows": CHUNK_ROWS,
                    "n_chunks": len(result_frames),
                    "failed_chunks": len([r for r in failed_chunk_rows if r["hx"] == hx and r["model"] == model]),
                    "table": str(table_csv_out),
                    "time_mapping": str(mapping_csv),
                    "timeseries": str(ts_path),
                    "parameter_source": str(parameter_source),
                }
            )
            pd.DataFrame(chunk_manifest_rows).to_csv(tables_dir / f"{hx}_{model}_chunk_manifest.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame(metrics_rows).to_csv(OUT_DIR / "site_a_hx_full_period_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(manifest_rows).to_csv(OUT_DIR / "site_a_hx_full_period_manifest.csv", index=False, encoding="utf-8-sig")
    failed_columns = ["hx", "model", "candidate_id", "chunk_id", "source_start_row", "source_end_row", "rows", "error_type", "error", "table"]
    pd.DataFrame(failed_chunk_rows, columns=failed_columns).to_csv(OUT_DIR / "site_a_hx_full_period_failed_chunks.csv", index=False, encoding="utf-8-sig")
    print(f"Output: {OUT_DIR}")
    if failed_chunk_rows:
        print(f"Failed full-period chunks: {len(failed_chunk_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
