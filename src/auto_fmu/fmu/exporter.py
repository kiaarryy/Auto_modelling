from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from auto_fmu.fmu.inspect import inspect_fmu
from auto_fmu.manifest import sha256_file


class ExportMode(str, Enum):
    DISABLED = "disabled"
    EXTERNAL_REFERENCE = "external_reference"
    RENDER_AND_EXPORT = "render_and_export"


@dataclass(frozen=True)
class ExportResult:
    ok: bool
    mode: ExportMode
    message: str
    artifact: Path | None = None


def _external_reference(settings: dict[str, Any], output_dir: Path) -> ExportResult:
    source = Path(str(settings.get("path", ""))).expanduser().resolve()
    if not source.is_file():
        return ExportResult(False, ExportMode.EXTERNAL_REFERENCE, f"external FMU does not exist: {source}")
    try:
        snapshot = inspect_fmu(source)
    except Exception as exc:
        return ExportResult(False, ExportMode.EXTERNAL_REFERENCE, f"external FMU inspection failed: {exc}")
    reference = {
        "mode": ExportMode.EXTERNAL_REFERENCE.value,
        "path": str(source),
        "sha256": sha256_file(source),
        "interface": {
            "inputs": list(snapshot.inputs),
            "outputs": list(snapshot.outputs),
            "tunable_parameters": list(snapshot.tunable_parameters),
            "variables": snapshot.to_dict()["variables"],
        },
        "smoke": {"status": "not_run", "reason": "no smoke inputs configured"},
    }
    target = output_dir / "external_fmu_reference.json"
    target.write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ExportResult(True, ExportMode.EXTERNAL_REFERENCE, "external FMU reference recorded", target)


def _render_and_export(settings: dict[str, Any], output_dir: Path, rendered_model: Path | None) -> ExportResult:
    if rendered_model is None or not Path(rendered_model).is_file():
        return ExportResult(False, ExportMode.RENDER_AND_EXPORT, "rendered Modelica model is required")
    dymola_exe = Path(str(settings.get("dymola_exe") or os.environ.get("DYMOLA_EXE", ""))).expanduser()
    if not dymola_exe.is_file():
        return ExportResult(False, ExportMode.RENDER_AND_EXPORT, f"Dymola executable does not exist: {dymola_exe}")
    model_name = str(settings.get("model_name", "")).strip()
    if not model_name:
        return ExportResult(False, ExportMode.RENDER_AND_EXPORT, "export.model_name is required")
    mos = output_dir / "export_fmu.mos"
    lines = []
    buildings_package = settings.get("buildings_package") or os.environ.get("BUILDINGS_PACKAGE")
    if buildings_package:
        lines.append(f'openModel("{Path(str(buildings_package)).as_posix()}");')
    lines.extend(
        [
            f'openModel("{Path(rendered_model).resolve().as_posix()}");',
            f'translateModelFMU("{model_name}", false, "", "2", "cs");',
            "exit();",
        ]
    )
    mos.write_text("\n".join(lines) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [str(dymola_exe), "/nowindow", str(mos)],
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    (output_dir / "export_fmu.log").write_text(
        f"returncode={completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}\n",
        encoding="utf-8",
    )
    candidates = [*output_dir.glob("*.fmu"), *Path(rendered_model).parent.glob("*.fmu")]
    exported = next(iter(candidates), None)
    if completed.returncode != 0 or exported is None:
        return ExportResult(False, ExportMode.RENDER_AND_EXPORT, f"Dymola export failed with code {completed.returncode}")
    target = output_dir / "exported_model.fmu"
    if exported != target:
        shutil.move(str(exported), str(target))
    return ExportResult(True, ExportMode.RENDER_AND_EXPORT, "FMU exported", target)


def export_fmu(settings: dict[str, Any] | None, *, output_dir: Path, rendered_model: Path | None = None) -> ExportResult:
    settings = settings or {}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    mode = ExportMode(settings.get("mode", ExportMode.DISABLED.value))
    if mode == ExportMode.DISABLED:
        return ExportResult(True, mode, "FMU export disabled")
    if mode == ExportMode.EXTERNAL_REFERENCE:
        return _external_reference(settings, output_dir)
    return _render_and_export(settings, output_dir, rendered_model)
