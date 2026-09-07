"""Publish retry-command claim worker (Phase 3C.1C-B).

Dedicated process for command ownership only. Does not execute retries,
create PublishAttempts, or call providers. Intended for compose service
``publish-retry-command-worker``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from uuid import uuid4

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.publish_retry_command_claim_service import (
    ClaimResult,
    PublishRetryCommandClaimService,
    claim_gates_open,
    scrubbed_worker_instance,
)

logger = logging.getLogger(__name__)


def build_worker_identity() -> str:
    """Stable-per-process identity. Regenerated on every process start."""
    host = (socket.gethostname() or "host")[:40]
    return f"{host}:{os.getpid()}:{uuid4()}"


class PublishRetryCommandWorker:
    """Bounded poll loop: claim/reclaim when gates open; never executes providers."""

    def __init__(self, worker_id: str | None = None) -> None:
        self.worker_id = worker_id or build_worker_identity()
        self.worker_instance = scrubbed_worker_instance(self.worker_id)
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        """Graceful shutdown: stop polling. Do not reset claimed rows to pending."""
        self._stop.set()

    async def run_once(self) -> list[ClaimResult]:
        """One claim/reclaim tick. CLAIM-OBSERVATION only — leave status claimed."""
        allowed, reason = claim_gates_open()
        if not allowed:
            logger.debug(
                "[RetryCommandWorker] gates closed reason=%s instance=%s",
                reason,
                self.worker_instance,
            )
            return [ClaimResult(kind="disabled", reason=reason)]

        async with AsyncSessionLocal() as db:
            results = await PublishRetryCommandClaimService.claim_batch(
                db,
                worker_id=self.worker_id,
                commit=True,
            )

        # Best-effort audit after successful commit (separate sessions).
        await PublishRetryCommandClaimService.record_claim_audits(
            AsyncSessionLocal,
            results,
            worker_id=self.worker_id,
        )

        # B observation mode: intentionally do NOT progress beyond claimed.
        # Execution gate / PublishService / adapters are out of scope.
        for item in results:
            if item.kind in ("claimed", "reclaimed"):
                logger.info(
                    "[RetryCommandWorker] %s command_id=%s correlation=%s instance=%s",
                    item.kind,
                    item.command_id,
                    item.correlation_id,
                    self.worker_instance,
                )
        return results

    async def run_forever(self) -> None:
        poll = max(1.0, float(settings.PUBLISH_RETRY_COMMAND_WORKER_POLL_SECONDS))
        logger.info(
            "[RetryCommandWorker] started instance=%s poll=%s batch=%s lease=%s "
            "commands=%s worker=%s claim=%s execution=%s(unimplemented)",
            self.worker_instance,
            poll,
            settings.PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE,
            settings.PUBLISH_RETRY_COMMAND_LEASE_SECONDS,
            settings.PUBLISH_RETRY_COMMANDS_ENABLED,
            settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED,
            settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED,
            settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED,
        )
        while not self._stop.is_set():
            try:
                if not settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED:
                    # Process flag flipped off mid-run — idle without claiming.
                    pass
                elif not settings.PUBLISH_RETRY_COMMANDS_ENABLED:
                    pass
                elif not settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED:
                    pass
                else:
                    await self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[RetryCommandWorker] tick failed instance=%s",
                    self.worker_instance,
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=poll)
            except asyncio.TimeoutError:
                pass
        logger.info(
            "[RetryCommandWorker] stopped instance=%s (leases left to expire; "
            "no mass-release)",
            self.worker_instance,
        )


async def amain() -> None:
    """Entrypoint. Idles forever when worker flag is false (compose-safe)."""
    if not settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED:
        logger.warning(
            "[RetryCommandWorker] PUBLISH_RETRY_COMMAND_WORKER_ENABLED=false; idling",
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

    worker = PublishRetryCommandWorker()
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
