from __future__ import annotations

import math
from typing import Iterable

import numpy as np


def regression_metrics(measured: Iterable[float], simulated: Iterable[float]) -> dict[str, float]:
    measured_array = np.asarray(list(measured), dtype=float)
    simulated_array = np.asarray(list(simulated), dtype=float)
    mask = np.isfinite(measured_array) & np.isfinite(simulated_array)
    if not mask.any():
        raise ValueError("no finite metric pairs")
    measured_array = measured_array[mask]
    simulated_array = simulated_array[mask]
    residual = simulated_array - measured_array
    rmse = float(math.sqrt(float(np.mean(residual**2))))
    mae = float(np.mean(np.abs(residual)))
    mean = float(np.mean(measured_array))
    return {
        "N": int(len(measured_array)),
        "RMSE": rmse,
        "MAE": mae,
        "MBE": float(np.mean(residual)),
        "CVRMSE_pct": float(rmse / mean * 100.0) if mean else float("nan"),
        "NMBE_pct": float(np.mean(residual) / mean * 100.0) if mean else float("nan"),
    }
