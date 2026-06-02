from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


EQUIPMENT_TYPES = ("chiller", "cooling_tower", "pump", "heat_exchanger")
ENVIRONMENT_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _expand_environment(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if not isinstance(value, str):
        return value
    expanded = os.path.expandvars(value)
    unresolved = ENVIRONMENT_PATTERN.findall(expanded)
    if unresolved:
        raise ValueError(f"environment variable is not defined: {', '.join(sorted(unresolved))}")
    return expanded


def _load_yaml(path: Path, seen: set[Path]) -> dict[str, Any]:
    path = Path(path).resolve()
    if path in seen:
        raise ValueError(f"configuration extends cycle: {path}")
    seen.add(path)
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    parent = config.pop("extends", None)
    if parent:
        parent_path = Path(parent)
        if not parent_path.is_absolute():
            parent_path = path.parent / parent_path
        config = _deep_merge(_load_yaml(parent_path, seen), config)
    seen.remove(path)
    return config


def load_config(path: Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    config = _expand_environment(_load_yaml(config_path, set()))
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
            if not device.get("metric") and not device.get("runner"):
                errors.append(f"{equipment_type}/{device.get('id', '?')}: metric is required")
            source = device.get("source_csv")
            if source and not resolve_path(config, source).exists():
                errors.append(f"{equipment_type}/{device.get('id', '?')}: source CSV does not exist: {source}")
            for source_name, source_value in device.get("sources", {}).items():
                values = source_value if isinstance(source_value, list) else [source_value]
                for value in values:
                    if value and not resolve_path(config, value).exists():
                        errors.append(f"{equipment_type}/{device.get('id', '?')}: {source_name} does not exist: {value}")
    return errors
