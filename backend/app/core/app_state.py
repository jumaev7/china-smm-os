"""Application runtime state (uptime tracking)."""
from __future__ import annotations

from datetime import datetime, timezone

_app_started_at: datetime | None = None


def mark_app_started() -> None:
    global _app_started_at
    _app_started_at = datetime.now(timezone.utc)


def uptime_seconds() -> float:
    if _app_started_at is None:
        return 0.0
    return (datetime.now(timezone.utc) - _app_started_at).total_seconds()
