from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from auto_fmu.cli import main


def write_generic_project(tmp_path: Path) -> Path:
    data_dir = tmp_path / "fixture"
    data_dir.mkdir()
    equipment = {
        "chiller": ("CHILLER_NORTH_01", "power_W"),
        "cooling_tower": ("TOWER_WEST_01", "Q_W"),
        "pump": ("PUMP_CONDENSER_A", "power_W"),
        "heat_exchanger": ("HX_PRIMARY_01", "Q_W"),
    }
    config = {"outputs_dir": "outputs", "equipment": {}}
    for kind, (equipment_id, metric) in equipment.items():
        csv_path = data_dir / f"{kind}.csv"
        pd.DataFrame({"timestamp": ["2024-01-01 00:00", "2024-01-01 00:05"], metric: [1.0, 2.0]}).to_csv(
            csv_path, index=False
        )
        config["equipment"][kind] = [
            {
                "id": equipment_id,
                "source_csv": str(csv_path.relative_to(tmp_path)),
                "metric": metric,
                "candidates": ["passthrough"],
            }
        ]
    config_path = tmp_path / "project.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def test_generic_four_stage_cli_writes_manifest_and_reports(tmp_path: Path) -> None:
    config = write_generic_project(tmp_path)

    assert main(["validate-config", "--config", str(config)]) == 0
    for command in ("prepare", "calibrate", "validate", "report"):
        assert main([command, "--config", str(config), "--equipment", "all", "--run-id", "generic-smoke"]) == 0

    run_dir = tmp_path / "outputs" / "runs" / "generic-smoke"
    assert (run_dir / "manifest.json").exists()
    for kind in ("chiller", "cooling_tower", "pump", "heat_exchanger"):
        assert (run_dir / kind / "report" / "summary.md").exists()


def test_regression_cli_writes_comparison_and_blocked_rows(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.csv"
    current = tmp_path / "current.csv"
    pd.DataFrame(
        [{"equipment_id": "CDWP_03", "candidate": "affinity_y3", "variable": "CVRMSE", "value": 3.0}]
    ).to_csv(baseline, index=False)
    pd.DataFrame(
        [{"equipment_id": "CDWP_03", "candidate": "affinity_y3", "variable": "CVRMSE", "value": 3.0005}]
    ).to_csv(current, index=False)
    config = tmp_path / "regression.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "project_root": ".",
                "outputs_dir": "outputs",
                "tolerance": 0.001,
                "cases": [
                    {"equipment": "pump", "baseline_csv": "baseline.csv", "new_csv": "current.csv"},
                    {"equipment": "chiller", "baseline_csv": "missing-baseline.csv", "new_csv": "missing-current.csv"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert main(["regression", "--config", str(config), "--equipment", "all", "--run-id", "regression-smoke"]) == 0

    regression_dir = tmp_path / "outputs" / "runs" / "regression-smoke" / "regression"
    pump = pd.read_csv(regression_dir / "pump.csv")
    chiller = pd.read_csv(regression_dir / "chiller.csv")
    assert pump["status"].tolist() == ["pass"]
    assert chiller["status"].tolist() == ["blocked"]


def test_regression_cli_normalizes_legacy_pump_metrics(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.csv"
    current = tmp_path / "current.csv"
    pd.DataFrame([{"pump": "CDWP_03", "family": "affinity_y3", "full_cvrmse_pct": 3.0}]).to_csv(baseline, index=False)
    pd.DataFrame([{"equipment_id": "CDWP_03", "candidate": "affinity_y3", "variable": "full_cvrmse_pct", "value": 3.0005}]).to_csv(
        current, index=False
    )
    config = tmp_path / "regression.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "outputs_dir": "outputs",
                "cases": [
                    {
                        "equipment": "pump",
                        "equipment_id": "CDWP_03",
                        "candidate": "affinity_y3",
                        "variable": "full_cvrmse_pct",
                        "baseline_csv": "baseline.csv",
                        "new_csv": "current.csv",
                        "normalizer": "pump_legacy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["regression", "--config", str(config), "--equipment", "pump", "--run-id", "regression"]) == 0
    compared = pd.read_csv(tmp_path / "outputs" / "runs" / "regression" / "regression" / "pump.csv")
    assert compared["status"].tolist() == ["pass"]


def test_scan_hygiene_rejects_fixed_archive_paths_in_core(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auto_fmu"
    source.mkdir(parents=True)
    (source / "bad.py").write_text('PATH = "CT_Model/DATA/Site_A"\n', encoding="utf-8")

    assert main(["scan-hygiene", "--root", str(tmp_path)]) == 1


def test_scan_hygiene_rejects_public_absolute_paths_but_allows_local_yaml(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    configs = tmp_path / "configs"
    docs.mkdir()
    configs.mkdir()
    (docs / "bad.md").write_text("archive: E:/private/archive\n", encoding="utf-8")
    (configs / "project.local.yaml").write_text("outputs_dir: outputs\n", encoding="utf-8")

    assert main(["scan-hygiene", "--root", str(tmp_path)]) == 1


def test_scan_hygiene_allows_ignored_local_yaml_content(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "project.local.yaml").write_text("archive: E:/private/archive\n", encoding="utf-8")

    assert main(["scan-hygiene", "--root", str(tmp_path)]) == 0
