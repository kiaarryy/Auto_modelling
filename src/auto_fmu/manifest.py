from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class RunManifest:
    def __init__(self, path: Path, run_id: str) -> None:
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data: dict[str, Any] = {
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "stages": {},
                "artifacts": [],
                "warnings": [],
                "failed_candidates": [],
            }

    def record_stage(self, stage: str, status: str = "completed") -> None:
        self.data["stages"][stage] = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}

    def add_artifact(self, path: Path, root: Path) -> None:
        path = Path(path)
        record = {"path": str(path.resolve().relative_to(Path(root).resolve())), "sha256": sha256_file(path)}
        existing = {artifact["path"] for artifact in self.data["artifacts"]}
        if record["path"] not in existing:
            self.data["artifacts"].append(record)

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
