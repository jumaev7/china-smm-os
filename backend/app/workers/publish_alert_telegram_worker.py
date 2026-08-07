"""Worker for durable publish-operator-alert Telegram outbox deliveries."""
from __future__ import annotations

import asyncio
import logging
import signal
import socket
from uuid import uuid4

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.publish_alert_telegram_outbox_service import PublishAlertTelegramOutboxService

logger = logging.getLogger(__name__)


class PublishAlertTelegramWorker:
    def __init__(self) -> None:
        self.worker_id = f"patg-{socket.gethostname()[:28]}-{uuid4().hex[:8]}"
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run_once(self) -> dict[str, int]:
        async with AsyncSessionLocal() as db:
            claimed = await PublishAlertTelegramOutboxService.claim_batch(
                db,
                worker_id=self.worker_id,
            )
            await db.commit()

        counts = {
            "claimed": len(claimed),
            "delivered": 0,
            "retrying": 0,
            "failed": 0,
            "exhausted": 0,
            "cancelled": 0,
            "other": 0,
        }
        for row in claimed:
            try:
                async with AsyncSessionLocal() as db:
                    fresh = await db.get(type(row), row.id)
                    if fresh is None:
                        continue
                    status = await PublishAlertTelegramOutboxService.process_delivery(
                        db,
                        fresh,
                        worker_id=self.worker_id,
                    )
                    await db.commit()
                if status in counts:
                    counts[status] += 1
                else:
                    counts["other"] += 1
            except Exception:
                logger.exception(
                    "[PublishAlertTelegramWorker] process failed delivery=%s",
                    getattr(row, "id", None),
                )
                counts["other"] += 1
        return counts

    async def run_forever(self) -> None:
        logger.info(
            "[PublishAlertTelegramWorker] started id=%s poll=%s batch=%s",
            self.worker_id,
            settings.PUBLISH_ALERT_TELEGRAM_WORKER_POLL_SECONDS,
            settings.PUBLISH_ALERT_TELEGRAM_WORKER_BATCH_SIZE,
        )
        while not self._stop.is_set():
            try:
                if not settings.PUBLISH_ALERT_TELEGRAM_ENABLED:
                    # Master kill switch — idle without claiming.
                    pass
                else:
                    summary = await self.run_once()
                    if summary["claimed"]:
                        logger.info(
                            "[PublishAlertTelegramWorker] tick id=%s summary=%s",
                            self.worker_id,
                            {k: v for k, v in summary.items() if v},
                        )
            except Exception:
                logger.exception(
                    "[PublishAlertTelegramWorker] tick failed id=%s",
                    self.worker_id,
                )
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=max(1.0, float(settings.PUBLISH_ALERT_TELEGRAM_WORKER_POLL_SECONDS)),
                )
            except asyncio.TimeoutError:
                pass
        logger.info("[PublishAlertTelegramWorker] stopped id=%s", self.worker_id)


async def amain() -> None:
    if not settings.PUBLISH_ALERT_TELEGRAM_WORKER_ENABLED:
        # Idle forever when disabled so compose restart policies do not crash-loop.
        logger.warning(
            "[PublishAlertTelegramWorker] PUBLISH_ALERT_TELEGRAM_WORKER_ENABLED=false; idling",
        )
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                signal.signal(sig, lambda *_: stop.set())
        await stop.wait()
        return

    worker = PublishAlertTelegramWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: worker.request_stop())
    await worker.run_forever()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(amain())
