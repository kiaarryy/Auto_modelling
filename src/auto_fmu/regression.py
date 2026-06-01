from __future__ import annotations

from typing import Iterable


KEYS = ("equipment_id", "candidate", "variable")


def compare_metric_rows(
    legacy_rows: Iterable[dict[str, object]],
    new_rows: Iterable[dict[str, object]],
    tolerance: float = 1e-3,
) -> list[dict[str, object]]:
    legacy = {tuple(row[key] for key in KEYS): row for row in legacy_rows}
    current = {tuple(row[key] for key in KEYS): row for row in new_rows}
    compared = []
    for key in sorted(set(legacy) | set(current)):
        legacy_row = legacy.get(key)
        current_row = current.get(key)
        if legacy_row is None or current_row is None:
            compared.append(dict(zip(KEYS, key), status="missing", tolerance=tolerance))
            continue
        legacy_value = float(legacy_row["value"])
        new_value = float(current_row["value"])
        difference = abs(legacy_value - new_value)
        compared.append(
            dict(
                zip(KEYS, key),
                legacy_value=legacy_value,
                new_value=new_value,
                absolute_difference=difference,
                tolerance=float(tolerance),
                status="pass" if difference <= tolerance else "fail",
            )
        )
    return compared
