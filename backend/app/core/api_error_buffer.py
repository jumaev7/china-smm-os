"""In-memory ring buffers for API errors and slow requests (diagnostics only)."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.error_classifier import ErrorCategory, classify_error

_MAX_ENTRIES = 100
_SLOW_THRESHOLD_MS = 1000
SLOW_THRESHOLD_MS = _SLOW_THRESHOLD_MS

_errors: deque[dict[str, Any]] = deque(maxlen=_MAX_ENTRIES)
_slow: deque[dict[str, Any]] = deque(maxlen=_MAX_ENTRIES)
_category_counts: Counter[str] = Counter()


@dataclass(frozen=True)
class ApiRequestRecord:
    timestamp: str
    method: str
    path: str
    status: int
    duration_ms: int
    error_summary: str | None = None
    category: ErrorCategory = "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_request(
    *,
    method: str,
    path: str,
    status: int,
    duration_ms: int,
    error_summary: str | None = None,
) -> None:
    category = classify_error(
        method=method,
        path=path,
        status=status,
        error_summary=error_summary,
    )
    record = ApiRequestRecord(
        timestamp=_now_iso(),
        method=method,
        path=path,
        status=status,
        duration_ms=duration_ms,
        error_summary=error_summary,
        category=category,
    )
    payload = asdict(record)

    if status >= 500:
        _errors.appendleft(payload)
        _category_counts[category] += 1
    if duration_ms > _SLOW_THRESHOLD_MS:
        slow_payload = {**payload, "category": category if status >= 500 else "api_error"}
        _slow.appendleft(slow_payload)


def recent_errors(limit: int = 100) -> list[dict[str, Any]]:
    return list(_errors)[:limit]


def recent_slow(limit: int = 100) -> list[dict[str, Any]]:
    return list(_slow)[:limit]


def error_counts_by_category() -> dict[str, int]:
    return dict(_category_counts)
