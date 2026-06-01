from __future__ import annotations

import subprocess
from pathlib import Path


FORBIDDEN_CORE_TEXT = ("Site" + "_A", "CT" + "_Model", "Cali_EIR" + "_BSU_CH1")


def scan_hygiene(root: Path) -> list[str]:
    root = Path(root).resolve()
    errors = []
    source = root / "src" / "auto_fmu"
    if source.exists():
        for path in source.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_CORE_TEXT:
                if pattern in text:
                    errors.append(f"{path}: contains fixed archive path token {pattern}")
    try:
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
    except (FileNotFoundError, subprocess.CalledProcessError):
        tracked = []
    for relative in tracked:
        normalized = relative.replace("\\", "/")
        if normalized.lower().endswith(".fmu"):
            errors.append(f"{relative}: tracked FMU artifact")
        if normalized.startswith("outputs/"):
            errors.append(f"{relative}: tracked generated output")
    return errors
