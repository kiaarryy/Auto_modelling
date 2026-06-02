from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_fmu.equipment.chiller import normalize_chiller_frame, series_metrics


def test_normalize_chiller_frame_builds_steady_si_table() -> None:
    raw = pd.DataFrame(
        {
            "DateTime": ["2024-01-01 00:00", "2024-01-01 00:05"],
            "CHWS-WTS": [7.0, 7.5],
            "CHWR-WTS": [12.0, 12.5],
            "CDWS-WTS": [24.0, 24.5],
            "CDWR-WTS": [29.0, 29.5],
            "CHW-WFM": [100.0, 110.0],
            "CDW-WFM": [120.0, 130.0],
            "P/kw": [200.0, 220.0],
        }
    )
    columns = {
        "timestamp": "DateTime",
        "chws_C": "CHWS-WTS",
        "chwr_C": "CHWR-WTS",
        "cdws_C": "CDWS-WTS",
        "cdwr_C": "CDWR-WTS",
        "chw_lps": "CHW-WFM",
        "cdw_lps": "CDW-WFM",
        "power_kw": "P/kw",
    }

    table = normalize_chiller_frame(raw, columns)

    assert table.columns.tolist() == ["Time", "timestamp", "CHWS", "CHWR", "CDWS", "CDWR", "CHW", "CDW", "P/kw", "VSD", "deltaT_chw", "deltaT_cdw", "Q_evap_kW"]
    assert table["Time"].tolist() == [0.0, 300.0]
    assert table["Q_evap_kW"].tolist() == pytest.approx([2093.0, 2302.3])


def test_chiller_series_metrics_reports_power_cooling_and_cop() -> None:
    frame = pd.DataFrame(
        {
            "P_m": [100.0, 200.0],
            "P_s": [110.0, 190.0],
            "Q_m": [1000.0, 2000.0],
            "Q_s": [990.0, 2010.0],
        }
    )

    metrics = series_metrics(frame)

    assert set(metrics) == {"P_W", "QEva_W", "COP"}
    assert metrics["P_W"]["CVRMSE_pct"] == np.sqrt(100.0) / 150.0 * 100.0
