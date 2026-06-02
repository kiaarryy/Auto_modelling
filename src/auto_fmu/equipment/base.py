from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from auto_fmu.fmu.exporter import ExportResult, export_fmu
from auto_fmu.readiness import ReadinessResult
from auto_fmu.status import RunStatus, select_status


@dataclass(frozen=True)
class RunnerContext:
    config: dict[str, Any]
    equipment_type: str
    device: dict[str, Any]
    run_id: str
    run_dir: Path
    device_dir: Path


class EquipmentRunner(ABC):
    def __init__(self, context: RunnerContext) -> None:
        self.context = context
        self.rendered_model: Path | None = None
        self.export_result = ExportResult(True, self.export_mode, "not started")
        self.readiness = ReadinessResult(False, ("readiness has not run",), {})
        self.metric_rows: list[dict[str, Any]] = []

    @property
    def export_mode(self):
        from auto_fmu.fmu.exporter import ExportMode

        return ExportMode(self.context.device.get("export", {}).get("mode", ExportMode.DISABLED.value))

    @property
    def device_dir(self) -> Path:
        return self.context.device_dir

    @abstractmethod
    def prepare(self) -> None:
        """Write canonical input data and adapter QA artifacts."""

    @abstractmethod
    def check_readiness(self) -> ReadinessResult:
        """Return whether the device has enough valid data to model."""

    @abstractmethod
    def calibrate(self) -> None:
        """Fit and select model candidates."""

    @abstractmethod
    def validate(self) -> None:
        """Write full-period metrics and time series."""

    def render_modelica(self) -> Path | None:
        return None

    def export_fmu(self) -> ExportResult:
        return export_fmu(
            self.context.device.get("export"),
            output_dir=self.device_dir / "fmu",
            rendered_model=self.rendered_model,
        )

    @abstractmethod
    def report(self, status: RunStatus) -> None:
        """Write a human-readable device summary."""

    def regression_rows(self) -> list[dict[str, Any]]:
        return []

    def metrics_ok(self) -> bool:
        thresholds = {
            "CVRMSE_pct": 10.0,
            "NMBE_pct": 5.0,
            **self.context.config.get("thresholds", {}),
            **self.context.device.get("thresholds", {}),
        }
        return bool(self.metric_rows) and all(
            float(row["CVRMSE_pct"]) <= float(thresholds["CVRMSE_pct"])
            and abs(float(row["NMBE_pct"])) <= float(thresholds["NMBE_pct"])
            for row in self.metric_rows
        )

    def _write_readiness(self) -> None:
        self._write_json(self.device_dir / "readiness.json", self.readiness.to_dict())

    def _write_manifest(self, status: RunStatus) -> None:
        self._write_json(
            self.device_dir / "manifest.json",
            {
                "run_id": self.context.run_id,
                "equipment_type": self.context.equipment_type,
                "equipment_id": self.context.device["id"],
                "status": status.value,
                "readiness": self.readiness.to_dict(),
                "export": {
                    "mode": self.export_result.mode.value,
                    "ok": self.export_result.ok,
                    "message": self.export_result.message,
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def execute(self) -> RunStatus:
        self.prepare()
        self.readiness = self.check_readiness()
        self._write_readiness()
        if not self.readiness.ready:
            self.export_result = ExportResult(True, self.export_mode, "not executed because readiness failed")
            status = RunStatus.NOT_READY
            self.report(status)
            self._write_manifest(status)
            return status
        self.calibrate()
        self.validate()
        self.rendered_model = self.render_modelica()
        self.export_result = self.export_fmu()
        status = select_status(readiness_ok=True, export_ok=self.export_result.ok, metrics_ok=self.metrics_ok())
        self.report(status)
        self._write_manifest(status)
        return status


def write_csv(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path
