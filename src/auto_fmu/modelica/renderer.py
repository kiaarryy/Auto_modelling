from __future__ import annotations

from pathlib import Path
from typing import Any


def render_template(template: Path, output: Path, values: dict[str, Any]) -> Path:
    text = Path(template).read_text(encoding="utf-8")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text.format(**values), encoding="utf-8")
    return output
