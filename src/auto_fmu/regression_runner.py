from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from auto_fmu.regression import compare_metric_rows
from auto_fmu.reporting import table_to_markdown


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _normalize_pump_legacy(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        {
            "equipment_id": row["pump"],
            "candidate": row["family"],
            "variable": "full_cvrmse_pct",
            "value": row["full_cvrmse_pct"],
        }
        for row in frame.to_dict("records")
    ]


def _select_case(rows: list[dict[str, object]], case: dict[str, Any]) -> list[dict[str, object]]:
    keys = ("equipment_id", "candidate", "variable")
    return [row for row in rows if all(not case.get(key) or row.get(key) == case[key] for key in keys)]


def run_regression(config_path: Path, equipment: str, run_id: str) -> Path:
    config_path = Path(config_path).resolve()
    config: dict[str, Any] = yaml.safe_load(os.path.expandvars(config_path.read_text(encoding="utf-8"))) or {}
    project_root = _resolve(config_path.parent, config.get("project_root", "."))
    output_dir = project_root / config.get("outputs_dir", "outputs") / "runs" / run_id / "regression"
    output_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, list[dict[str, object]]] = {}
    for case in config.get("cases", []):
        equipment_type = case["equipment"]
        if equipment != "all" and equipment_type != equipment:
            continue
        baseline = _resolve(project_root, case["baseline_csv"])
        current = _resolve(project_root, case["new_csv"])
        if not baseline.exists() or not current.exists():
            tables.setdefault(equipment_type, []).append(
                {
                    "equipment_id": case.get("equipment_id", ""),
                    "candidate": case.get("candidate", ""),
                    "variable": case.get("variable", ""),
                    "status": "blocked",
                    "reason": "missing baseline CSV" if not baseline.exists() else "missing new CSV",
                    "baseline_csv": str(baseline),
                    "new_csv": str(current),
                }
            )
            continue
        legacy_rows = pd.read_csv(baseline).to_dict("records")
        if case.get("normalizer") == "pump_legacy":
            legacy_rows = _normalize_pump_legacy(pd.read_csv(baseline))
        current_rows = pd.read_csv(current).to_dict("records")
        compared = compare_metric_rows(
            _select_case(legacy_rows, case),
            _select_case(current_rows, case),
            tolerance=float(case.get("tolerance", config.get("tolerance", 1e-3))),
        )
        tables.setdefault(equipment_type, []).extend(compared)
    summaries = []
    for equipment_type, rows in sorted(tables.items()):
        table = pd.DataFrame(rows)
        table.to_csv(output_dir / f"{equipment_type}.csv", index=False)
        summaries.append(f"## {equipment_type}\n\n{table_to_markdown(table)}")
    (output_dir / "summary.md").write_text("# Archive regression\n\n" + "\n\n".join(summaries) + "\n", encoding="utf-8")
    return output_dir
