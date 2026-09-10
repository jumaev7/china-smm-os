"""Publish retry-command worker (Phase 3C.1C-D2-B1 / B2b1-A).

Claim/reclaim ownership, then:

* ``EXECUTION_BACKEND=none`` → safe pre-executor stop (D2-B1)
* verified staging fake ``RetryCommandWorkerExecutionContext`` → executor handoff
  (B2b1-A; bootstrap must succeed before this worker is constructed)

Does not know APP_ENV, current_database, staging DB names, provider-secret
policy, or fake sink paths — those live in staging bootstrap only.

Compose profile ``retry-command`` isolates this process from broad
``docker compose up``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.services import publish_retry_command_metrics as cmd_metrics
from app.services.publish_retry_command_claim_service import (
    ClaimResult,
    PublishRetryCommandClaimService,
    claim_gates_open,
    scrubbed_worker_instance,
)
from app.services.publish_retry_command_execution_backend import (
    assert_worker_execution_backend_or_exit,
    resolve_execution_backend,
)

if TYPE_CHECKING:
    from app.services.publish_retry_command_staging_worker_bootstrap import (
        RetryCommandWorkerExecutionContext,
    )

logger = logging.getLogger(__name__)


def build_worker_identity() -> str:
    """Stable-per-process identity. Regenerated on every process start."""
    host = (socket.gethostname() or "host")[:40]
    return f"{host}:{os.getpid()}:{uuid4()}"


class PublishRetryCommandWorker:
    """Bounded poll loop: claim/reclaim, then none-stop or verified fake handoff.

    ``execution=None`` preserves D2-B1 backend=none semantics.
    ``execution`` set only after staging bootstrap succeeds (fake only).
    """

    def __init__(
        self,
        worker_id: str | None = None,
        *,
        execution: RetryCommandWorkerExecutionContext | None = None,
    ) -> None:
        self.worker_id = worker_id or build_worker_identity()
        self.worker_instance = scrubbed_worker_instance(self.worker_id)
        self._stop = asyncio.Event()
        self._execution = execution

    def request_stop(self) -> None:
        """Graceful shutdown: stop new claims / orchestration starts.

        Does NOT cancel an already-running executor / in-flight orchestration.
        Do not mass-release leases. Active work completes; leases expire.
        """
        self._stop.set()

    async def run_once(self) -> list[ClaimResult]:
        """One claim/reclaim tick, then sequential post-claim orchestration.

        Claim transaction commits and the session closes before any
        orchestration. Only rows returned by this tick are considered —
        no scan of arbitrary claimed / provider_write_started rows.
        """
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
        # Claim session is closed here — no DB TX across orchestration.

        # Best-effort audit after successful commit (separate sessions).
        await PublishRetryCommandClaimService.record_claim_audits(
            AsyncSessionLocal,
            results,
            worker_id=self.worker_id,
        )

        # Sequential only. No asyncio.gather / fan-out.
        for item in results:
            if item.kind not in ("claimed", "reclaimed"):
                continue
            if self._stop.is_set():
                # SIGTERM after claim: leave lease; do not start orchestration.
                logger.info(
                    "[RetryCommandWorker] stop requested after claim; "
                    "leaving command_id=%s for lease expiry instance=%s",
                    item.command_id,
                    self.worker_instance,
                )
                break
            assert item.command_id is not None
            try:
                await self._orchestrate_after_claim(command_id=item.command_id)
            except Exception:  # noqa: BLE001 — per-command; no immediate retry
                logger.exception(
                    "[RetryCommandWorker] orchestration failed command_id=%s "
                    "instance=%s (no immediate retry; lease/reclaim only)",
                    item.command_id,
                    self.worker_instance,
                )
        return results

    async def _orchestrate_after_claim(self, *, command_id: UUID) -> None:
        """Post-claim handoff. Owns only command_id + worker_id (+ verified ctx).

        Reachable paths:
          EXECUTION=false → observation metric, stop
          EXECUTION=true + backend=none → observation metric, stop
          EXECUTION=true + verified fake execution context → executor handoff
          any other backend / fake without context → fail closed
        """
        if not settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED:
            cmd_metrics.inc("retry_command_worker_execution_disabled_total")
            logger.info(
                "[RetryCommandWorker] execution disabled; observation only "
                "command_id=%s instance=%s",
                command_id,
                self.worker_instance,
            )
            return

        resolution = resolve_execution_backend()
        if resolution.value == "none":
            cmd_metrics.inc("retry_command_worker_backend_none_total")
            logger.info(
                "[RetryCommandWorker] backend=none; safe pre-executor stop "
                "command_id=%s instance=%s",
                command_id,
                self.worker_instance,
            )
            return

        if resolution.value == "fake" and self._execution is not None:
            if self._execution.execution_backend != "fake":
                cmd_metrics.inc("retry_command_worker_backend_invalid_total")
                logger.error(
                    "[RetryCommandWorker] refusing non-fake execution context "
                    "command_id=%s instance=%s",
                    command_id,
                    self.worker_instance,
                )
                return
            await self._future_executor_handoff(command_id=command_id)
            return

        # Fail closed — fake without bootstrap context, or real/invalid.
        cmd_metrics.inc("retry_command_worker_backend_invalid_total")
        logger.error(
            "[RetryCommandWorker] refusing orchestration backend=%s reason=%s "
            "command_id=%s instance=%s execution_context=%s",
            resolution.value,
            resolution.reason,
            command_id,
            self.worker_instance,
            self._execution is not None,
        )

    async def _future_executor_handoff(self, *, command_id: UUID) -> None:
        """Verified fake execution handoff after claim TX close.

        Passes command_id + worker_id + provider + eligibility + hooks from the
        frozen context. Does not pass a trusted ORM snapshot — executor reloads.
        """
        execution = self._execution
        if execution is None or execution.execution_backend != "fake":
            raise RuntimeError(
                "executor handoff requires verified fake execution context; "
                f"command_id={command_id} worker_id={self.worker_id}"
            )
        result = await execution.execute_claimed(
            AsyncSessionLocal,
            command_id=command_id,
            worker_id=self.worker_id,
        )
        logger.info(
            "[RetryCommandWorker] fake executor finished command_id=%s "
            "outcome=%s provider_invoked=%s instance=%s",
            command_id,
            result.outcome,
            result.provider_invoked,
            self.worker_instance,
        )

    async def run_forever(self) -> None:
        poll = max(1.0, float(settings.PUBLISH_RETRY_COMMAND_WORKER_POLL_SECONDS))
        backend = resolve_execution_backend()
        logger.info(
            "[RetryCommandWorker] started instance=%s poll=%s batch=%s lease=%s "
            "commands=%s worker=%s claim=%s execution=%s backend=%s "
            "verified_fake_context=%s",
            self.worker_instance,
            poll,
            settings.PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE,
            settings.PUBLISH_RETRY_COMMAND_LEASE_SECONDS,
            settings.PUBLISH_RETRY_COMMANDS_ENABLED,
            settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED,
            settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED,
            settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED,
            backend.value,
            self._execution is not None,
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
    """Entrypoint. Idles forever when worker flag is false (compose-safe).

    Dispatch:
      backend=none → D2-B1 path (execution=None)
      backend=fake → staging bootstrap FIRST, then worker(execution=context)
      real/unknown → SystemExit(2)
    """
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

    resolution = resolve_execution_backend()
    execution: RetryCommandWorkerExecutionContext | None = None

    if resolution.value == "none" and resolution.d2b1_runnable:
        assert_worker_execution_backend_or_exit()
    elif resolution.value == "fake":
        # Bootstrap BEFORE worker construction / poll / claim.
        from app.services.publish_retry_command_staging_worker_bootstrap import (
            StagingWorkerBootstrapError,
            bootstrap_staging_fake_worker_execution,
        )

        try:
            execution = await bootstrap_staging_fake_worker_execution(engine)
        except StagingWorkerBootstrapError as exc:
            logger.error(
                "[RetryCommandWorker] staging fake bootstrap failed reason=%s "
                "detail=%s (no claim)",
                exc.reason,
                exc.detail,
            )
            raise SystemExit(2) from exc
    else:
        logger.error(
            "[RetryCommandWorker] refusing start: PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=%r "
            "reason=%s",
            resolution.value,
            resolution.reason,
        )
        raise SystemExit(2)

    worker = PublishRetryCommandWorker(execution=execution)
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
