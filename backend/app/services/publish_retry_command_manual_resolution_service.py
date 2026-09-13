"""Phase E2-1 — manual stranded retry-command resolution (MARK_AMBIGUOUS only).

Bookkeeping terminalization only:

* never calls Claim / Preparation / Barrier / Executor / Finalizer / worker
* never calls providers or provider reconciliation
* never creates replacement PublishRetryCommand rows
* never mutates ContentItem / tenant_external_publications

Entry is limited to ``provider_write_started`` with a non-null write-started
timestamp. Concurrent terminal writers serialize on ``SELECT … FOR UPDATE``;
first commit wins; exact same-action replay is idempotent without audit spam.
Audit is mandatory in the same transaction (``commit=False`` flush); audit
failure rolls back command, attempt, and alert mutations.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.publish_attempt import PublishAttempt
from app.models.publish_operator_alert import PublishOperatorAlert
from app.models.publish_retry_command import (
    RETRY_COMMAND_TERMINAL_STATUSES,
    PublishRetryCommand,
)
from app.services.platform_audit_service import PlatformAuditService
from app.services.publish_operator_alert_service import PublishOperatorAlertService
from app.services.publish_resilience import STATUS_OPERATOR_REVIEW
from app.services.publish_retry_command_stranded_detector import stranded_dedupe_key

logger = logging.getLogger(__name__)

ACTION_MARK_AMBIGUOUS = "MARK_AMBIGUOUS"
ALLOWED_ACTIONS = frozenset({ACTION_MARK_AMBIGUOUS})

AUDIT_EVENT_MARK_AMBIGUOUS = "publishing.retry_cmd_recon_ambiguous"
assert len(AUDIT_EVENT_MARK_AMBIGUOUS) <= 50

OPERATOR_REASON_MAX_LEN = 1000
EVIDENCE_SOURCE_MAX_LEN = 80

ENTRY_STATUS = "provider_write_started"
TERMINAL_STATUS = "ambiguous"
TERMINAL_PROVIDER_OUTCOME = "ambiguous"
ATTEMPT_TERMINAL_STATUS = STATUS_OPERATOR_REVIEW

ResolutionKind = Literal["applied", "already_resolved"]


@dataclass(frozen=True)
class ManualResolutionResult:
    command_id: UUID
    resulting_attempt_id: UUID
    status: str
    provider_outcome: str
    attempt_status: str
    resolution: ResolutionKind
    finished_at: datetime | None
    action: str
    audit_event_type: str | None = None
    audit_id: UUID | None = None
    correlation_id: str | None = None
    alert_resolved: bool = False


class PublishRetryCommandManualResolutionService:
    """Operator-confirmed MARK_AMBIGUOUS for stranded post-barrier commands."""

    @classmethod
    def gates_open(cls) -> bool:
        return bool(getattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", False))

    @classmethod
    async def resolve(
        cls,
        db: AsyncSession,
        *,
        command_id: UUID,
        tenant_id: UUID,
        action: str,
        confirm_permanent_resolution: bool,
        operator_reason: str,
        actor_id: UUID | None,
        actor_type: str = "tenant_user",
        evidence_source: str | None = None,
        commit: bool = True,
    ) -> ManualResolutionResult:
        if not cls.gates_open():
            raise HTTPException(
                status_code=403,
                detail=(
                    "Manual retry-command resolution is disabled "
                    "(PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED=false)"
                ),
            )

        normalized_action = (action or "").strip().upper()
        if normalized_action not in ALLOWED_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported resolution action '{action}'. "
                    f"E2-1 accepts only {ACTION_MARK_AMBIGUOUS}."
                ),
            )

        if confirm_permanent_resolution is not True:
            raise HTTPException(
                status_code=400,
                detail=(
                    "confirm_permanent_resolution must be true. "
                    "MARK_AMBIGUOUS permanently terminalizes the command "
                    "with no further retry execution."
                ),
            )

        reason = cls._normalize_operator_reason(operator_reason)
        evidence = cls._normalize_evidence_source(evidence_source)

        command = await cls._lock_command(db, command_id, tenant_id)

        # Re-check under lock (no optimistic last-write-wins).
        if (
            command.status == TERMINAL_STATUS
            and (command.provider_outcome or "") == TERMINAL_PROVIDER_OUTCOME
            and normalized_action == ACTION_MARK_AMBIGUOUS
        ):
            return await cls._idempotent_already_resolved(db, command)

        if command.status in ("pending", "claimed"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "not_resolvable",
                    "message": (
                        "Command is not in provider_write_started; "
                        "manual resolution is not applicable"
                    ),
                    "status": command.status,
                },
            )

        if command.status in RETRY_COMMAND_TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "already_resolved",
                    "message": (
                        f"Command is already terminal ({command.status}); "
                        "different resolution is not allowed"
                    ),
                    "status": command.status,
                    "provider_outcome": command.provider_outcome,
                },
            )

        if command.status != ENTRY_STATUS or command.provider_write_started_at is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "not_resolvable",
                    "message": (
                        "Command must be provider_write_started with "
                        "provider_write_started_at set"
                    ),
                    "status": command.status,
                },
            )

        if command.resulting_attempt_id is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": "resulting_attempt_id is required for resolution",
                },
            )

        attempt = await cls._lock_resulting_attempt(db, command)
        cls._validate_bidirectional_lineage(command, attempt)

        old_status = command.status
        old_provider_outcome = command.provider_outcome

        # Command terminalization — non-executable forever.
        command.status = TERMINAL_STATUS
        command.provider_outcome = TERMINAL_PROVIDER_OUTCOME
        command.finished_at = func.now()
        command.reason_code = "manual_mark_ambiguous"
        command.updated_at = func.now()

        # Resulting attempt bookkeeping only (ignore any client attempt id).
        attempt.status = ATTEMPT_TERMINAL_STATUS
        attempt.retryable = False
        attempt.next_retry_at = None
        attempt.finished_at = func.now()

        await db.flush()

        audit_row = await cls._record_mandatory_audit(
            db,
            command=command,
            attempt=attempt,
            actor_id=actor_id,
            actor_type=actor_type,
            operator_reason=reason,
            evidence_source=evidence,
            old_status=old_status,
            old_provider_outcome=old_provider_outcome,
        )

        alert_resolved = await cls._resolve_stranded_alert_if_present(
            db,
            tenant_id=tenant_id,
            command_id=command.id,
            actor_id=actor_id,
        )

        await db.refresh(
            command,
            attribute_names=["status", "provider_outcome", "finished_at", "updated_at"],
        )
        await db.refresh(
            attempt,
            attribute_names=["status", "retryable", "next_retry_at", "finished_at"],
        )

        if commit:
            await db.commit()
            await db.refresh(command, attribute_names=["finished_at"])
            await db.refresh(attempt, attribute_names=["finished_at", "status"])

        logger.info(
            "[RetryCmdManualResolve] applied action=%s command_id=%s "
            "attempt_id=%s tenant_id=%s alert_resolved=%s",
            normalized_action,
            command.id,
            attempt.id,
            tenant_id,
            alert_resolved,
        )

        return ManualResolutionResult(
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            status=command.status,
            provider_outcome=command.provider_outcome or TERMINAL_PROVIDER_OUTCOME,
            attempt_status=attempt.status,
            resolution="applied",
            finished_at=command.finished_at,
            action=normalized_action,
            audit_event_type=AUDIT_EVENT_MARK_AMBIGUOUS,
            audit_id=audit_row.id,
            correlation_id=command.correlation_id,
            alert_resolved=alert_resolved,
        )

    @classmethod
    async def _idempotent_already_resolved(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
    ) -> ManualResolutionResult:
        """Same-action replay: no audit, no alert mutation, no timestamp rewrite."""
        if command.resulting_attempt_id is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": (
                        "Terminal ambiguous command missing resulting_attempt_id"
                    ),
                },
            )
        attempt = await db.get(PublishAttempt, command.resulting_attempt_id)
        attempt_status = attempt.status if attempt is not None else ATTEMPT_TERMINAL_STATUS

        logger.info(
            "[RetryCmdManualResolve] already_resolved command_id=%s status=%s",
            command.id,
            command.status,
        )
        return ManualResolutionResult(
            command_id=command.id,
            resulting_attempt_id=command.resulting_attempt_id,
            status=command.status,
            provider_outcome=command.provider_outcome or TERMINAL_PROVIDER_OUTCOME,
            attempt_status=attempt_status,
            resolution="already_resolved",
            finished_at=command.finished_at,
            action=ACTION_MARK_AMBIGUOUS,
            audit_event_type=None,
            audit_id=None,
            correlation_id=command.correlation_id,
            alert_resolved=False,
        )

    @classmethod
    async def _lock_command(
        cls,
        db: AsyncSession,
        command_id: UUID,
        tenant_id: UUID,
    ) -> PublishRetryCommand:
        stmt = (
            select(PublishRetryCommand)
            .where(
                PublishRetryCommand.id == command_id,
                PublishRetryCommand.tenant_id == tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            # Anti-enumeration: same message as read path.
            raise HTTPException(status_code=404, detail="Retry command not found")
        return row

    @classmethod
    async def _lock_resulting_attempt(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
    ) -> PublishAttempt:
        stmt = (
            select(PublishAttempt)
            .where(PublishAttempt.id == command.resulting_attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        attempt = (await db.execute(stmt)).scalar_one_or_none()
        if attempt is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": "resulting_attempt_id points to a missing attempt",
                },
            )
        return attempt

    @classmethod
    def _validate_bidirectional_lineage(
        cls,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
    ) -> None:
        """Fail closed on mismatched lineage — never silent repair."""
        if attempt.retry_command_id != command.id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": (
                        "Bidirectional lineage broken: attempt.retry_command_id "
                        "does not match command"
                    ),
                },
            )
        if attempt.content_id != command.content_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": "Linked attempt content_id mismatch",
                },
            )
        if (attempt.platform or "").strip().lower() != (command.platform or "").strip().lower():
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": "Linked attempt platform mismatch",
                },
            )
        if attempt.account_id != command.publishing_account_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": "Linked attempt account mismatch",
                },
            )

    @classmethod
    async def _record_mandatory_audit(
        cls,
        db: AsyncSession,
        *,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
        actor_id: UUID | None,
        actor_type: str,
        operator_reason: str,
        evidence_source: str | None,
        old_status: str,
        old_provider_outcome: str | None,
    ):
        details: dict[str, Any] = {
            "actor_id": str(actor_id) if actor_id else None,
            "actor_type": actor_type,
            "tenant_id": str(command.tenant_id),
            "command_id": str(command.id),
            "original_attempt_id": str(command.original_attempt_id),
            "resulting_attempt_id": str(attempt.id),
            "old_status": old_status,
            "new_status": command.status,
            "old_provider_outcome": old_provider_outcome,
            "new_provider_outcome": command.provider_outcome,
            "action": ACTION_MARK_AMBIGUOUS,
            "operator_reason": operator_reason,
            "evidence_source": evidence_source,
            "correlation_id": command.correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt_status": attempt.status,
        }
        # commit=False — same TX as command/attempt/alert; flush failure aborts all.
        return await PlatformAuditService.record(
            db,
            actor_type=actor_type if actor_id else "system",
            actor_id=actor_id,
            tenant_id=command.tenant_id,
            event_type=AUDIT_EVENT_MARK_AMBIGUOUS,
            resource_type="publish_retry_command",
            resource_id=str(command.id),
            details=details,
            commit=False,
        )

    @classmethod
    async def _resolve_stranded_alert_if_present(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        command_id: UUID,
        actor_id: UUID | None,
    ) -> bool:
        """Resolve open/acked E1 stranded alert if present; never create one."""
        dedupe = stranded_dedupe_key(command_id)
        alert = (
            await db.execute(
                select(PublishOperatorAlert)
                .where(
                    PublishOperatorAlert.tenant_id == tenant_id,
                    PublishOperatorAlert.dedupe_key == dedupe,
                    PublishOperatorAlert.state.in_(("open", "acknowledged")),
                )
                .with_for_update()
                .execution_options(populate_existing=True),
            )
        ).scalar_one_or_none()
        if alert is None:
            return False

        note = (
            f"{ACTION_MARK_AMBIGUOUS} command_id={command_id} "
            f"terminal_status={TERMINAL_STATUS}"
        )
        # Durable row mutation only — resolve_manual does not gate on Telegram/email.
        await PublishOperatorAlertService.resolve_manual(
            db,
            tenant_id,
            alert.id,
            actor_id=actor_id,
            note=note,
        )
        return True

    @classmethod
    def _normalize_operator_reason(cls, operator_reason: str) -> str:
        if operator_reason is None:
            raise HTTPException(
                status_code=400,
                detail="operator_reason is required",
            )
        reason = operator_reason.strip()
        if not reason:
            raise HTTPException(
                status_code=400,
                detail="operator_reason must be non-empty after trimming",
            )
        if len(reason) > OPERATOR_REASON_MAX_LEN:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"operator_reason exceeds maximum length "
                    f"({OPERATOR_REASON_MAX_LEN})"
                ),
            )
        return reason

    @classmethod
    def _normalize_evidence_source(cls, evidence_source: str | None) -> str | None:
        if evidence_source is None:
            return None
        value = evidence_source.strip()
        if not value:
            return None
        if len(value) > EVIDENCE_SOURCE_MAX_LEN:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"evidence_source exceeds maximum length "
                    f"({EVIDENCE_SOURCE_MAX_LEN})"
                ),
            )
        return value
