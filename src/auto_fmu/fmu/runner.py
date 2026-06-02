from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from auto_fmu.fmu.inspect import FMUInterfaceSnapshot


def validate_start_values(
    snapshot: FMUInterfaceSnapshot,
    start_values: Mapping[str, object],
    *,
    allow_fixed_parameters: bool = False,
) -> None:
    allowed = snapshot.parameters if allow_fixed_parameters else snapshot.tunable_parameters
    invalid = sorted(set(start_values) - set(allowed))
    if invalid:
        raise ValueError(f"parameters are not tunable through FMI: {', '.join(invalid)}")


def build_fmi_input(columns: Mapping[str, Sequence[float]], input_names: Iterable[str]) -> np.ndarray:
    names = ["time", *input_names]
    missing = [name for name in names if name not in columns]
    if missing:
        raise ValueError(f"missing FMI input columns: {', '.join(missing)}")
    lengths = {len(columns[name]) for name in names}
    if len(lengths) != 1:
        raise ValueError("FMI input columns have inconsistent lengths")
    result = np.zeros(next(iter(lengths)), dtype=[(name, np.float64) for name in names])
    for name in names:
        result[name] = np.asarray(columns[name], dtype=float)
    return result


def write_deterministic_csv(path: Path, values: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(values.dtype.names)
        for row in values:
            writer.writerow([format(float(row[name]), ".15g") for name in values.dtype.names or ()])
