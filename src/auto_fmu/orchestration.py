from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from auto_fmu.config import EQUIPMENT_TYPES
from auto_fmu.equipment.base import RunnerContext
from auto_fmu.equipment.registry import create_runner


def run_dir(config: dict[str, Any], run_id: str) -> Path:
    return (Path(config["_root"]) / config["outputs_dir"] / "runs" / run_id).resolve()


def _selected_devices(config: dict[str, Any], equipment: str, equipment_id: str | None = None) -> Iterable[tuple[str, dict[str, Any]]]:
    selected_types = config["equipment"].keys() if equipment == "all" else (equipment,)
    found = False
    for equipment_type in selected_types:
        if equipment_type not in EQUIPMENT_TYPES:
            raise ValueError(f"unsupported equipment type: {equipment_type}")
        for device in config["equipment"].get(equipment_type, []):
            if equipment_id is None or device["id"] == equipment_id:
                found = True
                yield equipment_type, device
    if equipment_id is not None and not found:
        raise ValueError(f"equipment id not found: {equipment}/{equipment_id}")


def run_equipment(config: dict[str, Any], equipment: str, equipment_id: str, run_id: str) -> Path:
    root = run_dir(config, run_id)
    equipment_type, device = next(iter(_selected_devices(config, equipment, equipment_id)))
    device_dir = root / equipment_type / device["id"]
    create_runner(RunnerContext(config, equipment_type, device, run_id, root, device_dir)).execute()
    return device_dir


def run_batch(config: dict[str, Any], equipment: str, run_id: str) -> Path:
    root = run_dir(config, run_id)
    rows = []
    regression_rows: dict[str, list[dict[str, Any]]] = {}
    for equipment_type, device in _selected_devices(config, equipment):
        device_dir = root / equipment_type / device["id"]
        runner = create_runner(RunnerContext(config, equipment_type, device, run_id, root, device_dir))
        status = runner.execute()
        rows.append({"equipment_type": equipment_type, "equipment_id": device["id"], "status": status.value})
        regression_rows.setdefault(equipment_type, []).extend(runner.regression_rows())
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["equipment_type", "equipment_id", "status"]).to_csv(root / "batch_summary.csv", index=False)
    for equipment_type, metric_rows in regression_rows.items():
        if metric_rows:
            output = root / "new_metrics" / f"{equipment_type}.csv"
            output.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(metric_rows).to_csv(output, index=False)
    return root
