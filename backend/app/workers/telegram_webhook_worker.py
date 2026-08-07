"""Worker for durable Telegram webhook events."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import uuid

from app.core.database import AsyncSessionLocal
from app.services.telegram_service import process_update
from app.services.telegram_webhook_queue_service import TelegramWebhookQueueService

logger = logging.getLogger(__name__)


class TelegramWebhookWorker:
    def __init__(self) -> None:
        self.worker_id = f"tgw-{socket.gethostname()[:32]}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.poll_seconds = float(os.getenv("TELEGRAM_WEBHOOK_WORKER_POLL_SECONDS", "0.5"))
        self.batch_size = int(os.getenv("TELEGRAM_WEBHOOK_WORKER_BATCH_SIZE", "5"))
        self.lease_seconds = int(os.getenv("TELEGRAM_WEBHOOK_WORKER_LEASE_SECONDS", "180"))
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run_once(self) -> dict[str, int]:
        async with AsyncSessionLocal() as db:
            claimed = await TelegramWebhookQueueService.claim_batch(
                db,
                worker_id=self.worker_id,
                batch_size=self.batch_size,
                lease_seconds=self.lease_seconds,
            )
            await db.commit()

        completed = failed = 0
        for event_id, payload in claimed:
            try:
                async with AsyncSessionLocal() as db:
                    await process_update(db, payload)
                    await TelegramWebhookQueueService.mark_completed(
                        db, event_id, worker_id=self.worker_id,
                    )
                    await db.commit()
                completed += 1
            except Exception as exc:
                logger.exception("[TelegramWebhookWorker] processing failed event=%s", event_id)
                async with AsyncSessionLocal() as db:
                    await TelegramWebhookQueueService.mark_failed(
                        db, event_id, worker_id=self.worker_id, error=exc,
                    )
                    await db.commit()
                failed += 1
        return {"claimed": len(claimed), "completed": completed, "failed": failed}

    async def run_forever(self) -> None:
        logger.info("[TelegramWebhookWorker] started id=%s", self.worker_id)
        while not self._stop.is_set():
            summary = await self.run_once()
            if summary["claimed"]:
                logger.info("[TelegramWebhookWorker] tick %s", summary)
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
        logger.info("[TelegramWebhookWorker] stopped id=%s", self.worker_id)


async def amain() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    worker = TelegramWebhookWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: worker.request_stop())
    await worker.run_forever()


def main() -> None:
    asyncio.run(amain())
