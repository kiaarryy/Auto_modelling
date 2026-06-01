from __future__ import annotations

import numpy as np
import pandas as pd


def validate_finite_table(table: pd.DataFrame) -> None:
    if table.isna().any().any():
        raise ValueError("table contains blank or non-finite cells")
    numeric = table.select_dtypes(include=[np.number])
    if numeric.size and not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("table contains non-finite cells")


def compress_time_axis(table: pd.DataFrame, timestamp_column: str, step_seconds: int = 300) -> tuple[pd.DataFrame, pd.DataFrame]:
    compressed = table.copy()
    time_s = np.arange(len(compressed), dtype=float) * float(step_seconds)
    mapping = pd.DataFrame({"source_timestamp": compressed[timestamp_column].astype(str), "time_s": time_s})
    compressed.insert(0, "time_s", time_s)
    return compressed, mapping


def select_continuous_window(table: pd.DataFrame, rows: int, step_seconds: int = 300) -> pd.DataFrame:
    if rows <= 0:
        raise ValueError("rows must be positive")
    time_values = table["time_s"].to_numpy(dtype=float)
    for start in range(0, len(table) - rows + 1):
        selected = table.iloc[start : start + rows]
        if np.allclose(np.diff(time_values[start : start + rows]), float(step_seconds)):
            return selected.copy()
    raise ValueError(f"no continuous {rows}-row window")
