from __future__ import annotations

import pandas as pd

from auto_fmu.equipment.cooling_tower import compress_full_period, scale_total_outputs, york_values


def test_ct_full_period_compression_preserves_source_time_mapping() -> None:
    source = pd.DataFrame({"time_s": [0.0, 900.0, 1200.0], "value": [1, 2, 3]})

    compressed, mapping = compress_full_period(source)

    assert compressed["time_s"].tolist() == [0.0, 300.0, 600.0]
    assert mapping["source_time_s"].tolist() == [0.0, 900.0, 1200.0]


def test_ct_two_fan_external_scale_is_applied_once() -> None:
    frame = pd.DataFrame({"Q_s": [10.0], "P_s": [20.0], "Q_m": [30.0], "P_m": [40.0]})

    scaled = scale_total_outputs(frame, factor=2.0)

    assert scaled.to_dict("records") == [{"Q_s": 20.0, "P_s": 40.0, "Q_m": 30.0, "P_m": 40.0}]


def test_yorkcalc_forces_single_fan_internal_output() -> None:
    values = york_values(
        {"table_path": "table.txt", "m_flow_nominal": 1.0, "TAirInWB_nominal": 290.0, "TWatIn_nominal": 300.0, "TWatOut_nominal": 295.0, "yMin": 0.05, "fraFreCon": 0.1},
        {"nFan": 2.0, "TApp_nominal": 3.0, "TRan_nominal": 4.0},
    )

    assert values["nFan"] == 1.0
