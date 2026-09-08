"""Command-specific finalization for retry-command D2-A.

Owns terminal mutation of command-owned attempts only. Does NOT call
``PublishResilienceService.finalize_attempt`` / ``begin_attempt``.

Preconditions (all required):
  command.status == provider_write_started
  command.provider_write_started_at IS NOT NULL
  bidirectional lineage intact
  attempt.retry_command_id == command.id
  attempt still carries write-started forensic markers

Terminal attempt statuses (selector-safe audit):
  SUCCESS           → attempt.status = success
  DEFINITIVE_FAILURE → attempt.status = failed
      (chosen over operator_review: explicit terminal failure; auto-retry
       selectors key on retrying / in_progress only — both failed and
       operator_review are safe, but failed matches known_failure semantics)
  AMBIGUOUS         → attempt.status = operator_review

Never sets retryable=True, next_retry_at, or status=retrying.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import (
    RETRY_COMMAND_TERMINAL_STATUSES,
    PublishRetryCommand,
)
from app.services import publish_retry_command_metrics as cmd_metrics
from app.services.platform_audit_service import PlatformAuditService
from app.services.publish_resilience import (
    STATUS_FAILED,
    STATUS_OPERATOR_REVIEW,
    STATUS_SUCCESS,
)
from app.services.publish_retry_command_barrier_service import (
    WRITE_STARTED_FAILURE_CODE,
)
from app.services.publish_retry_command_claim_service import scrubbed_worker_instance
from app.services.publish_retry_command_outcome_classifier import (
    FAILURE_CODE_AMBIGUOUS,
    FAILURE_CODE_DEFINITIVE,
    ClassifiedProviderOutcome,
)

logger = logging.getLogger(__name__)

FinalizationOutcome = Literal[
    "succeeded",
    "failed",
    "ambiguous",
    "already_finalized",
    "invariant_violation",
    "not_ready",
]

# Forensic codes for terminal command-owned attempts.
SUCCESS_CLEARED_ERROR = None
DEFINITIVE_ATTEMPT_STATUS = STATUS_FAILED
AMBIGUOUS_ATTEMPT_STATUS = STATUS_OPERATOR_REVIEW
AMBIGUOUS_FAILURE_CATEGORY = "command_orchestration"
DEFINITIVE_FAILURE_CATEGORY = "command_orchestration"


@dataclass(frozen=True)
class FinalizationResult:
    """Structured command finalization outcome."""

    ok: bool
    outcome: FinalizationOutcome
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
    already_terminal: bool = False
    external_post_id: str | None = None


class PublishRetryCommandFinalizationService:
    """Atomic terminal mutation for post-barrier command-owned attempts."""

    @classmethod
    async def finalize(
        cls,
        db: AsyncSession,
        *,
        command_id: UUID,
        classified: ClassifiedProviderOutcome,
        worker_id: str,
        correlation_id: str | None = None,
        commit: bool = True,
    ) -> FinalizationResult:
        """Lock command + linked attempt and finalize atomically."""
        try:
            result = await cls._finalize_locked(
                db,
                command_id=command_id,
                classified=classified,
                worker_id=worker_id,
                correlation_id=correlation_id,
            )
            if commit:
                await db.commit()
            else:
                await db.flush()
        except Exception:
            logger.exception(
                "[RetryCommandFinalize] failed command_id=%s worker=%s",
                command_id,
                scrubbed_worker_instance(worker_id),
            )
            if commit:
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
            raise

        cls._record_metrics(result)
        return result

    @classmethod
    async def finalize_and_audit(
        cls,
        db: AsyncSession,
        session_factory,
        *,
        command_id: UUID,
        classified: ClassifiedProviderOutcome,
        worker_id: str,
        correlation_id: str | None = None,
    ) -> FinalizationResult:
        result = await cls.finalize(
            db,
            command_id=command_id,
            classified=classified,
            worker_id=worker_id,
            correlation_id=correlation_id,
            commit=True,
        )
        await cls.record_finalization_audit(
            session_factory,
            result,
            worker_id=worker_id,
        )
        return result

    @classmethod
    async def _finalize_locked(
        cls,
        db: AsyncSession,
        *,
        command_id: UUID,
        classified: ClassifiedProviderOutcome,
        worker_id: str,
        correlation_id: str | None,
    ) -> FinalizationResult:
        del worker_id  # ownership already enforced pre-barrier; forensic only
        command = (
            await db.scalars(
                select(PublishRetryCommand)
                .where(PublishRetryCommand.id == command_id)
                .with_for_update(),
            )
        ).first()
        if command is None:
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command_id,
                reason_code="command_not_found",
                message="Retry command not found",
            )

        corr = correlation_id or command.correlation_id

        # Idempotent terminal short-circuit — never rewrite authoritative state.
        if command.status in RETRY_COMMAND_TERMINAL_STATUSES:
            return FinalizationResult(
                ok=True,
                outcome="already_finalized",
                command_id=command.id,
                resulting_attempt_id=command.resulting_attempt_id,
                original_attempt_id=command.original_attempt_id,
                reason_code="already_finalized",
                message=f"Command already terminal ({command.status})",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
                provider_outcome=command.provider_outcome,
                already_terminal=True,
                external_post_id=None,
            )

        if (
            command.status != "provider_write_started"
            or command.provider_write_started_at is None
        ):
            return FinalizationResult(
                ok=False,
                outcome="not_ready",
                command_id=command.id,
                resulting_attempt_id=command.resulting_attempt_id,
                original_attempt_id=command.original_attempt_id,
                reason_code="not_provider_write_started",
                message=(
                    "Command must be provider_write_started with "
                    "provider_write_started_at set before finalization"
                ),
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
            )

        if command.resulting_attempt_id is None:
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command.id,
                reason_code="missing_resulting_attempt",
                message="resulting_attempt_id required for finalization",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
            )

        attempt = (
            await db.scalars(
                select(PublishAttempt)
                .where(PublishAttempt.id == command.resulting_attempt_id)
                .with_for_update(),
            )
        ).first()
        if attempt is None:
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command.id,
                resulting_attempt_id=command.resulting_attempt_id,
                reason_code="resulting_attempt_missing",
                message="Linked attempt missing",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
            )

        lineage_err = cls._validate_lineage(command, attempt, corr)
        if lineage_err is not None:
            return lineage_err

        write_marker_err = cls._validate_write_started_markers(command, attempt, corr)
        if write_marker_err is not None:
            return write_marker_err

        if classified.outcome == "SUCCESS":
            return await cls._apply_success(db, command, attempt, classified, corr)
        if classified.outcome == "DEFINITIVE_FAILURE":
            return await cls._apply_definitive_failure(
                db, command, attempt, classified, corr,
            )
        return await cls._apply_ambiguous(db, command, attempt, classified, corr)

    @classmethod
    def _validate_lineage(
        cls,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
        corr: str | None,
    ) -> FinalizationResult | None:
        if attempt.retry_command_id != command.id:
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="bidirectional_lineage_broken",
                message="attempt.retry_command_id does not match command.id",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
            )
        if attempt.content_id != command.content_id:
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="tenant_lineage_mismatch",
                message="Linked attempt content_id mismatch — fail closed",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
            )
        if (attempt.platform or "").strip().lower() != (command.platform or "").strip().lower():
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="platform_lineage_mismatch",
                message="Linked attempt platform mismatch — fail closed",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
            )
        if attempt.account_id != command.publishing_account_id:
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="account_lineage_mismatch",
                message="Linked attempt account mismatch — fail closed",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
            )
        return None

    @classmethod
    def _validate_write_started_markers(
        cls,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
        corr: str | None,
    ) -> FinalizationResult | None:
        # Attempt must still look like a post-barrier, pre-finalize row.
        if attempt.status not in (STATUS_OPERATOR_REVIEW,):
            # If somehow already terminal success/failed while command is not,
            # fail closed — Phase E reconciles; do not invent transitions.
            if attempt.status in (STATUS_SUCCESS, STATUS_FAILED) and attempt.finished_at is not None:
                return FinalizationResult(
                    ok=False,
                    outcome="invariant_violation",
                    command_id=command.id,
                    resulting_attempt_id=attempt.id,
                    reason_code="attempt_already_terminal_command_not",
                    message="Attempt terminal while command still write-started",
                    correlation_id=corr,
                    tenant_id=command.tenant_id,
                    platform=command.platform,
                    command_status=command.status,
                    attempt_status=attempt.status,
                )
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="attempt_status_not_write_started",
                message=f"Linked attempt status unexpected ({attempt.status})",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
                attempt_status=attempt.status,
            )
        if (attempt.failure_code or "") != WRITE_STARTED_FAILURE_CODE:
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="attempt_failure_code_not_write_started",
                message=(
                    f"Linked attempt failure_code must be "
                    f"{WRITE_STARTED_FAILURE_CODE} (got {attempt.failure_code})"
                ),
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
                attempt_status=attempt.status,
            )
        if attempt.retryable is not False:
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="attempt_retryable_true",
                message="Command-owned attempt must have retryable=false",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
            )
        if attempt.next_retry_at is not None:
            return FinalizationResult(
                ok=False,
                outcome="invariant_violation",
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="attempt_next_retry_set",
                message="Command-owned attempt next_retry_at must be NULL",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                command_status=command.status,
            )
        return None

    @classmethod
    async def _apply_success(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
        classified: ClassifiedProviderOutcome,
        corr: str | None,
    ) -> FinalizationResult:
        epid = (classified.external_post_id or "").strip() or None
        if epid is None:
            # Defense in depth — classifier should already have rejected this.
            return await cls._apply_ambiguous(
                db,
                command,
                attempt,
                ClassifiedProviderOutcome(
                    outcome="AMBIGUOUS",
                    failure_code=FAILURE_CODE_AMBIGUOUS,
                    safe_message="Success missing external_post_id at finalize",
                    reason_code="success_missing_external_post_id",
                ),
                corr,
            )

        attempt.status = STATUS_SUCCESS
        attempt.retryable = False
        attempt.next_retry_at = None
        attempt.external_post_id = epid
        attempt.external_post_url = classified.external_post_url
        attempt.finished_at = func.now()
        attempt.failure_code = None
        attempt.failure_category = None
        attempt.error = None

        command.status = "succeeded"
        command.provider_outcome = "known_success"
        command.finished_at = func.now()
        command.reason_code = classified.reason_code or "provider_success"
        command.updated_at = func.now()
        # lease_expires_at remains NULL (cleared at barrier)

        await db.flush()
        await db.refresh(command, attribute_names=["status", "finished_at", "provider_outcome"])
        await db.refresh(
            attempt,
            attribute_names=[
                "status", "finished_at", "external_post_id", "retryable", "next_retry_at",
            ],
        )
        return FinalizationResult(
            ok=True,
            outcome="succeeded",
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            original_attempt_id=command.original_attempt_id,
            reason_code="provider_success",
            message="Retry command finalized as success",
            correlation_id=corr,
            tenant_id=command.tenant_id,
            platform=command.platform,
            command_status=command.status,
            attempt_status=attempt.status,
            provider_outcome=command.provider_outcome,
            external_post_id=epid,
        )

    @classmethod
    async def _apply_definitive_failure(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
        classified: ClassifiedProviderOutcome,
        corr: str | None,
    ) -> FinalizationResult:
        # Documented choice: STATUS_FAILED (terminal, non-retryable).
        attempt.status = DEFINITIVE_ATTEMPT_STATUS
        attempt.retryable = False
        attempt.next_retry_at = None
        attempt.finished_at = func.now()
        attempt.failure_code = classified.failure_code or FAILURE_CODE_DEFINITIVE
        attempt.failure_category = DEFINITIVE_FAILURE_CATEGORY
        attempt.error = classified.safe_message or "Provider definitive failure"
        # Do not invent external_post_id on failure.

        command.status = "failed"
        command.provider_outcome = "known_failure"
        command.finished_at = func.now()
        command.reason_code = classified.reason_code or "provider_definitive_failure"
        command.updated_at = func.now()

        await db.flush()
        await db.refresh(command, attribute_names=["status", "finished_at", "provider_outcome"])
        await db.refresh(
            attempt,
            attribute_names=[
                "status", "finished_at", "retryable", "next_retry_at", "failure_code",
            ],
        )
        return FinalizationResult(
            ok=True,
            outcome="failed",
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            original_attempt_id=command.original_attempt_id,
            reason_code="provider_definitive_failure",
            message="Retry command finalized as definitive failure",
            correlation_id=corr,
            tenant_id=command.tenant_id,
            platform=command.platform,
            command_status=command.status,
            attempt_status=attempt.status,
            provider_outcome=command.provider_outcome,
        )

    @classmethod
    async def _apply_ambiguous(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
        classified: ClassifiedProviderOutcome,
        corr: str | None,
    ) -> FinalizationResult:
        attempt.status = AMBIGUOUS_ATTEMPT_STATUS
        attempt.retryable = False
        attempt.next_retry_at = None
        attempt.finished_at = func.now()
        attempt.failure_code = classified.failure_code or FAILURE_CODE_AMBIGUOUS
        attempt.failure_category = AMBIGUOUS_FAILURE_CATEGORY
        attempt.error = classified.safe_message or "Provider ambiguous after write barrier"

        command.status = "ambiguous"
        command.provider_outcome = "ambiguous"
        command.finished_at = func.now()
        command.reason_code = classified.reason_code or "provider_ambiguous"
        command.updated_at = func.now()

        await db.flush()
        await db.refresh(command, attribute_names=["status", "finished_at", "provider_outcome"])
        await db.refresh(
            attempt,
            attribute_names=[
                "status", "finished_at", "retryable", "next_retry_at", "failure_code",
            ],
        )
        return FinalizationResult(
            ok=True,
            outcome="ambiguous",
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            original_attempt_id=command.original_attempt_id,
            reason_code=classified.reason_code or "provider_ambiguous",
            message="Retry command finalized as ambiguous",
            correlation_id=corr,
            tenant_id=command.tenant_id,
            platform=command.platform,
            command_status=command.status,
            attempt_status=attempt.status,
            provider_outcome=command.provider_outcome,
        )

    @classmethod
    def _record_metrics(cls, result: FinalizationResult) -> None:
        try:
            if result.outcome == "already_finalized":
                return
            if result.ok and result.outcome in ("succeeded", "failed", "ambiguous"):
                cmd_metrics.inc("retry_command_finalize_total")
        except Exception:  # noqa: BLE001 — metrics must not alter finalization
            logger.debug(
                "[RetryCommandFinalize] metrics failed outcome=%s",
                result.outcome,
                exc_info=True,
            )

    @classmethod
    async def record_finalization_audit(
        cls,
        session_factory,
        result: FinalizationResult,
        *,
        worker_id: str,
    ) -> None:
        """Best-effort audit; must not alter finalization outcome or trigger replay."""
        if result.command_id is None:
            return
        if result.outcome == "already_finalized":
            return
        if not result.ok:
            return

        event_map = {
            "succeeded": "publishing.retry_command_provider_succeeded",
            "failed": "publishing.retry_command_provider_failed",
            "ambiguous": "publishing.retry_command_provider_ambiguous",
        }
        event_type = event_map.get(result.outcome)
        if event_type is None:
            return

        details: dict[str, Any] = {
            "command_id": str(result.command_id),
            "original_attempt_id": (
                str(result.original_attempt_id) if result.original_attempt_id else None
            ),
            "resulting_attempt_id": (
                str(result.resulting_attempt_id) if result.resulting_attempt_id else None
            ),
            "platform": result.platform,
            "correlation_id": result.correlation_id,
            "worker_instance": scrubbed_worker_instance(worker_id),
            "command_status": result.command_status,
            "attempt_status": result.attempt_status,
            "provider_outcome": result.provider_outcome,
            "reason_code": result.reason_code,
            # external_post_id is an opaque provider id — allowed, not a secret token
            "external_post_id": result.external_post_id,
        }
        try:
            async with session_factory() as db:
                await PlatformAuditService.record(
                    db,
                    actor_type="system",
                    actor_id=None,
                    tenant_id=result.tenant_id,
                    event_type=event_type,
                    resource_type="publish_retry_command",
                    resource_id=str(result.command_id),
                    details=details,
                    commit=True,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[RetryCommandFinalize] audit failed command_id=%s",
                result.command_id,
            )
