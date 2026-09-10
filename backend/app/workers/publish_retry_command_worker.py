"""Publish retry-command worker (Phase 3C.1C-D2-B1 / B2b1-A / B2b1-B).

Claim/reclaim ownership, then:

* ``EXECUTION_BACKEND=none`` → safe pre-executor stop (D2-B1)
* verified staging fake ``RetryCommandWorkerExecutionContext`` → executor handoff
  (B2b1-A; bootstrap must succeed before this worker is constructed)

B2b1-B graceful shutdown:

* SIGTERM/SIGINT → ``request_stop()`` (flag only; never cancels active executor)
* pre-barrier: ``should_stop_before_barrier`` → ``stopped_before_barrier``
* post-barrier: drain active executor (bounded); no cancel / no replay
* no new claim after stop

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
from typing import TYPE_CHECKING, Any
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

# Process exit codes (B2b1-B).
EXIT_OK = 0
EXIT_BOOTSTRAP_FAILURE = 2
EXIT_DRAIN_TIMEOUT = 3
EXIT_INVARIANT_FAILURE = 4

DEFAULT_DRAIN_SECONDS = 60.0


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
        drain_seconds: float | None = None,
    ) -> None:
        self.worker_id = worker_id or build_worker_identity()
        self.worker_instance = scrubbed_worker_instance(self.worker_id)
        self._stop = asyncio.Event()
        self._execution = execution
        if drain_seconds is not None:
            self._drain_seconds = float(drain_seconds)
        else:
            self._drain_seconds = float(
                getattr(
                    settings,
                    "PUBLISH_RETRY_COMMAND_WORKER_DRAIN_SECONDS",
                    DEFAULT_DRAIN_SECONDS,
                )
                or DEFAULT_DRAIN_SECONDS
            )
        self._exit_code = EXIT_OK
        self._active_task: asyncio.Task | None = None
        self._active_command_id: UUID | None = None

    @property
    def exit_code(self) -> int:
        return self._exit_code

    def request_stop(self) -> None:
        """Graceful shutdown: stop new claims / orchestration starts.

        Sets the stop flag/event only. MUST NOT cancel the active executor
        task, raise into the executor, close DB under an active executor,
        kill the provider coroutine, or force immediate exit.
        """
        if not self._stop.is_set():
            try:
                cmd_metrics.inc("retry_command_worker_stop_requested_total")
            except Exception:  # noqa: BLE001
                pass
            logger.info(
                "[RetryCommandWorker] worker_stop_requested instance=%s "
                "active_command_id=%s",
                self.worker_instance,
                self._active_command_id,
            )
        self._stop.set()

    def _should_stop_before_barrier(self) -> bool:
        """Control-plane stop flag for executor pre-barrier check. No I/O."""
        return self._stop.is_set()

    async def run_once(self) -> list[ClaimResult]:
        """One claim/reclaim tick, then sequential post-claim orchestration.

        Claim transaction commits and the session closes before any
        orchestration. Only rows returned by this tick are considered —
        no scan of arbitrary claimed / provider_write_started rows.
        """
        if self._stop.is_set():
            logger.info(
                "[RetryCommandWorker] stop already requested; skipping claim "
                "instance=%s",
                self.worker_instance,
            )
            return []

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

        # Sequential only. No fan-out concurrency across commands.
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
                if self._exit_code == EXIT_OK:
                    self._exit_code = EXIT_INVARIANT_FAILURE
            if self._exit_code != EXIT_OK:
                break
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
                self._exit_code = EXIT_INVARIANT_FAILURE
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
        self._exit_code = EXIT_INVARIANT_FAILURE

    async def _future_executor_handoff(self, *, command_id: UUID) -> None:
        """Verified fake execution handoff after claim TX close.

        Passes command_id + worker_id + provider + eligibility + hooks +
        should_stop_before_barrier from the worker. Does not pass a trusted
        ORM snapshot — executor reloads.
        """
        execution = self._execution
        if execution is None or execution.execution_backend != "fake":
            raise RuntimeError(
                "executor handoff requires verified fake execution context; "
                f"command_id={command_id} worker_id={self.worker_id}"
            )

        async def _run_executor() -> Any:
            return await execution.execute_claimed(
                AsyncSessionLocal,
                command_id=command_id,
                worker_id=self.worker_id,
                should_stop_before_barrier=self._should_stop_before_barrier,
            )

        task = asyncio.create_task(
            _run_executor(),
            name=f"retry-command-executor:{command_id}",
        )
        self._active_task = task
        self._active_command_id = command_id
        try:
            result = await self._await_active_executor(task)
        finally:
            self._active_task = None
            self._active_command_id = None

        if result is None:
            # Drain timed out — DB left as-is; no replay.
            return

        if result.outcome == "stopped_before_barrier":
            logger.info(
                "[RetryCommandWorker] worker_stopped_before_barrier "
                "command_id=%s instance=%s",
                command_id,
                self.worker_instance,
            )
        logger.info(
            "[RetryCommandWorker] fake executor finished command_id=%s "
            "outcome=%s provider_invoked=%s instance=%s",
            command_id,
            result.outcome,
            result.provider_invoked,
            self.worker_instance,
        )

    async def _await_active_executor(
        self,
        task: asyncio.Task,
    ) -> Any | None:
        """Await active executor; after stop, bound drain via shield (no cancel).

        Normal path: direct completion of the task.
        After stop while in-flight: ``wait_for(shield(task), drain_seconds)``.
        On drain timeout: set non-zero exit code; do NOT cancel the task;
        do NOT mutate command / replay provider. Process should exit.
        """
        stop_waiter = asyncio.create_task(self._stop.wait())
        try:
            done, _pending = await asyncio.wait(
                {task, stop_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if task in done:
                return task.result()

            # Stop requested while executor still running — drain with bound.
            try:
                cmd_metrics.inc("retry_command_worker_draining_total")
            except Exception:  # noqa: BLE001
                pass
            logger.info(
                "[RetryCommandWorker] worker_draining_active_command "
                "command_id=%s drain_seconds=%s instance=%s",
                self._active_command_id,
                self._drain_seconds,
                self.worker_instance,
            )
            try:
                # shield: wait_for must NOT cancel the post-barrier executor.
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=float(self._drain_seconds),
                )
            except asyncio.TimeoutError:
                try:
                    cmd_metrics.inc("retry_command_worker_drain_timeout_total")
                except Exception:  # noqa: BLE001
                    pass
                logger.error(
                    "[RetryCommandWorker] worker_drain_timeout "
                    "command_id=%s drain_seconds=%s instance=%s "
                    "(no replay/reset; DB left as-is; Phase E later)",
                    self._active_command_id,
                    self._drain_seconds,
                    self.worker_instance,
                )
                self._exit_code = EXIT_DRAIN_TIMEOUT
                # Do not cancel task. Process exit reaps; if process remains
                # alive the shielded task may still run — no second call.
                return None

            try:
                cmd_metrics.inc("retry_command_worker_drain_completed_total")
            except Exception:  # noqa: BLE001
                pass
            logger.info(
                "[RetryCommandWorker] worker_drain_completed "
                "command_id=%s instance=%s",
                self._active_command_id,
                self.worker_instance,
            )
            return task.result()
        finally:
            if not stop_waiter.done():
                stop_waiter.cancel()
                try:
                    await stop_waiter
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    async def run_forever(self) -> None:
        poll = max(1.0, float(settings.PUBLISH_RETRY_COMMAND_WORKER_POLL_SECONDS))
        backend = resolve_execution_backend()
        logger.info(
            "[RetryCommandWorker] started instance=%s poll=%s batch=%s lease=%s "
            "commands=%s worker=%s claim=%s execution=%s backend=%s "
            "verified_fake_context=%s drain_seconds=%s",
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
            self._drain_seconds,
        )
        while not self._stop.is_set() and self._exit_code == EXIT_OK:
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
                if self._exit_code == EXIT_OK:
                    self._exit_code = EXIT_INVARIANT_FAILURE
                    break
            if self._exit_code != EXIT_OK:
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=poll)
            except asyncio.TimeoutError:
                pass
        logger.info(
            "[RetryCommandWorker] stopped instance=%s exit_code=%s "
            "(leases left to expire; no mass-release)",
            self.worker_instance,
            self._exit_code,
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
            raise SystemExit(EXIT_BOOTSTRAP_FAILURE) from exc
    else:
        logger.error(
            "[RetryCommandWorker] refusing start: PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=%r "
            "reason=%s",
            resolution.value,
            resolution.reason,
        )
        raise SystemExit(EXIT_BOOTSTRAP_FAILURE)

    worker = PublishRetryCommandWorker(execution=execution)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: worker.request_stop())
    await worker.run_forever()
    if worker.exit_code != EXIT_OK:
        raise SystemExit(worker.exit_code)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(amain())
