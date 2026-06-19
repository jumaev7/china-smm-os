"""Per-request SQL query profiling (read-only diagnostics)."""
from __future__ import annotations

import logging
import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SLOWEST = 50
_lock = Lock()

_current_key: ContextVar[str | None] = ContextVar("query_profiler_key", default=None)
_query_count: ContextVar[int] = ContextVar("query_profiler_count", default=0)
_query_ms: ContextVar[float] = ContextVar("query_profiler_ms", default=0.0)
_cursor_start: ContextVar[float | None] = ContextVar("query_profiler_cursor_start", default=None)


@dataclass
class EndpointQueryStats:
    endpoint: str
    call_count: int = 0
    total_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    total_query_count: int = 0

    @property
    def avg_duration_ms(self) -> float:
        if self.call_count <= 0:
            return 0.0
        return self.total_duration_ms / self.call_count


_endpoint_stats: dict[str, EndpointQueryStats] = {}
_slowest: deque[dict[str, Any]] = deque(maxlen=_MAX_SLOWEST)


def _stats_key(method: str, path: str) -> str:
    return f"{method} {path}"


def begin_request(method: str, path: str) -> None:
    _current_key.set(_stats_key(method, path))
    _query_count.set(0)
    _query_ms.set(0.0)


def end_request(method: str, path: str, request_duration_ms: int) -> None:
    key = _stats_key(method, path)
    q_count = _query_count.get()
    q_ms = _query_ms.get()

    with _lock:
        stats = _endpoint_stats.get(key)
        if stats is None:
            stats = EndpointQueryStats(endpoint=key)
            _endpoint_stats[key] = stats
        stats.call_count += 1
        stats.total_duration_ms += request_duration_ms
        stats.max_duration_ms = max(stats.max_duration_ms, float(request_duration_ms))
        stats.total_query_count += q_count

        entry = {
            "endpoint": key,
            "duration_ms": request_duration_ms,
            "query_count": q_count,
            "query_duration_ms": int(q_ms),
        }
        _insert_slowest(entry)

    _current_key.set(None)
    _query_count.set(0)
    _query_ms.set(0.0)


def _insert_slowest(entry: dict[str, Any]) -> None:
    merged = list(_slowest) + [entry]
    merged.sort(key=lambda x: x["duration_ms"], reverse=True)
    _slowest.clear()
    for item in merged[:_MAX_SLOWEST]:
        _slowest.append(item)


def on_before_cursor_execute() -> None:
    if _current_key.get() is None:
        return
    _cursor_start.set(time.perf_counter())


def on_after_cursor_execute() -> None:
    if _current_key.get() is None:
        return
    start = _cursor_start.get()
    if start is None:
        return
    elapsed_ms = (time.perf_counter() - start) * 1000
    _query_count.set(_query_count.get() + 1)
    _query_ms.set(_query_ms.get() + elapsed_ms)
    _cursor_start.set(None)


def query_health_summary(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        rows = sorted(
            _endpoint_stats.values(),
            key=lambda s: s.avg_duration_ms,
            reverse=True,
        )[:limit]
        return [
            {
                "endpoint": s.endpoint,
                "avg_duration_ms": round(s.avg_duration_ms, 1),
                "max_duration_ms": round(s.max_duration_ms, 1),
                "call_count": s.call_count,
                "avg_query_count": round(s.total_query_count / s.call_count, 1) if s.call_count else 0,
            }
            for s in rows
        ]


def slowest_requests(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        return list(_slowest)[:limit]
