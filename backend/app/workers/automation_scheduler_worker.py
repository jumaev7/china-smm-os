"""Durable automation scheduler worker loop (PostgreSQL-backed)."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import uuid
from typing import Any

from app.core.config import settings
from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
from app.services.automation_scheduler_service import AutomationSchedulerService

logger = logging.getLogger(__name__)


def build_worker_id() -> str:
    host = socket.gethostname()[:40]
    return f"aw-{host}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


class AutomationSchedulerWorker:
    """Poll/claim/process durable automation jobs until stopped."""

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        poll_seconds: float | None = None,
        batch_size: int | None = None,
        lease_seconds: int | None = None,
    ) -> None:
        self.worker_id = worker_id or build_worker_id()
        self.poll_seconds = float(
            poll_seconds
            if poll_seconds is not None
            else settings.AUTOMATION_SCHEDULER_POLL_SECONDS
        )
        self.batch_size = int(
            batch_size if batch_size is not None else settings.AUTOMATION_SCHEDULER_BATCH_SIZE
        )
        self.lease_seconds = int(
            lease_seconds
            if lease_seconds is not None
            else settings.AUTOMATION_SCHEDULER_LEASE_SECONDS
        )
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        logger.info(
            "[AutomationWorker] started id=%s poll=%ss batch=%s lease=%ss",
            self.worker_id,
            self.poll_seconds,
            self.batch_size,
            self.lease_seconds,
        )
        await ensure_platform_event_bus_schema()
        while not self._stop.is_set():
            try:
                summary = await self.run_once()
            except Exception:
                logger.exception("[AutomationWorker] tick failed id=%s", self.worker_id)
                summary = {"claimed": 0, "processed": 0}
            claimed = int(summary.get("claimed") or 0)
            if claimed == 0:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                except asyncio.TimeoutError:
                    pass
            # When work existed, loop immediately to drain backlog.
        logger.info("[AutomationWorker] stopped id=%s", self.worker_id)

    async def run_once(self) -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            claimed_ids, recovery = await AutomationSchedulerService.claim_batch(
                db,
                worker_id=self.worker_id,
                batch_size=self.batch_size,
                lease_seconds=self.lease_seconds,
            )
            await db.commit()

        processed = 0
        succeeded = 0
        failed = 0
        for job_id in claimed_ids:
            if self._stop.is_set():
                break
            async with AsyncSessionLocal() as db:
                outcome = await AutomationSchedulerService.process_job(
                    db,
                    job_id=job_id,
                    worker_id=self.worker_id,
                )
                await db.commit()
            processed += 1
            if outcome.status == "succeeded":
                succeeded += 1
            elif outcome.status in {"failed", "dead_letter"}:
                failed += 1

        summary = {
            "claimed": len(claimed_ids),
            "processed": processed,
            "succeeded": succeeded,
            "failed": failed,
            "recovery": recovery,
        }
        if claimed_ids or recovery.get("recovered") or recovery.get("dead_lettered"):
            logger.info(
                "[AutomationWorker] tick id=%s claimed=%s processed=%s ok=%s fail=%s recovery=%s",
                self.worker_id,
                summary["claimed"],
                summary["processed"],
                summary["succeeded"],
                summary["failed"],
                recovery,
            )
        return summary


async def amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not settings.AUTOMATION_SCHEDULER_ENABLED:
        logger.warning("[AutomationWorker] AUTOMATION_SCHEDULER_ENABLED=false — exiting")
        return

    worker = AutomationSchedulerWorker()
    loop = asyncio.get_running_loop()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("[AutomationWorker] signal %s — shutting down", sig.name)
        worker.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except NotImplementedError:
            # Windows: signal handlers limited.
            signal.signal(sig, lambda *_: worker.request_stop())

    await worker.run_forever()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
