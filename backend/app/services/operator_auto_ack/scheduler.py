"""Periodic shadow-mode auto-ack evaluation (observe + audit only).

Mirrors IntegrationHealthScheduler: in-process asyncio loop, gated by
OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED. Prefer this over a new always-on worker.

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
from app.services.operator_auto_ack.constants import INTERVAL_SECONDS
from app.services.operator_auto_ack.shadow import OperatorAutoAckShadowService

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_cycle = 0
_cycle_lock: asyncio.Lock | None = None
_cycle_running = False


def _get_cycle_lock() -> asyncio.Lock:
    global _cycle_lock
    if _cycle_lock is None:
        _cycle_lock = asyncio.Lock()
    return _cycle_lock


class OperatorAutoAckShadowScheduler:
    @classmethod
    async def start(cls) -> None:
        global _task
        if not settings.OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED:
            logger.info(
                "[AutoAckShadow] scheduler disabled "
                "(OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED=false)"
            )
            return
        if _task and not _task.done():
            return
        _task = asyncio.create_task(cls._run_loop())
        logger.info(
            "[AutoAckShadow] scheduler started (interval=%ss)",
            INTERVAL_SECONDS,
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
        logger.info("[AutoAckShadow] scheduler stopped")

    @classmethod
    async def _run_loop(cls) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                await cls.run_once()
            except Exception:
                logger.exception("[AutoAckShadow] cycle failed")
            await asyncio.sleep(INTERVAL_SECONDS)

    @classmethod
    async def run_once(cls) -> dict[str, Any]:
        """Run one cycle; skip if a prior cycle is still in progress (no overlap)."""
        global _cycle, _cycle_running
        lock = _get_cycle_lock()
        if lock.locked() or _cycle_running:
            logger.warning("[AutoAckShadow] skipping overlapping cycle")
            return {"skipped": True, "reason": "overlap"}

        async with lock:
            _cycle_running = True
            try:
                _cycle += 1
                cycle_num = _cycle
                started_at = datetime.now(timezone.utc)
                async with session_scope() as db:
                    summary = await OperatorAutoAckShadowService.run_cycle(db)
                completed_at = datetime.now(timezone.utc)
                try:
                    async with session_scope() as db:
                        await OperatorAutoAckShadowService.audit_scheduler_cycle(
                            db,
                            cycle=cycle_num,
                            started_at=started_at,
                            completed_at=completed_at,
                            totals=summary,
                        )
                except Exception:
                    logger.warning(
                        "[AutoAckShadow] scheduler audit failed cycle=%s",
                        cycle_num,
                        exc_info=True,
                    )
                logger.info(
                    "[AutoAckShadow] cycle=%s evaluated=%s eligible=%s "
                    "would_ack=%s deduped=%s errors=%s",
                    cycle_num,
                    summary.get("evaluated"),
                    summary.get("eligible"),
                    summary.get("would_acknowledge"),
                    summary.get("deduped"),
                    summary.get("errors"),
                )
                return {**summary, "cycle": cycle_num}
            finally:
                _cycle_running = False
