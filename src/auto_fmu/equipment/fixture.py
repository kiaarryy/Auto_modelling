from __future__ import annotations

import json

import pandas as pd

from auto_fmu.config import resolve_path
from auto_fmu.equipment.base import EquipmentRunner, write_csv
from auto_fmu.metrics import regression_metrics
from auto_fmu.readiness import ReadinessResult
from auto_fmu.reporting import table_to_markdown
from auto_fmu.status import RunStatus


class FixtureRunner(EquipmentRunner):
    def prepare(self) -> None:
        device = self.context.device
        frame = pd.read_csv(resolve_path(self.context.config, device["source_csv"]))
        metric = device["metric"]
        if "timestamp" not in frame:
            raise ValueError(f"{self.context.equipment_type}/{device['id']}: timestamp column is required")
        if metric not in frame:
            raise ValueError(f"{self.context.equipment_type}/{device['id']}: metric column is required: {metric}")
        write_csv(self.device_dir / "prepare" / "canonical.csv", frame)
        write_csv(
            self.device_dir / "prepare" / "adapter_qa.csv",
            pd.DataFrame([{"check": "rows", "value": len(frame), "status": "pass" if len(frame) else "fail"}]),
        )

    def check_readiness(self) -> ReadinessResult:
        frame = pd.read_csv(self.device_dir / "prepare" / "canonical.csv")
        minimum = int(self.context.device.get("readiness", {}).get("min_rows", 1))
        ready = len(frame) >= minimum
        reasons = [] if ready else [f"requires at least {minimum} rows; got {len(frame)}"]
        return ReadinessResult(ready=ready, reasons=reasons, details={"rows": len(frame), "minimum_rows": minimum})

    def calibrate(self) -> None:
        device = self.context.device
        frame = pd.read_csv(self.device_dir / "prepare" / "canonical.csv")
        rows = []
        for candidate in device.get("candidates", ["passthrough"]):
            if candidate != "passthrough":
                raise ValueError(f"{self.context.equipment_type}/{device['id']}: unsupported fixture candidate: {candidate}")
            rows.append({"candidate": candidate, "variable": device["metric"], **regression_metrics(frame[device["metric"]], frame[device["metric"]])})
        write_csv(self.device_dir / "calibrate" / "all_candidate_metrics.csv", pd.DataFrame(rows))
        write_csv(
            self.device_dir / "calibrate" / "parameters.csv",
            pd.DataFrame([{"candidate": row["candidate"], "parameters": "{}"} for row in rows]),
        )
        self._write_json(self.device_dir / "selected_model.json", {"candidate": rows[0]["candidate"], "parameters": {}})

    def validate(self) -> None:
        device = self.context.device
        candidate = device.get("candidates", ["passthrough"])[0]
        frame = pd.read_csv(self.device_dir / "prepare" / "canonical.csv")
        metric = device["metric"]
        measured = frame[metric]
        self.metric_rows = [{"candidate": candidate, "variable": metric, **regression_metrics(measured, measured)}]
        write_csv(self.device_dir / "validate" / "full_period_metrics.csv", pd.DataFrame(self.metric_rows))
        write_csv(
            self.device_dir / "validate" / "time_series.csv",
            pd.DataFrame(
                {
                    "timestamp": frame["timestamp"],
                    "candidate": candidate,
                    "variable": metric,
                    "measured": measured,
                    "simulated": measured,
                }
            ),
        )

    def report(self, status: RunStatus) -> None:
        metrics = pd.DataFrame(self.metric_rows)
        body = table_to_markdown(metrics) if not metrics.empty else "_No validation metrics: readiness failed._"
        output = self.device_dir / "report" / "summary.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            f"# {self.context.equipment_type}/{self.context.device['id']}\n\n"
            f"Status: `{status.value}`\n\n"
            "This fixture validates orchestration only. The `passthrough` candidate is not a real equipment model.\n\n"
            + body
            + "\n",
            encoding="utf-8",
        )
