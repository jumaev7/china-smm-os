"""Unwired retry-command executor (Phase 3C.1C-D2-A).

Orchestrates:

  claimed command
  → PreparationService          (TX1 COMMIT)
  → BarrierService              (TX2 COMMIT)
  → exactly one provider call   (NO DB TX; injected FakeProvider only)
  → CommandFinalizationService  (TX3 COMMIT)
  → STOP

NOT wired into PublishRetryCommandWorker. No real provider adapters.
No PublishService.publish_content. No begin_attempt / raw finalize_attempt.

Transaction / kill-switch semantics
-----------------------------------
* EXECUTION=false blocks before preparation/barrier (fail closed).
* After a successful ``barrier_crossed`` commit in THIS invocation, the
  executor performs exactly one provider call even if EXECUTION flips false
  mid-flight (preserves barrier point-of-no-return).
* A NEW executor invocation that observes ``provider_write_started`` (or any
  terminal status) MUST NOT call the provider — at-most-once side effects.

Concurrent callers: BarrierService ``FOR UPDATE`` ensures only one
``barrier_crossed``; others get ``already_barriered`` (ok=False) and never
invoke the provider.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.services import publish_retry_command_metrics as cmd_metrics
from app.services.platform_audit_service import PlatformAuditService
from app.services.publish_retry_command_barrier_service import (
    PublishRetryCommandBarrierService,
)
from app.services.publish_retry_command_claim_service import scrubbed_worker_instance
from app.services.publish_retry_command_finalization_service import (
    PublishRetryCommandFinalizationService,
)
from app.services.publish_retry_command_outcome_classifier import (
    FAILURE_CODE_FINALIZE_FAILED,
    ClassifiedProviderOutcome,
    classify_provider_exception,
    classify_provider_result,
)
from app.services.publish_retry_command_preparation_service import (
    PublishRetryCommandPreparationService,
    prepare_gates_open,
)
from app.services.publish_retry_command_provider_port import (
    ProviderExecutionRequest,
    RetryCommandProviderPort,
)

logger = logging.getLogger(__name__)

ExecutorOutcome = Literal[
    "succeeded",
    "failed",
    "ambiguous",
    "already_finalized",
    "already_barriered_no_replay",
    "blocked_preparation",
    "blocked_barrier",
    "post_provider_finalize_failed",
    "disabled",
    "invariant_violation",
]

_PREP_OK = frozenset({
    "prepared",
    "reused_existing_attempt",
    "repaired_attempt_side_link",
})


@dataclass(frozen=True)
class ExecutorResult:
    """Structured executor outcome. No provider payloads/tokens."""

    ok: bool
    outcome: ExecutorOutcome
    command_id: UUID | None = None
    resulting_attempt_id: UUID | None = None
    original_attempt_id: UUID | None = None
    reason_code: str | None = None
    message: str | None = None
    correlation_id: str | None = None
    tenant_id: UUID | None = None
    platform: str | None = None
    command_status: str | None = None
    attempt_status: str | None = None
    provider_outcome: str | None = None
    provider_invoked: bool = False
    provider_invocation_count: int = 0
    external_post_id: str | None = None
    preparation_outcome: str | None = None
    barrier_outcome: str | None = None
    finalization_outcome: str | None = None


class PublishRetryCommandExecutor:
    """Coordinates prepare → barrier → one fake provider call → finalize."""

    @classmethod
    async def execute(
        cls,
        session_factory,
        *,
        command_id: UUID,
        worker_id: str,
        provider: RetryCommandProviderPort,
        correlation_id: str | None = None,
    ) -> ExecutorResult:
        """Run the D2-A orchestration path once for a claimed command.

        ``provider`` must be injected explicitly (tests: FakeProviderExecutor).
        """
        # Pre-barrier kill switch — do not start preparation when closed.
        allowed, gate_reason = prepare_gates_open()
        if not allowed:
            return ExecutorResult(
                ok=False,
                outcome="disabled",
                command_id=command_id,
                reason_code=gate_reason,
                message="Retry command execution is disabled",
            )

        # --- TX1: Preparation ---
        async with session_factory() as db:
            prep = await PublishRetryCommandPreparationService.prepare(
                db,
                command_id=command_id,
                worker_id=worker_id,
                correlation_id=correlation_id,
                commit=True,
            )
        try:
            await PublishRetryCommandPreparationService.record_preparation_audit(
                session_factory,
                prep,
                worker_id=worker_id,
            )
        except Exception:  # noqa: BLE001 — audit must not alter orchestration
            logger.exception(
                "[RetryCommandExecutor] prep audit failed command_id=%s",
                command_id,
            )

        if prep.outcome == "blocked_terminal_or_post_write":
            # Already barriered or terminal — NEVER replay provider.
            return ExecutorResult(
                ok=True,
                outcome=(
                    "already_finalized"
                    if (prep.reason_code == "terminal_command")
                    else "already_barriered_no_replay"
                ),
                command_id=prep.command_id or command_id,
                resulting_attempt_id=prep.resulting_attempt_id,
                original_attempt_id=prep.original_attempt_id,
                reason_code=prep.reason_code or "no_replay",
                message=prep.message or "Post-barrier / terminal — provider not invoked",
                correlation_id=prep.correlation_id or correlation_id,
                tenant_id=prep.tenant_id,
                platform=prep.platform,
                command_status=prep.command_status,
                provider_invoked=False,
                provider_invocation_count=0,
                preparation_outcome=prep.outcome,
            )

        if not prep.ok or prep.outcome not in _PREP_OK:
            return ExecutorResult(
                ok=False,
                outcome=(
                    "disabled"
                    if prep.outcome == "disabled"
                    else (
                        "invariant_violation"
                        if prep.outcome == "invariant_violation"
                        else "blocked_preparation"
                    )
                ),
                command_id=prep.command_id or command_id,
                resulting_attempt_id=prep.resulting_attempt_id,
                original_attempt_id=prep.original_attempt_id,
                reason_code=prep.reason_code,
                message=prep.message,
                correlation_id=prep.correlation_id or correlation_id,
                tenant_id=prep.tenant_id,
                platform=prep.platform,
                command_status=prep.command_status,
                provider_invoked=False,
                preparation_outcome=prep.outcome,
            )

        # --- TX2: Barrier ---
        async with session_factory() as db:
            barrier = await PublishRetryCommandBarrierService.cross_barrier(
                db,
                command_id=command_id,
                worker_id=worker_id,
                correlation_id=correlation_id or prep.correlation_id,
                commit=True,
            )
        try:
            await PublishRetryCommandBarrierService.record_barrier_audit(
                session_factory,
                barrier,
                worker_id=worker_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[RetryCommandExecutor] barrier audit failed command_id=%s",
                command_id,
            )

        if barrier.outcome == "already_barriered":
            return ExecutorResult(
                ok=True,
                outcome="already_barriered_no_replay",
                command_id=barrier.command_id or command_id,
                resulting_attempt_id=barrier.resulting_attempt_id,
                original_attempt_id=barrier.original_attempt_id,
                reason_code="already_barriered",
                message="Barrier already crossed — provider not invoked",
                correlation_id=barrier.correlation_id or correlation_id,
                tenant_id=barrier.tenant_id,
                platform=barrier.platform,
                command_status=barrier.command_status,
                provider_invoked=False,
                preparation_outcome=prep.outcome,
                barrier_outcome=barrier.outcome,
            )

        if not barrier.ok or barrier.outcome != "barrier_crossed":
            return ExecutorResult(
                ok=False,
                outcome=(
                    "disabled"
                    if barrier.outcome == "disabled"
                    else (
                        "invariant_violation"
                        if barrier.outcome == "invariant_violation"
                        else "blocked_barrier"
                    )
                ),
                command_id=barrier.command_id or command_id,
                resulting_attempt_id=barrier.resulting_attempt_id,
                original_attempt_id=barrier.original_attempt_id,
                reason_code=barrier.reason_code,
                message=barrier.message,
                correlation_id=barrier.correlation_id or correlation_id,
                tenant_id=barrier.tenant_id,
                platform=barrier.platform,
                command_status=barrier.command_status,
                provider_invoked=False,
                preparation_outcome=prep.outcome,
                barrier_outcome=barrier.outcome,
            )

        # Point of no return. Do NOT re-check EXECUTION before provider call.
        assert barrier.resulting_attempt_id is not None
        request = ProviderExecutionRequest(
            command_id=command_id,
            resulting_attempt_id=barrier.resulting_attempt_id,
            platform=barrier.platform or prep.platform or "unknown",
            tenant_id=barrier.tenant_id or prep.tenant_id,
            correlation_id=barrier.correlation_id or prep.correlation_id or correlation_id,
        )

        try:
            await cls._audit_provider_call_started(
                session_factory,
                command_id=command_id,
                worker_id=worker_id,
                tenant_id=request.tenant_id,
                platform=request.platform,
                correlation_id=request.correlation_id,
                resulting_attempt_id=request.resulting_attempt_id,
            )
        except Exception:  # noqa: BLE001 — audit must never skip the provider call
            logger.exception(
                "[RetryCommandExecutor] provider_call_started audit raised "
                "command_id=%s",
                command_id,
            )

        # --- NO DB TX: exactly one provider invocation ---
        # Metrics must not gate or skip the provider call.
        try:
            cmd_metrics.inc("retry_command_provider_calls_total")
        except Exception:  # noqa: BLE001
            logger.debug(
                "[RetryCommandExecutor] provider_calls metric failed",
                exc_info=True,
            )

        provider_invoked = False
        classified: ClassifiedProviderOutcome
        try:
            raw = await provider.execute(request)
            provider_invoked = True
            classified = classify_provider_result(raw)
        except Exception as exc:  # noqa: BLE001 — post-barrier → AMBIGUOUS
            provider_invoked = True
            classified = classify_provider_exception(exc)
            logger.warning(
                "[RetryCommandExecutor] provider raised after barrier "
                "command_id=%s reason=%s",
                command_id,
                classified.reason_code,
            )

        cls._record_provider_outcome_metrics(classified)

        # --- TX3: Finalization ---
        try:
            async with session_factory() as db:
                fin = await PublishRetryCommandFinalizationService.finalize(
                    db,
                    command_id=command_id,
                    classified=classified,
                    worker_id=worker_id,
                    correlation_id=request.correlation_id,
                    commit=True,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[RetryCommandExecutor] finalization TX failed after provider "
                "command_id=%s — NO provider replay",
                command_id,
            )
            return ExecutorResult(
                ok=False,
                outcome="post_provider_finalize_failed",
                command_id=command_id,
                resulting_attempt_id=barrier.resulting_attempt_id,
                original_attempt_id=barrier.original_attempt_id,
                reason_code=FAILURE_CODE_FINALIZE_FAILED,
                message=(
                    "Provider result obtained but finalization transaction failed; "
                    "DB may remain provider_write_started (Phase E reconciles)"
                ),
                correlation_id=request.correlation_id,
                tenant_id=barrier.tenant_id,
                platform=barrier.platform,
                command_status="provider_write_started",
                provider_invoked=provider_invoked,
                provider_invocation_count=1 if provider_invoked else 0,
                preparation_outcome=prep.outcome,
                barrier_outcome=barrier.outcome,
                finalization_outcome="tx_failed",
            )

        try:
            await PublishRetryCommandFinalizationService.record_finalization_audit(
                session_factory,
                fin,
                worker_id=worker_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[RetryCommandExecutor] finalize audit failed command_id=%s",
                command_id,
            )

        if not fin.ok:
            # Finalizer rejected (invariant) after provider — treat as local ambiguous state.
            return ExecutorResult(
                ok=False,
                outcome="post_provider_finalize_failed",
                command_id=fin.command_id or command_id,
                resulting_attempt_id=fin.resulting_attempt_id or barrier.resulting_attempt_id,
                original_attempt_id=fin.original_attempt_id or barrier.original_attempt_id,
                reason_code=fin.reason_code or FAILURE_CODE_FINALIZE_FAILED,
                message=fin.message or "Finalization rejected after provider call",
                correlation_id=fin.correlation_id or request.correlation_id,
                tenant_id=fin.tenant_id or barrier.tenant_id,
                platform=fin.platform or barrier.platform,
                command_status=fin.command_status,
                attempt_status=fin.attempt_status,
                provider_invoked=provider_invoked,
                provider_invocation_count=1 if provider_invoked else 0,
                preparation_outcome=prep.outcome,
                barrier_outcome=barrier.outcome,
                finalization_outcome=fin.outcome,
            )

        outcome_map = {
            "succeeded": "succeeded",
            "failed": "failed",
            "ambiguous": "ambiguous",
            "already_finalized": "already_finalized",
        }
        exec_outcome: ExecutorOutcome = outcome_map.get(fin.outcome, "ambiguous")  # type: ignore[assignment]

        return ExecutorResult(
            ok=True,
            outcome=exec_outcome,
            command_id=fin.command_id or command_id,
            resulting_attempt_id=fin.resulting_attempt_id,
            original_attempt_id=fin.original_attempt_id,
            reason_code=fin.reason_code,
            message=fin.message,
            correlation_id=fin.correlation_id or request.correlation_id,
            tenant_id=fin.tenant_id,
            platform=fin.platform,
            command_status=fin.command_status,
            attempt_status=fin.attempt_status,
            provider_outcome=fin.provider_outcome,
            provider_invoked=provider_invoked,
            provider_invocation_count=1 if provider_invoked else 0,
            external_post_id=fin.external_post_id,
            preparation_outcome=prep.outcome,
            barrier_outcome=barrier.outcome,
            finalization_outcome=fin.outcome,
        )

    @classmethod
    def _record_provider_outcome_metrics(
        cls,
        classified: ClassifiedProviderOutcome,
    ) -> None:
        try:
            if classified.outcome == "SUCCESS":
                cmd_metrics.inc("retry_command_provider_success_total")
            elif classified.outcome == "DEFINITIVE_FAILURE":
                cmd_metrics.inc("retry_command_provider_failure_total")
            else:
                cmd_metrics.inc("retry_command_provider_ambiguous_total")
        except Exception:  # noqa: BLE001
            logger.debug(
                "[RetryCommandExecutor] provider outcome metrics failed",
                exc_info=True,
            )

    @classmethod
    async def _audit_provider_call_started(
        cls,
        session_factory,
        *,
        command_id: UUID,
        worker_id: str,
        tenant_id: UUID | None,
        platform: str | None,
        correlation_id: str | None,
        resulting_attempt_id: UUID | None,
    ) -> None:
        details: dict[str, Any] = {
            "command_id": str(command_id),
            "resulting_attempt_id": (
                str(resulting_attempt_id) if resulting_attempt_id else None
            ),
            "platform": platform,
            "correlation_id": correlation_id,
            "worker_instance": scrubbed_worker_instance(worker_id),
        }
        try:
            async with session_factory() as db:
                await PlatformAuditService.record(
                    db,
                    actor_type="system",
                    actor_id=None,
                    tenant_id=tenant_id,
                    event_type="publishing.retry_command_provider_call_started",
                    resource_type="publish_retry_command",
                    resource_id=str(command_id),
                    details=details,
                    commit=True,
                )
        except Exception:  # noqa: BLE001 — audit must not skip/alter provider call
            logger.exception(
                "[RetryCommandExecutor] provider_call_started audit failed "
                "command_id=%s",
                command_id,
            )
