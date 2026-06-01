from __future__ import annotations

import pandas as pd
import pytest

from auto_fmu.regression import compare_metric_rows
from auto_fmu.windows import compress_time_axis, select_continuous_window, validate_finite_table


def test_compress_time_axis_preserves_original_timestamp_mapping() -> None:
    source = pd.DataFrame({"timestamp": ["2024-01-01 00:00", "2024-01-01 01:00"], "value": [1, 2]})

    compressed, mapping = compress_time_axis(source, "timestamp", step_seconds=300)

    assert compressed["time_s"].tolist() == [0.0, 300.0]
    assert mapping.to_dict("records") == [
        {"source_timestamp": "2024-01-01 00:00", "time_s": 0.0},
        {"source_timestamp": "2024-01-01 01:00", "time_s": 300.0},
    ]


def test_select_continuous_window_does_not_cross_gap() -> None:
    source = pd.DataFrame({"time_s": [0, 300, 600, 1800, 2100], "value": [1, 2, 3, 4, 5]})

    selected = select_continuous_window(source, rows=2, step_seconds=300)

    assert selected["time_s"].tolist() == [0, 300]


def test_validate_finite_table_rejects_infinite_cells() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        validate_finite_table(pd.DataFrame({"time_s": [0.0], "value": [float("inf")]}))


def test_regression_comparison_applies_absolute_tolerance() -> None:
    compared = compare_metric_rows(
        [{"equipment_id": "CDWP_03", "candidate": "affinity_y3", "variable": "CVRMSE", "value": 3.0}],
        [{"equipment_id": "CDWP_03", "candidate": "affinity_y3", "variable": "CVRMSE", "value": 3.0005}],
        tolerance=1e-3,
    )

    assert compared[0]["status"] == "pass"
    assert compared[0]["absolute_difference"] == pytest.approx(0.0005)
