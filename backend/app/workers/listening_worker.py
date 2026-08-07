"""Durable Social Listening webhook and reconciliation worker."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from uuid import uuid4

from app.core.config import settings
from app.core.database import AsyncSessionLocal, ensure_listening_schema
from app.services.listening.live_sync_service import run_scheduled_live_sync_batch
from app.services.listening.webhook_service import process_due_events

logger = logging.getLogger(__name__)


class ListeningWorker:
    def __init__(self) -> None:
        self.worker_id = f"lw-{socket.gethostname()[:30]}-{os.getpid()}-{uuid4().hex[:8]}"
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run_once(self) -> dict[str, int]:
        async with AsyncSessionLocal() as db:
            events = await process_due_events(db, limit=settings.LISTENING_WORKER_BATCH_SIZE)
        async with AsyncSessionLocal() as db:
            syncs = await run_scheduled_live_sync_batch(
                db, worker_id=self.worker_id, limit=settings.LISTENING_WORKER_BATCH_SIZE,
            )
        return {"webhook_events": len(events), "reconciliation_syncs": len(syncs)}

    async def run_forever(self) -> None:
        await ensure_listening_schema()
        logger.info("[ListeningWorker] started id=%s", self.worker_id)
        while not self._stop.is_set():
            try:
                summary = await self.run_once()
                if any(summary.values()):
                    logger.info("[ListeningWorker] tick id=%s summary=%s", self.worker_id, summary)
            except Exception:  # noqa: BLE001
                logger.exception("[ListeningWorker] tick failed id=%s", self.worker_id)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(1.0, settings.LISTENING_WORKER_POLL_SECONDS))
            except asyncio.TimeoutError:
                pass


async def amain() -> None:
    if not settings.LISTENING_WORKER_ENABLED:
        logger.warning("[ListeningWorker] LISTENING_WORKER_ENABLED=false; exiting")
        return
    worker = ListeningWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: worker.request_stop())
    await worker.run_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(amain())
