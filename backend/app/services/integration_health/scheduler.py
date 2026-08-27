"""Periodic integration health checks (read-only provider probes).

Mirrors HealthSnapshotService lifecycle: in-process asyncio loop, gated by
INTEGRATION_HEALTH_CHECK_ENABLED. Prefer this over a new always-on worker.

Topology assumption: single production ``backend`` uvicorn process owns this
scheduler. Worker containers do not import FastAPI lifespan. In-process locks
are sufficient for that topology; do not scale backend replicas without adding
a durable lease/advisory lock first.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.database import session_scope
from app.services.integration_health.service import IntegrationHealthService

logger = logging.getLogger(__name__)

# Conservative cadence: local eval often; remote Meta probes less frequently.
# Recommended first production activation: local ~30m, remote ~120m (every 4th cycle).
INTERVAL_SECONDS = 30 * 60  # 30 minutes
_REMOTE_EVERY_N_CYCLES = 4  # remote Meta probes every ~120 minutes when remote enabled

_task: asyncio.Task | None = None
_cycle = 0
_cycle_lock: asyncio.Lock | None = None
_cycle_running = False


def _get_cycle_lock() -> asyncio.Lock:
    global _cycle_lock
    if _cycle_lock is None:
        _cycle_lock = asyncio.Lock()
    return _cycle_lock


class IntegrationHealthScheduler:
    @classmethod
    async def start(cls) -> None:
        global _task
        if not settings.INTEGRATION_HEALTH_CHECK_ENABLED:
            logger.info(
                "[IntegrationHealth] scheduler disabled "
                "(INTEGRATION_HEALTH_CHECK_ENABLED=false)"
            )
            return
        if _task and not _task.done():
            return
        _task = asyncio.create_task(cls._run_loop())
        logger.info(
            "[IntegrationHealth] scheduler started (interval=%ss remote=%s)",
            INTERVAL_SECONDS,
            settings.INTEGRATION_HEALTH_REMOTE_CHECK_ENABLED,
        )

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
        logger.info("[IntegrationHealth] scheduler stopped")

    @classmethod
    async def _run_loop(cls) -> None:
        await asyncio.sleep(15)
        while True:
            try:
                await cls.run_once()
            except Exception:
                logger.exception("[IntegrationHealth] cycle failed")
            await asyncio.sleep(INTERVAL_SECONDS)

    @classmethod
    async def run_once(cls) -> dict[str, Any]:
        """Run one cycle; skip if a prior cycle is still in progress (no overlap)."""
        global _cycle, _cycle_running
        lock = _get_cycle_lock()
        if lock.locked() or _cycle_running:
            logger.warning("[IntegrationHealth] skipping overlapping cycle")
            return {"skipped": True, "reason": "overlap"}

        async with lock:
            _cycle_running = True
            try:
                _cycle += 1
                cycle_num = _cycle
                remote_allowed = bool(settings.INTEGRATION_HEALTH_REMOTE_CHECK_ENABLED)
                live_remote = remote_allowed and (cycle_num % _REMOTE_EVERY_N_CYCLES) == 0
                started_at = datetime.now(timezone.utc)
                async with session_scope() as db:
                    summary = await IntegrationHealthService.run_periodic_cycle(
                        db, live_remote=live_remote
                    )
                completed_at = datetime.now(timezone.utc)
                try:
                    async with session_scope() as db:
                        await IntegrationHealthService.audit_scheduler_cycle(
                            db,
                            cycle=cycle_num,
                            live_remote=live_remote,
                            remote_enabled=remote_allowed,
                            started_at=started_at,
                            completed_at=completed_at,
                            totals=summary,
                        )
                except Exception:
                    logger.warning(
                        "[IntegrationHealth] scheduler audit failed cycle=%s",
                        cycle_num,
                        exc_info=True,
                    )
                logger.info(
                    "[IntegrationHealth] cycle=%s live_remote=%s remote_enabled=%s "
                    "tenants=%s checked=%s errors=%s",
                    cycle_num,
                    live_remote,
                    remote_allowed,
                    summary.get("tenants"),
                    summary.get("checked"),
                    summary.get("errors"),
                )
                return {
                    **summary,
                    "cycle": cycle_num,
                    "live_remote": live_remote,
                    "remote_enabled": remote_allowed,
                }
            finally:
                _cycle_running = False
