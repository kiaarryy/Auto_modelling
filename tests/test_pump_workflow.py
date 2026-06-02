from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from auto_fmu.cli import main
from auto_fmu.equipment.pump import discover_columns


def write_pump_project(tmp_path: Path, *, equipment_id: str = "CDWP_03", flow_values: list[float] | None = None) -> Path:
    timestamps = pd.date_range("2024-01-01", periods=8, freq="5min").astype(str).tolist()
    frequency = [25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 30.0, 40.0]
    flow = flow_values or [10.0, 20.0, 15.0, 25.0, 12.0, 30.0, 28.0, 18.0]
    y = pd.Series(frequency) / 50.0
    phi = pd.Series(flow) / 20.0
    power = 10000.0 * (0.15 + 0.30 * phi + 0.10 * y + 0.40 * y**3 + 0.25 * phi * y)
    pd.DataFrame({"DateTime": timestamps, "P/kw": power / 1000.0, "freq": frequency}).to_csv(tmp_path / "pump.csv", index=False)
    pd.DataFrame({"DateTime": timestamps, "flow": flow}).to_csv(tmp_path / "flow.csv", index=False)
    project = tmp_path / "project.yaml"
    project.write_text(
        yaml.safe_dump(
            {
                "outputs_dir": "outputs",
                "equipment": {
                    "pump": [
                        {
                            "id": equipment_id,
                            "runner": "pump_empirical",
                            "sources": {"pump_csv": "pump.csv", "flow_csv": "flow.csv"},
                            "columns": {"timestamp": "DateTime", "power_kw": "P/kw", "frequency_hz": "freq", "flow_lps": "flow"},
                            "flow_scale": 1.0,
                            "candidates": ["affinity_y3", "speed_poly", "flow_speed_5term"],
                            "window": {"rows": 8, "stride": 1, "count": 1, "min_separation": 8},
                            "readiness": {"min_valid_rows": 2, "min_windows": 1, "hxcwp_min_flow_p95": 10.0},
                            "export": {"mode": "disabled"},
                        }
                    ]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return project


def test_pump_runner_joins_sources_and_selects_full_period_candidate(tmp_path: Path) -> None:
    project = write_pump_project(tmp_path)

    assert main(["batch", "--config", str(project), "--equipment", "pump", "--run-id", "pump"]) == 0

    device_dir = tmp_path / "outputs" / "runs" / "pump" / "pump" / "CDWP_03"
    canonical = pd.read_csv(device_dir / "prepare" / "canonical.csv")
    selected = json.loads((device_dir / "selected_model.json").read_text(encoding="utf-8"))
    metrics = pd.read_csv(device_dir / "calibrate" / "all_candidate_metrics.csv")
    manifest = json.loads((device_dir / "manifest.json").read_text(encoding="utf-8"))
    assert canonical["m_flow_kg_s"].tolist() == [10.0, 20.0, 15.0, 25.0, 12.0, 30.0, 28.0, 18.0]
    assert metrics["candidate"].tolist() == ["affinity_y3", "speed_poly", "flow_speed_5term"]
    assert selected["candidate"] == "flow_speed_5term"
    assert manifest["status"] == "accepted"
    normalized = pd.read_csv(tmp_path / "outputs" / "runs" / "pump" / "new_metrics" / "pump.csv")
    assert normalized[["equipment_id", "candidate", "variable"]].to_dict("records") == [
        {"equipment_id": "CDWP_03", "candidate": "flow_speed_5term", "variable": "full_cvrmse_pct"}
    ]


def test_hxcwp_low_mapped_flow_is_explicitly_not_ready(tmp_path: Path) -> None:
    project = write_pump_project(tmp_path, equipment_id="HXCWP_03", flow_values=[2.0] * 8)

    assert main(["batch", "--config", str(project), "--equipment", "pump", "--run-id", "pump"]) == 0

    device_dir = tmp_path / "outputs" / "runs" / "pump" / "pump" / "HXCWP_03"
    readiness = json.loads((device_dir / "readiness.json").read_text(encoding="utf-8"))
    summary = pd.read_csv(tmp_path / "outputs" / "runs" / "pump" / "batch_summary.csv")
    assert not readiness["ready"]
    assert "mapped flow p95" in " ".join(readiness["reasons"])
    assert summary.loc[0, "status"] == "not_ready"


def test_pump_column_discovery_matches_site_mapping_conventions() -> None:
    pump = pd.DataFrame(columns=["DateTime", "CDWP-1E03-VSD-CTRL.Present Value (Hz)", "CDWP-1E03-VSD-STS.Present Value (Hz)", "P/kw"])
    flow = pd.DataFrame(columns=["DateTime", "CH-1E03-CDW-WFM.Present Value (lps)", "CH-1E03-CHW-WFM.Present Value (lps)"])

    columns = discover_columns(pump, flow, {"flow_family": "CDW", "source_kind": "CH"})

    assert columns == {
        "timestamp": "DateTime",
        "power_kw": "P/kw",
        "frequency_hz": "CDWP-1E03-VSD-STS.Present Value (Hz)",
        "flow_lps": "CH-1E03-CDW-WFM.Present Value (lps)",
    }
