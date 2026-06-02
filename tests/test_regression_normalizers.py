from __future__ import annotations

import pandas as pd
import pytest

from auto_fmu.regression_runner import _normalize_chiller_timeseries, _normalize_cooling_tower_legacy, _normalize_heat_exchanger_legacy


def test_chiller_timeseries_normalizer_uses_public_equipment_id_and_candidate_name() -> None:
    frame = pd.DataFrame(
        {
            "Equipment": ["DCCP 01", "DCCP 01"],
            "Model type": ["EEIR", "EEIR"],
            "P_measured_kW": [10.0, 20.0],
            "P_sim_kW": [10.0, 22.0],
            "Q_measured_kW": [100.0, 200.0],
            "Q_sim_kW": [100.0, 200.0],
            "COP_measured": [10.0, 10.0],
            "COP_sim": [10.0, 11.0],
        }
    )

    normalized = _normalize_chiller_timeseries(frame)

    assert {row["equipment_id"] for row in normalized} == {"DCCP_01"}
    assert {row["candidate"] for row in normalized} == {"ElectricReformulatedEIR"}
    assert {row["variable"] for row in normalized} == {"P_W", "QEva_W", "COP"}


def test_cooling_tower_legacy_normalizer_maps_cvrmse() -> None:
    normalized = _normalize_cooling_tower_legacy(pd.DataFrame([{"tower": "CT_03", "model": "Merkel", "variable": "Q", "CVRMSE_%": 1.25}]))

    assert normalized == [{"equipment_id": "CT_03", "candidate": "Merkel", "variable": "Q", "value": 1.25}]


def test_heat_exchanger_legacy_normalizer_maps_cvrmse() -> None:
    normalized = _normalize_heat_exchanger_legacy(pd.DataFrame([{"hx": "HX_02", "model": "PlateEffectivenessNTU", "variable": "Q", "CVRMSE": 6.5}]))

    assert normalized == [{"equipment_id": "HX_02", "candidate": "PlateEffectivenessNTU", "variable": "Q", "value": pytest.approx(6.5)}]
