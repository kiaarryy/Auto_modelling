from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from auto_fmu.config import EQUIPMENT_TYPES, resolve_path
from auto_fmu.manifest import RunManifest
from auto_fmu.metrics import regression_metrics
from auto_fmu.reporting import table_to_markdown


def _selected_types(config: dict[str, Any], equipment: str) -> Iterable[str]:
    return config["equipment"].keys() if equipment == "all" else (equipment,)


def _run_dir(config: dict[str, Any], run_id: str) -> Path:
    return (Path(config["_root"]) / config["outputs_dir"] / "runs" / run_id).resolve()


def _manifest(config: dict[str, Any], run_id: str) -> tuple[Path, RunManifest]:
    run_dir = _run_dir(config, run_id)
    return run_dir, RunManifest(run_dir / "manifest.json", run_id)


def prepare(config: dict[str, Any], equipment: str, run_id: str) -> Path:
    run_dir, manifest = _manifest(config, run_id)
    for equipment_type in _selected_types(config, equipment):
        frames = []
        for device in config["equipment"].get(equipment_type, []):
            frame = pd.read_csv(resolve_path(config, device["source_csv"]))
            if "timestamp" not in frame:
                raise ValueError(f"{equipment_type}/{device['id']}: timestamp column is required")
            if device["metric"] not in frame:
                raise ValueError(f"{equipment_type}/{device['id']}: metric column is required: {device['metric']}")
            frame.insert(0, "equipment_id", device["id"])
            frames.append(frame)
        if not frames:
            continue
        output = run_dir / equipment_type / "prepare" / "canonical.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(frames, ignore_index=True).to_csv(output, index=False)
        manifest.add_artifact(output, run_dir)
    manifest.record_stage("prepare")
    manifest.write()
    return run_dir


def calibrate(config: dict[str, Any], equipment: str, run_id: str) -> Path:
    run_dir, manifest = _manifest(config, run_id)
    for equipment_type in _selected_types(config, equipment):
        prepared = run_dir / equipment_type / "prepare" / "canonical.csv"
        if not prepared.exists():
            continue
        frame = pd.read_csv(prepared)
        rows = []
        for device in config["equipment"].get(equipment_type, []):
            selected = frame[frame["equipment_id"] == device["id"]]
            for candidate in device.get("candidates", ["passthrough"]):
                if candidate != "passthrough":
                    raise ValueError(f"{equipment_type}/{device['id']}: unsupported fixture candidate: {candidate}")
                metric = regression_metrics(selected[device["metric"]], selected[device["metric"]])
                rows.append({"equipment_id": device["id"], "candidate": candidate, "variable": device["metric"], **metric})
        stage = run_dir / equipment_type / "calibrate"
        stage.mkdir(parents=True, exist_ok=True)
        metrics_path = stage / "all_candidate_metrics.csv"
        selected_path = stage / "selected_models.csv"
        parameters_path = stage / "parameters.csv"
        pd.DataFrame(rows).to_csv(metrics_path, index=False)
        pd.DataFrame(rows)[["equipment_id", "candidate"]].drop_duplicates().to_csv(selected_path, index=False)
        pd.DataFrame([{"equipment_id": row["equipment_id"], "candidate": row["candidate"], "parameters": "{}"} for row in rows]).to_csv(
            parameters_path, index=False
        )
        for path in (metrics_path, selected_path, parameters_path):
            manifest.add_artifact(path, run_dir)
    manifest.record_stage("calibrate")
    manifest.write()
    return run_dir


def validate(config: dict[str, Any], equipment: str, run_id: str) -> Path:
    run_dir, manifest = _manifest(config, run_id)
    for equipment_type in _selected_types(config, equipment):
        prepared = run_dir / equipment_type / "prepare" / "canonical.csv"
        if not prepared.exists():
            continue
        frame = pd.read_csv(prepared)
        metric_rows = []
        series_rows = []
        selections = []
        for device in config["equipment"].get(equipment_type, []):
            selected = frame[frame["equipment_id"] == device["id"]]
            candidate = device.get("candidates", ["passthrough"])[0]
            measured = selected[device["metric"]]
            simulated = measured
            metric_rows.append(
                {"equipment_id": device["id"], "candidate": candidate, "variable": device["metric"], **regression_metrics(measured, simulated)}
            )
            selections.append({"equipment_id": device["id"], "candidate": candidate})
            for timestamp, measured_value, simulated_value in zip(selected["timestamp"], measured, simulated):
                series_rows.append(
                    {
                        "equipment_id": device["id"],
                        "candidate": candidate,
                        "timestamp": timestamp,
                        "variable": device["metric"],
                        "measured": measured_value,
                        "simulated": simulated_value,
                    }
                )
        stage = run_dir / equipment_type / "validate"
        stage.mkdir(parents=True, exist_ok=True)
        paths = {
            "metrics": stage / "full_period_metrics.csv",
            "selected": stage / "selected_models.csv",
            "series": stage / "time_series.csv",
        }
        pd.DataFrame(metric_rows).to_csv(paths["metrics"], index=False)
        pd.DataFrame(selections).to_csv(paths["selected"], index=False)
        pd.DataFrame(series_rows).to_csv(paths["series"], index=False)
        for path in paths.values():
            manifest.add_artifact(path, run_dir)
    manifest.record_stage("validate")
    manifest.write()
    return run_dir


def report(config: dict[str, Any], equipment: str, run_id: str) -> Path:
    run_dir, manifest = _manifest(config, run_id)
    for equipment_type in _selected_types(config, equipment):
        metrics_path = run_dir / equipment_type / "validate" / "full_period_metrics.csv"
        if not metrics_path.exists():
            continue
        metrics = pd.read_csv(metrics_path)
        output = run_dir / equipment_type / "report" / "summary.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            f"# {equipment_type} fixture report\n\n"
            "This report validates orchestration only. The `passthrough` candidate is not a real equipment model.\n\n"
            + table_to_markdown(metrics)
            + "\n",
            encoding="utf-8",
        )
        manifest.add_artifact(output, run_dir)
    manifest.record_stage("report")
    manifest.write()
    return run_dir
