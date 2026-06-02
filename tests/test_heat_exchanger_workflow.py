from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace

from auto_fmu.equipment.heat_exchanger import HeatExchangerRunner, NUMERIC_FMU_COLUMNS, build_candidate_grid, iter_chunk_tables, select_window, validate_finite_table


def test_hx_comb_time_table_rejects_non_finite_values() -> None:
    table = pd.DataFrame([{column: 1.0 for column in NUMERIC_FMU_COLUMNS}])
    table.loc[0, "Q_m_W"] = np.inf

    with pytest.raises(ValueError, match="blank, NaN, or infinite"):
        validate_finite_table(table)


def test_hx_chunking_keeps_final_partial_chunk() -> None:
    source = pd.DataFrame({"time_s": np.arange(5, dtype=float), "value": np.arange(5)})

    chunks = iter_chunk_tables(source, chunk_rows=2)

    assert [(start, len(table)) for start, table in chunks] == [(0, 2), (2, 2), (4, 1)]
    assert chunks[-1][1]["time_s"].tolist() == [0.0]


def test_hx_candidate_grid_contains_two_model_families() -> None:
    nominals = {
        "m1_flow_nominal": 10.0,
        "m2_flow_nominal": 20.0,
        "dp1_nominal": 0.0,
        "dp2_nominal": 0.0,
        "Q_flow_nominal": 1000.0,
        "T_a1_nominal": 295.0,
        "T_b1_nominal": 290.0,
        "T_a2_nominal": 285.0,
        "T_b2_nominal": 292.0,
        "eps": 0.8,
    }

    candidates = build_candidate_grid(nominals)

    assert len(candidates) == 14
    assert {candidate["model"] for candidate in candidates} == {"PlateEffectivenessNTU", "ConstantEffectiveness"}


def test_hx_calibration_window_is_contiguous_and_compressed() -> None:
    source = pd.DataFrame({"time_s": [0.0, 300.0, 600.0, 1800.0, 2100.0], "T1In_m_C": [1, 1, 1, 1, 1], "T1Out_m_C": [1, 1, 1, 1, 1], "T2In_m_C": [1, 1, 1, 1, 1], "T2Out_m_C": [1, 1, 1, 1, 1], "m1_flow_kg_s": [1, 1, 1, 1, 1], "m2_flow_kg_s": [1, 1, 1, 1, 1], "Q_m_W": [1, 1, 1, 1, 1]})

    window = select_window(source, max_rows=3, stride=1)

    assert window["time_s"].tolist() == [0.0, 300.0, 600.0]


def test_hx_not_ready_device_has_no_regression_rows() -> None:
    runner = HeatExchangerRunner.__new__(HeatExchangerRunner)
    runner.context = SimpleNamespace(device={"id": "HX_03"})

    assert runner.regression_rows() == []
