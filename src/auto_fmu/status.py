from __future__ import annotations

from enum import Enum


class RunStatus(str, Enum):
    NOT_READY = "not_ready"
    EXPORT_FAILED = "export_failed"
    ACCEPTED = "accepted"
    HIGH_ERROR = "high_error"


def select_status(*, readiness_ok: bool, export_ok: bool, metrics_ok: bool) -> RunStatus:
    if not readiness_ok:
        return RunStatus.NOT_READY
    if not export_ok:
        return RunStatus.EXPORT_FAILED
    if metrics_ok:
        return RunStatus.ACCEPTED
    return RunStatus.HIGH_ERROR
