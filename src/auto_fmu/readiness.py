from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class ReadinessResult:
    ready: bool
    reasons: Sequence[str]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
