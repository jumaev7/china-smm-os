"""Periodic in-memory health snapshots (48h retention, read-only)."""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.api_error_buffer import error_counts_by_category, recent_errors, recent_slow
from app.core.database import session_scope
from app.services.api_health_service import ApiHealthService
from app.services.schema_health_service import SchemaHealthService

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 15 * 60
RETENTION_HOURS = 48

_snapshots: deque[dict[str, Any]] = deque()
_task: asyncio.Task | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _prune() -> None:
    cutoff = _now() - timedelta(hours=RETENTION_HOURS)
    while _snapshots and datetime.fromisoformat(_snapshots[0]["timestamp"]) < cutoff:
        _snapshots.popleft()


_SNAPSHOT_API_BUDGET_SEC = 45.0
_SNAPSHOT_PROBE_TIMEOUT_SEC = 1.5
_SNAPSHOT_SKIP = frozenset({
    "production_deployment",
    "executive_copilot",
    "pilot_demo",
    "pilot_launch",
    "pilot_launch_validation",
    "real_factory_pilot",
})


async def capture_snapshot() -> dict[str, Any]:
    async with session_scope() as db:
        schema = await SchemaHealthService.check(db)
    api = await ApiHealthService.check(
        None,
        skip_paths=_SNAPSHOT_SKIP,
        time_budget_sec=_SNAPSHOT_API_BUDGET_SEC,
        per_probe_timeout_sec=_SNAPSHOT_PROBE_TIMEOUT_SEC,
    )

    errors = recent_errors(limit=100)
    slow = recent_slow(limit=100)
    categories = error_counts_by_category()

    snapshot = {
        "timestamp": _now().isoformat(),
        "schema_ok": schema.get("ok", False),
        "migration_drift": schema.get("migration_drift", False),
        "missing_tables_count": len(schema.get("missing_tables") or []),
        "missing_columns_count": len(schema.get("missing_columns") or []),
        "api_ok_count": api.get("ok_count", 0),
        "api_total": api.get("total", 0),
        "error_count_5xx": len(errors),
        "slow_count": len(slow),
        "error_categories": categories,
        "broken_endpoints": [
            ep["name"] for ep in (api.get("endpoints") or [])
            if ep.get("status") == "error"
        ],
    }
    _snapshots.append(snapshot)
    _prune()
    logger.info(
        "[Health Snapshot] schema_ok=%s api=%s/%s errors=%s slow=%s",
        snapshot["schema_ok"],
        snapshot["api_ok_count"],
        snapshot["api_total"],
        snapshot["error_count_5xx"],
        snapshot["slow_count"],
    )
    return snapshot


def list_snapshots(limit: int = 200) -> list[dict[str, Any]]:
    _prune()
    return list(_snapshots)[-limit:]


class HealthSnapshotService:
    @classmethod
    async def start(cls) -> None:
        global _task
        if _task and not _task.done():
            return
        _task = asyncio.create_task(cls._run_loop())
        logger.info("[Health Snapshot] scheduler started (interval=%ss)", INTERVAL_SECONDS)

    @classmethod
    async def stop(cls) -> None:
        global _task
        if not _task:
            return
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
        logger.info("[Health Snapshot] scheduler stopped")

    @classmethod
    async def _run_loop(cls) -> None:
        await asyncio.sleep(5)
        while True:
            try:
                await capture_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[Health Snapshot] capture failed")
            await asyncio.sleep(INTERVAL_SECONDS)
