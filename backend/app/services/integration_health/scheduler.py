"""Periodic integration health checks (read-only provider probes).

Mirrors HealthSnapshotService lifecycle: in-process asyncio loop, gated by
INTEGRATION_HEALTH_CHECK_ENABLED. Prefer this over a new always-on worker.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.core.database import session_scope
from app.services.integration_health.service import IntegrationHealthService

logger = logging.getLogger(__name__)

# Conservative cadence: local eval often; remote Meta probes on the same cycle
# but bounded concurrency + per-account locks prevent stampeding.
INTERVAL_SECONDS = 30 * 60  # 30 minutes
_REMOTE_EVERY_N_CYCLES = 2  # remote Meta probes every ~60 minutes

_task: asyncio.Task | None = None
_cycle = 0


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
            "[IntegrationHealth] scheduler started (interval=%ss)", INTERVAL_SECONDS
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
        global _cycle
        await asyncio.sleep(15)
        while True:
            try:
                await cls.run_once()
            except Exception:
                logger.exception("[IntegrationHealth] cycle failed")
            await asyncio.sleep(INTERVAL_SECONDS)

    @classmethod
    async def run_once(cls) -> dict[str, Any]:
        global _cycle
        _cycle += 1
        live_remote = (_cycle % _REMOTE_EVERY_N_CYCLES) == 0
        async with session_scope() as db:
            summary = await IntegrationHealthService.run_periodic_cycle(
                db, live_remote=live_remote
            )
        logger.info(
            "[IntegrationHealth] cycle=%s live_remote=%s tenants=%s checked=%s errors=%s",
            _cycle,
            live_remote,
            summary.get("tenants"),
            summary.get("checked"),
            summary.get("errors"),
        )
        return summary
