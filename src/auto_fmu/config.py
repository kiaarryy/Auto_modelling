from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


EQUIPMENT_TYPES = ("chiller", "cooling_tower", "pump", "heat_exchanger")


def load_config(path: Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config["_config_path"] = config_path
    config["_root"] = config_path.parent
    config.setdefault("outputs_dir", "outputs")
    config.setdefault("equipment", {})
    return config


def resolve_path(config: dict[str, Any], value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (Path(config["_root"]) / path).resolve()


def validate_config(config: dict[str, Any]) -> list[str]:
    errors = []
    for equipment_type, devices in config.get("equipment", {}).items():
        if equipment_type not in EQUIPMENT_TYPES:
            errors.append(f"unsupported equipment type: {equipment_type}")
        for device in devices or []:
            if not device.get("id"):
                errors.append(f"{equipment_type}: device id is required")
            if not device.get("metric"):
                errors.append(f"{equipment_type}/{device.get('id', '?')}: metric is required")
            source = device.get("source_csv")
            if source and not resolve_path(config, source).exists():
                errors.append(f"{equipment_type}/{device.get('id', '?')}: source CSV does not exist: {source}")
    return errors
