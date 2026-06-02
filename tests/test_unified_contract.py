from __future__ import annotations

import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import yaml

from auto_fmu.cli import main
from auto_fmu.config import load_config
from auto_fmu.fmu.exporter import ExportMode, export_fmu
from auto_fmu.status import RunStatus, select_status


MODEL_DESCRIPTION = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="Mock" guid="mock">
  <ModelVariables>
    <ScalarVariable name="u" valueReference="1" causality="input" variability="continuous">
      <Real />
    </ScalarVariable>
    <ScalarVariable name="y" valueReference="2" causality="output" variability="continuous">
      <Real />
    </ScalarVariable>
  </ModelVariables>
</fmiModelDescription>
"""


def mock_fmu(path: Path) -> Path:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("modelDescription.xml", MODEL_DESCRIPTION)
    return path


def write_project(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    pd.DataFrame(
        {"timestamp": ["2024-01-01 00:00", "2024-01-01 00:05"], "power_W": [1000.0, 1100.0]}
    ).to_csv(fixture / "pump.csv", index=False)
    project = tmp_path / "project.yaml"
    project.write_text(
        yaml.safe_dump(
            {
                "outputs_dir": "outputs",
                "equipment": {
                    "pump": [
                        {
                            "id": "PUMP_01",
                            "source_csv": "fixture/pump.csv",
                            "metric": "power_W",
                            "candidates": ["passthrough"],
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


def test_status_priority_is_stable() -> None:
    assert select_status(readiness_ok=False, export_ok=False, metrics_ok=False) == RunStatus.NOT_READY
    assert select_status(readiness_ok=True, export_ok=False, metrics_ok=True) == RunStatus.EXPORT_FAILED
    assert select_status(readiness_ok=True, export_ok=True, metrics_ok=True) == RunStatus.ACCEPTED
    assert select_status(readiness_ok=True, export_ok=True, metrics_ok=False) == RunStatus.HIGH_ERROR


def test_load_config_supports_extends_environment_and_local_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_FMU_TEST_SOURCE", "fixture/pump.csv")
    base = tmp_path / "base.yaml"
    base.write_text(
        yaml.safe_dump(
            {
                "outputs_dir": "base-output",
                "equipment": {"pump": [{"id": "PUMP_01", "source_csv": "${AUTO_FMU_TEST_SOURCE}", "metric": "power_W"}]},
                "thresholds": {"CVRMSE_pct": 10.0, "NMBE_pct": 5.0},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    local = tmp_path / "project.local.yaml"
    local.write_text(
        yaml.safe_dump({"extends": "base.yaml", "outputs_dir": "outputs", "thresholds": {"CVRMSE_pct": 8.0}}),
        encoding="utf-8",
    )

    config = load_config(local)

    assert config["outputs_dir"] == "outputs"
    assert config["thresholds"] == {"CVRMSE_pct": 8.0, "NMBE_pct": 5.0}
    assert config["equipment"]["pump"][0]["source_csv"] == "fixture/pump.csv"


def test_external_reference_records_hash_interface_and_smoke_status(tmp_path: Path) -> None:
    source = mock_fmu(tmp_path / "source.fmu")

    result = export_fmu(
        {"mode": ExportMode.EXTERNAL_REFERENCE.value, "path": str(source)},
        output_dir=tmp_path / "fmu",
    )

    reference = json.loads((tmp_path / "fmu" / "external_fmu_reference.json").read_text(encoding="utf-8"))
    assert result.ok
    assert reference["mode"] == ExportMode.EXTERNAL_REFERENCE.value
    assert len(reference["sha256"]) == 64
    assert reference["interface"]["inputs"] == ["u"]
    assert reference["interface"]["outputs"] == ["y"]
    assert reference["smoke"]["status"] == "not_run"
    assert not (tmp_path / "fmu" / "exported_model.fmu").exists()


def test_render_and_export_collects_dymola_fmu_written_next_to_model(tmp_path: Path, monkeypatch) -> None:
    dymola = tmp_path / "Dymola.exe"
    dymola.write_text("", encoding="utf-8")
    model = tmp_path / "modelica" / "generated_model.mo"
    model.parent.mkdir()
    model.write_text("model Mock\nend Mock;\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        mock_fmu(model.parent / "Mock.fmu")
        return subprocess.CompletedProcess(args[0], 0, "translated", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = export_fmu(
        {"mode": ExportMode.RENDER_AND_EXPORT.value, "dymola_exe": str(dymola), "model_name": "Mock"},
        output_dir=tmp_path / "fmu",
        rendered_model=model,
    )

    assert result.ok
    assert result.artifact == tmp_path / "fmu" / "exported_model.fmu"
    assert result.artifact.exists()
    assert (tmp_path / "fmu" / "export_fmu.log").read_text(encoding="utf-8") == "returncode=0\nSTDOUT:\ntranslated\nSTDERR:\n\n"


def test_run_and_batch_write_per_device_contract(tmp_path: Path) -> None:
    project = write_project(tmp_path)

    assert main(["run", "--config", str(project), "--equipment", "pump", "--equipment-id", "PUMP_01", "--run-id", "single"]) == 0
    assert main(["batch", "--config", str(project), "--equipment", "all", "--run-id", "batch"]) == 0

    for run_id in ("single", "batch"):
        device_dir = tmp_path / "outputs" / "runs" / run_id / "pump" / "PUMP_01"
        assert (device_dir / "prepare" / "canonical.csv").exists()
        assert (device_dir / "prepare" / "adapter_qa.csv").exists()
        assert (device_dir / "readiness.json").exists()
        assert (device_dir / "calibrate" / "all_candidate_metrics.csv").exists()
        assert (device_dir / "calibrate" / "parameters.csv").exists()
        assert (device_dir / "selected_model.json").exists()
        assert (device_dir / "validate" / "full_period_metrics.csv").exists()
        assert (device_dir / "validate" / "time_series.csv").exists()
        assert (device_dir / "report" / "summary.md").exists()
        manifest = json.loads((device_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["status"] == RunStatus.ACCEPTED.value

    summary = pd.read_csv(tmp_path / "outputs" / "runs" / "batch" / "batch_summary.csv")
    assert summary[["equipment_type", "equipment_id", "status"]].to_dict("records") == [
        {"equipment_type": "pump", "equipment_id": "PUMP_01", "status": RunStatus.ACCEPTED.value}
    ]
