"""Phase E2 manual stranded retry-command resolution.

E2-1: MARK_AMBIGUOUS (PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED)
E2-2: ACKNOWLEDGE_EXTERNAL_SUCCESS (PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED)

Bookkeeping terminalization only:

* never calls Claim / Preparation / Barrier / Executor / Finalizer / worker
* never calls providers or provider reconciliation
* never fetches evidence URLs
* never creates replacement PublishRetryCommand rows
* never mutates ContentItem / tenant_external_publications
* never synthesizes attempt.response JSON

Entry is limited to ``provider_write_started`` with a non-null write-started
timestamp. Concurrent terminal writers serialize on ``SELECT … FOR UPDATE``;
first commit wins. E2-1 same-action replay is idempotent without audit spam.
E2-2 compatible manual replay requires reason_code + exactly one matching
authoritative audit; executor terminals are never treated as manual replay.
Audit is mandatory in the same transaction (``commit=False`` flush); audit
failure rolls back command, attempt, and alert mutations.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.platform_ops import PlatformAuditLog
from app.models.publish_attempt import PublishAttempt
from app.models.publish_operator_alert import PublishOperatorAlert
from app.models.publish_retry_command import (
    RETRY_COMMAND_TERMINAL_STATUSES,
    PublishRetryCommand,
)
from app.services.platform_audit_service import PlatformAuditService
from app.services.publish_operator_alert_service import PublishOperatorAlertService
from app.services.publish_resilience import STATUS_OPERATOR_REVIEW, STATUS_SUCCESS
from app.services.publish_retry_command_stranded_detector import stranded_dedupe_key

logger = logging.getLogger(__name__)

ACTION_MARK_AMBIGUOUS = "MARK_AMBIGUOUS"
ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS = "ACKNOWLEDGE_EXTERNAL_SUCCESS"
ALLOWED_ACTIONS = frozenset({
    ACTION_MARK_AMBIGUOUS,
    ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
})

AUDIT_EVENT_MARK_AMBIGUOUS = "publishing.retry_cmd_recon_ambiguous"
AUDIT_EVENT_ACK_EXTERNAL_SUCCESS = "publishing.retry_cmd_recon_success"
assert len(AUDIT_EVENT_MARK_AMBIGUOUS) <= 50
assert len(AUDIT_EVENT_ACK_EXTERNAL_SUCCESS) <= 50

REASON_CODE_MARK_AMBIGUOUS = "manual_mark_ambiguous"
REASON_CODE_ACK_EXTERNAL_SUCCESS = "operator_ack_external_success"
REASON_CODE_PROVIDER_SUCCESS = "provider_success"

OPERATOR_REASON_MAX_LEN = 1000
EVIDENCE_SOURCE_MAX_LEN = 80
EXTERNAL_POST_ID_MAX_LEN = 255
EXTERNAL_POST_URL_MAX_LEN = 2000

# Match barrier write-started marker without importing barrier/execution modules.
WRITE_STARTED_FAILURE_CODE = "retry_command_write_started"
WRITE_STARTED_ATTEMPT_STATUS = STATUS_OPERATOR_REVIEW

ENTRY_STATUS = "provider_write_started"
AMBIGUOUS_STATUS = "ambiguous"
AMBIGUOUS_PROVIDER_OUTCOME = "ambiguous"
AMBIGUOUS_ATTEMPT_STATUS = STATUS_OPERATOR_REVIEW

SUCCESS_STATUS = "succeeded"
SUCCESS_PROVIDER_OUTCOME = "known_success"
SUCCESS_ATTEMPT_STATUS = STATUS_SUCCESS

_SAFE_PERMALINK_SCHEMES = frozenset({"http", "https"})
_SIGNED_URL_MARKERS = ("X-Amz-Signature", "Signature=", "X-Goog-Signature", "sig=")

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
    external_post_id: str | None = None


@dataclass(frozen=True)
class _SuccessEvidence:
    operator_reason: str
    evidence_source: str
    external_post_id: str
    external_post_url: str | None
    observed_at: datetime | None


class PublishRetryCommandManualResolutionService:
    """Operator-confirmed manual resolution for stranded post-barrier commands."""

    @classmethod
    def gates_open(cls) -> bool:
        """E2-1 MARK_AMBIGUOUS gate (backward-compatible name)."""
        return bool(getattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", False))

    @classmethod
    def gates_open_e2_2(cls) -> bool:
        """E2-2 acknowledgment requires BOTH feature flags (intentional)."""
        return bool(
            getattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", False)
        ) and bool(
            getattr(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", False)
        )

    @classmethod
    def _require_action_gate(cls, normalized_action: str) -> None:
        if normalized_action == ACTION_MARK_AMBIGUOUS:
            if not cls.gates_open():
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "Manual retry-command resolution is disabled "
                        "(PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED=false)"
                    ),
                )
            return
        if normalized_action == ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS:
            e2_2 = bool(
                getattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", False)
            )
            coord = bool(
                getattr(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", False)
            )
            if not e2_2:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "E2-2 manual success acknowledgment is disabled "
                        "(PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED=false)"
                    ),
                )
            if not coord:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "E2-2 success acknowledgment requires write coordination "
                        "(PUBLISH_WRITE_COORDINATION_ENABLED=false)"
                    ),
                )
            return
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported resolution action '{normalized_action}'. "
                f"Accepted: {ACTION_MARK_AMBIGUOUS}, "
                f"{ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS}."
            ),
        )

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
        external_post_id: str | None = None,
        external_post_url: str | None = None,
        observed_at: datetime | None = None,
        commit: bool = True,
    ) -> ManualResolutionResult:
        normalized_action = (action or "").strip().upper()
        if normalized_action not in ALLOWED_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported resolution action '{action}'. "
                    f"Accepted: {ACTION_MARK_AMBIGUOUS}, "
                    f"{ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS}."
                ),
            )

        cls._require_action_gate(normalized_action)

        if confirm_permanent_resolution is not True:
            raise HTTPException(
                status_code=400,
                detail=(
                    "confirm_permanent_resolution must be true. "
                    "Manual resolution permanently terminalizes the command "
                    "with no further retry execution."
                ),
            )

        if normalized_action == ACTION_MARK_AMBIGUOUS:
            reason = cls._normalize_operator_reason(operator_reason)
            evidence = cls._normalize_evidence_source(evidence_source)
            return await cls._resolve_mark_ambiguous(
                db,
                command_id=command_id,
                tenant_id=tenant_id,
                operator_reason=reason,
                evidence_source=evidence,
                actor_id=actor_id,
                actor_type=actor_type,
                commit=commit,
            )

        success_evidence = cls._normalize_success_evidence(
            operator_reason=operator_reason,
            evidence_source=evidence_source,
            external_post_id=external_post_id,
            external_post_url=external_post_url,
            observed_at=observed_at,
        )
        return await cls._resolve_ack_external_success(
            db,
            command_id=command_id,
            tenant_id=tenant_id,
            evidence=success_evidence,
            actor_id=actor_id,
            actor_type=actor_type,
            commit=commit,
        )

    # ── E2-1 MARK_AMBIGUOUS ──────────────────────────────────────────────────

    @classmethod
    async def _resolve_mark_ambiguous(
        cls,
        db: AsyncSession,
        *,
        command_id: UUID,
        tenant_id: UUID,
        operator_reason: str,
        evidence_source: str | None,
        actor_id: UUID | None,
        actor_type: str,
        commit: bool,
    ) -> ManualResolutionResult:
        command = await cls._lock_command(db, command_id, tenant_id)

        if (
            command.status == AMBIGUOUS_STATUS
            and (command.provider_outcome or "") == AMBIGUOUS_PROVIDER_OUTCOME
        ):
            return await cls._idempotent_ambiguous_already_resolved(db, command)

        cls._reject_non_entry_states(command)

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
        old_reason_code = command.reason_code

        command.status = AMBIGUOUS_STATUS
        command.provider_outcome = AMBIGUOUS_PROVIDER_OUTCOME
        command.finished_at = func.now()
        command.reason_code = REASON_CODE_MARK_AMBIGUOUS
        command.updated_at = func.now()

        attempt.status = AMBIGUOUS_ATTEMPT_STATUS
        attempt.retryable = False
        attempt.next_retry_at = None
        attempt.finished_at = func.now()

        await db.flush()

        audit_row = await cls._record_ambiguous_audit(
            db,
            command=command,
            attempt=attempt,
            actor_id=actor_id,
            actor_type=actor_type,
            operator_reason=operator_reason,
            evidence_source=evidence_source,
            old_status=old_status,
            old_provider_outcome=old_provider_outcome,
            old_reason_code=old_reason_code,
        )

        alert_resolved = await cls._resolve_stranded_alert_if_present(
            db,
            tenant_id=tenant_id,
            command_id=command.id,
            actor_id=actor_id,
            action=ACTION_MARK_AMBIGUOUS,
            terminal_status=AMBIGUOUS_STATUS,
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
            ACTION_MARK_AMBIGUOUS,
            command.id,
            attempt.id,
            tenant_id,
            alert_resolved,
        )

        return ManualResolutionResult(
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            status=command.status,
            provider_outcome=command.provider_outcome or AMBIGUOUS_PROVIDER_OUTCOME,
            attempt_status=attempt.status,
            resolution="applied",
            finished_at=command.finished_at,
            action=ACTION_MARK_AMBIGUOUS,
            audit_event_type=AUDIT_EVENT_MARK_AMBIGUOUS,
            audit_id=audit_row.id,
            correlation_id=command.correlation_id,
            alert_resolved=alert_resolved,
        )

    @classmethod
    async def _idempotent_ambiguous_already_resolved(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
    ) -> ManualResolutionResult:
        """Same-action E2-1 replay: no audit, no alert mutation, no timestamp rewrite."""
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
        attempt_status = (
            attempt.status if attempt is not None else AMBIGUOUS_ATTEMPT_STATUS
        )

        logger.info(
            "[RetryCmdManualResolve] already_resolved command_id=%s status=%s",
            command.id,
            command.status,
        )
        return ManualResolutionResult(
            command_id=command.id,
            resulting_attempt_id=command.resulting_attempt_id,
            status=command.status,
            provider_outcome=command.provider_outcome or AMBIGUOUS_PROVIDER_OUTCOME,
            attempt_status=attempt_status,
            resolution="already_resolved",
            finished_at=command.finished_at,
            action=ACTION_MARK_AMBIGUOUS,
            audit_event_type=None,
            audit_id=None,
            correlation_id=command.correlation_id,
            alert_resolved=False,
        )

    # ── E2-2 ACKNOWLEDGE_EXTERNAL_SUCCESS ────────────────────────────────────

    @classmethod
    async def _resolve_ack_external_success(
        cls,
        db: AsyncSession,
        *,
        command_id: UUID,
        tenant_id: UUID,
        evidence: _SuccessEvidence,
        actor_id: UUID | None,
        actor_type: str,
        commit: bool,
    ) -> ManualResolutionResult:
        from app.services.publish_write_coordination import (
            PUBLICATION_IN_PROGRESS_ERROR,
            acquire_destination_xact_lock,
            find_destination_in_progress_attempt,
            normalize_destination,
        )

        # Destination lock first (same order as publish claim critical section), then
        # command / resulting-attempt FOR UPDATE.
        # We need destination fields before locking: load without FOR UPDATE,
        # acquire destination lock, then re-lock and re-validate.
        preview = (
            await db.execute(
                select(PublishRetryCommand).where(
                    PublishRetryCommand.id == command_id,
                    PublishRetryCommand.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if preview is None:
            raise HTTPException(status_code=404, detail="Retry command not found")

        identity = normalize_destination(
            tenant_id=tenant_id,
            content_id=preview.content_id,
            platform=preview.platform,
            account_id=preview.publishing_account_id,
        )
        await acquire_destination_xact_lock(db, identity)

        command = await cls._lock_command(db, command_id, tenant_id)

        # Re-validate destination identity after locks (fail closed on drift).
        if (
            command.content_id != identity.content_id
            or (command.platform or "").strip().lower() != identity.platform_normalized
            or command.publishing_account_id != identity.account_id
            or command.tenant_id != identity.tenant_id
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": (
                        "Command destination identity changed under lock; "
                        "failing closed"
                    ),
                },
            )

        if command.status == SUCCESS_STATUS and (
            command.provider_outcome or ""
        ) == SUCCESS_PROVIDER_OUTCOME:
            # Compatible replay: do not apply first-application conflict checks.
            return await cls._replay_ack_external_success(
                db,
                command=command,
                evidence=evidence,
            )

        cls._reject_non_entry_states(command)

        if command.resulting_attempt_id is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": "resulting_attempt_id is required for resolution",
                },
            )

        # Competing same-destination in_progress (any version) → 409, no mutation.
        competing = await find_destination_in_progress_attempt(db, identity)
        if competing is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": PUBLICATION_IN_PROGRESS_ERROR,
                    "message": (
                        "Same-destination publish claim is in progress; "
                        "acknowledge after it finishes or is reconciled"
                    ),
                    "status": command.status,
                    "attempt_id": str(competing.id),
                },
            )

        attempt = await cls._lock_resulting_attempt(db, command)
        cls._validate_bidirectional_lineage(command, attempt)
        cls._validate_write_started_attempt_lifecycle(attempt)
        cls._reject_external_id_conflict(attempt, evidence.external_post_id)

        old_status = command.status
        old_provider_outcome = command.provider_outcome
        old_reason_code = command.reason_code

        # Preserve forensic lease/claim/barrier timestamps; set terminal success.
        command.status = SUCCESS_STATUS
        command.provider_outcome = SUCCESS_PROVIDER_OUTCOME
        command.reason_code = REASON_CODE_ACK_EXTERNAL_SUCCESS
        command.finished_at = func.now()
        command.updated_at = func.now()

        attempt.status = SUCCESS_ATTEMPT_STATUS
        attempt.external_post_id = evidence.external_post_id
        attempt.external_post_url = evidence.external_post_url
        attempt.failure_code = None
        attempt.failure_category = None
        attempt.error = None
        attempt.retryable = False
        attempt.next_retry_at = None
        attempt.finished_at = func.now()
        # Do not invent attempt.response JSON.

        await db.flush()

        audit_row = await cls._record_success_audit(
            db,
            command=command,
            attempt=attempt,
            actor_id=actor_id,
            actor_type=actor_type,
            evidence=evidence,
            old_status=old_status,
            old_provider_outcome=old_provider_outcome,
            old_reason_code=old_reason_code,
        )

        alert_resolved = await cls._resolve_stranded_alert_if_present(
            db,
            tenant_id=tenant_id,
            command_id=command.id,
            actor_id=actor_id,
            action=ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
            terminal_status=SUCCESS_STATUS,
        )

        await db.refresh(
            command,
            attribute_names=[
                "status",
                "provider_outcome",
                "reason_code",
                "finished_at",
                "updated_at",
            ],
        )
        await db.refresh(
            attempt,
            attribute_names=[
                "status",
                "retryable",
                "next_retry_at",
                "finished_at",
                "external_post_id",
                "external_post_url",
                "failure_code",
                "failure_category",
                "error",
                "response",
            ],
        )

        if commit:
            await db.commit()
            await db.refresh(command, attribute_names=["finished_at", "reason_code"])
            await db.refresh(
                attempt,
                attribute_names=["finished_at", "status", "external_post_id"],
            )

        logger.info(
            "[RetryCmdManualResolve] applied action=%s command_id=%s "
            "attempt_id=%s tenant_id=%s alert_resolved=%s "
            "provenance=operator_attested_no_provider_io",
            ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
            command.id,
            attempt.id,
            tenant_id,
            alert_resolved,
        )

        return ManualResolutionResult(
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            status=command.status,
            provider_outcome=command.provider_outcome or SUCCESS_PROVIDER_OUTCOME,
            attempt_status=attempt.status,
            resolution="applied",
            finished_at=command.finished_at,
            action=ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
            audit_event_type=AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
            audit_id=audit_row.id,
            correlation_id=command.correlation_id,
            alert_resolved=alert_resolved,
            external_post_id=attempt.external_post_id,
        )

    @classmethod
    async def _replay_ack_external_success(
        cls,
        db: AsyncSession,
        *,
        command: PublishRetryCommand,
        evidence: _SuccessEvidence,
    ) -> ManualResolutionResult:
        """Compatible manual replay only — never fabricate audit for executor terminals."""
        if (command.reason_code or "") != REASON_CODE_ACK_EXTERNAL_SUCCESS:
            # Executor/finalizer (or other) success: not a manual replay.
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "already_resolved",
                    "message": (
                        "Command is already terminal (succeeded); "
                        "executor-produced success is not a manual replay"
                    ),
                    "status": command.status,
                    "provider_outcome": command.provider_outcome,
                    "reason_code": command.reason_code,
                },
            )

        if command.resulting_attempt_id is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": (
                        "Terminal success command missing resulting_attempt_id"
                    ),
                },
            )

        attempt = await cls._lock_resulting_attempt(db, command)
        cls._validate_bidirectional_lineage(command, attempt)

        if attempt.status != SUCCESS_ATTEMPT_STATUS:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": (
                        "Resulting attempt status inconsistent with manual "
                        "success terminal"
                    ),
                    "attempt_status": attempt.status,
                },
            )
        if (attempt.external_post_id or "").strip() != evidence.external_post_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "evidence_conflict",
                    "message": (
                        "Replay external_post_id does not match durable "
                        "attempt identity"
                    ),
                },
            )

        audit = await cls._load_authoritative_success_audit(db, command, attempt)
        cls._assert_replay_evidence_matches(audit, evidence)

        logger.info(
            "[RetryCmdManualResolve] already_resolved action=%s "
            "command_id=%s audit_id=%s",
            ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
            command.id,
            audit.id,
        )
        return ManualResolutionResult(
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            status=command.status,
            provider_outcome=command.provider_outcome or SUCCESS_PROVIDER_OUTCOME,
            attempt_status=attempt.status,
            resolution="already_resolved",
            finished_at=command.finished_at,
            action=ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
            audit_event_type=AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
            audit_id=audit.id,
            correlation_id=command.correlation_id,
            alert_resolved=False,
            external_post_id=attempt.external_post_id,
        )

    @classmethod
    async def _load_authoritative_success_audit(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
    ) -> PlatformAuditLog:
        """Fail closed on candidate cardinality before details validation.

        Candidates are scoped only by tenant + resource + manual-success
        event_type. Filtering by details *before* uniqueness would silently
        discard contradictory rows and accept a remaining valid sibling —
        which must never authorize replay.
        """
        candidates = (
            await db.execute(
                select(PlatformAuditLog).where(
                    PlatformAuditLog.tenant_id == command.tenant_id,
                    PlatformAuditLog.resource_type == "publish_retry_command",
                    PlatformAuditLog.resource_id == str(command.id),
                    PlatformAuditLog.event_type == AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
                ),
            )
        ).scalars().all()

        if len(candidates) == 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "evidence_conflict",
                    "message": (
                        "Manual success reason_code present but authoritative "
                        "applied audit provenance is missing"
                    ),
                },
            )
        if len(candidates) > 1:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "evidence_conflict",
                    "message": (
                        "Multiple manual success audit candidate rows for the "
                        "same tenant/resource/event; failing closed"
                    ),
                },
            )

        audit = candidates[0]
        cls._assert_success_audit_provenance_consistent(audit, command, attempt)
        return audit

    @classmethod
    def _assert_success_audit_provenance_consistent(
        cls,
        audit: PlatformAuditLog,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
    ) -> None:
        """Validate the single candidate; never authorize other-tenant rows."""
        if audit.tenant_id != command.tenant_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "evidence_conflict",
                    "message": (
                        "Audit tenant does not match command tenant; "
                        "failing closed"
                    ),
                },
            )

        details = audit.details if isinstance(audit.details, dict) else None
        if details is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "evidence_conflict",
                    "message": (
                        "Authoritative manual success audit details are "
                        "missing or malformed"
                    ),
                },
            )

        expected = {
            "action": ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
            "provenance": "manual_resolution_e2_2",
            "tenant_id": str(command.tenant_id),
            "command_id": str(command.id),
            "original_attempt_id": str(command.original_attempt_id),
            "resulting_attempt_id": str(attempt.id),
            "new_status": SUCCESS_STATUS,
            "new_provider_outcome": SUCCESS_PROVIDER_OUTCOME,
            "new_reason_code": REASON_CODE_ACK_EXTERNAL_SUCCESS,
            "attempt_status": SUCCESS_ATTEMPT_STATUS,
        }
        mismatches: list[str] = []
        for key, expected_value in expected.items():
            if details.get(key) != expected_value:
                mismatches.append(key)

        if mismatches:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "evidence_conflict",
                    "message": (
                        "Authoritative manual success audit provenance is "
                        f"inconsistent ({', '.join(mismatches)})"
                    ),
                    "mismatched_fields": mismatches,
                },
            )

    @classmethod
    def _assert_replay_evidence_matches(
        cls,
        audit: PlatformAuditLog,
        evidence: _SuccessEvidence,
    ) -> None:
        details = audit.details if isinstance(audit.details, dict) else {}

        stored_reason = str(details.get("operator_reason") or "").strip()
        stored_source = str(details.get("evidence_source") or "").strip()
        stored_id = str(details.get("external_post_id") or "").strip()
        stored_url = cls._canonical_optional_url(details.get("external_post_url"))
        stored_observed = cls._canonical_observed_at(details.get("observed_at"))

        request_url = cls._canonical_optional_url(evidence.external_post_url)
        request_observed = cls._canonical_observed_at(evidence.observed_at)

        mismatches: list[str] = []
        if stored_reason != evidence.operator_reason:
            mismatches.append("operator_reason")
        if stored_source != evidence.evidence_source:
            mismatches.append("evidence_source")
        if stored_id != evidence.external_post_id:
            mismatches.append("external_post_id")
        if stored_url != request_url:
            mismatches.append("external_post_url")
        if stored_observed != request_observed:
            mismatches.append("observed_at")

        if mismatches:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "evidence_conflict",
                    "message": (
                        "Replay evidence does not match authoritative manual "
                        f"audit ({', '.join(mismatches)})"
                    ),
                    "mismatched_fields": mismatches,
                },
            )

    @classmethod
    def _canonical_optional_url(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def _canonical_observed_at(cls, value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value).strip()
            if not text:
                return None
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(text)
            except ValueError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "evidence_conflict",
                        "message": "Stored or request observed_at is not parseable",
                    },
                ) from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")

    @classmethod
    def _validate_write_started_attempt_lifecycle(
        cls,
        attempt: PublishAttempt,
    ) -> None:
        """Require post-barrier pre-finalize markers; never overwrite foreign terminals."""
        if attempt.status in (STATUS_SUCCESS, "failed") and attempt.finished_at is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": (
                        "Resulting attempt is independently terminal while "
                        "command is still provider_write_started"
                    ),
                    "attempt_status": attempt.status,
                },
            )
        if attempt.status != WRITE_STARTED_ATTEMPT_STATUS:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": (
                        "Resulting attempt is not in expected write-started "
                        f"lifecycle (got {attempt.status})"
                    ),
                    "attempt_status": attempt.status,
                },
            )
        if (attempt.failure_code or "") != WRITE_STARTED_FAILURE_CODE:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": (
                        "Resulting attempt failure_code must be "
                        f"{WRITE_STARTED_FAILURE_CODE}"
                    ),
                },
            )
        if attempt.retryable is not False:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": "Resulting attempt must have retryable=false",
                },
            )
        if attempt.next_retry_at is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "lineage_conflict",
                    "message": "Resulting attempt next_retry_at must be null",
                },
            )

    @classmethod
    def _reject_external_id_conflict(
        cls,
        attempt: PublishAttempt,
        external_post_id: str,
    ) -> None:
        existing = (attempt.external_post_id or "").strip()
        if existing and existing != external_post_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "evidence_conflict",
                    "message": (
                        "Resulting attempt already has a different durable "
                        "external_post_id"
                    ),
                    "existing_external_post_id": existing,
                },
            )

    # ── Shared helpers ───────────────────────────────────────────────────────

    @classmethod
    def _reject_non_entry_states(cls, command: PublishRetryCommand) -> None:
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
    async def _record_ambiguous_audit(
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
        old_reason_code: str | None,
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
            "old_reason_code": old_reason_code,
            "new_reason_code": command.reason_code,
            "action": ACTION_MARK_AMBIGUOUS,
            "operator_reason": operator_reason,
            "evidence_source": evidence_source,
            "correlation_id": command.correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt_status": attempt.status,
        }
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
    async def _record_success_audit(
        cls,
        db: AsyncSession,
        *,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
        actor_id: UUID | None,
        actor_type: str,
        evidence: _SuccessEvidence,
        old_status: str,
        old_provider_outcome: str | None,
        old_reason_code: str | None,
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
            "old_reason_code": old_reason_code,
            "new_reason_code": command.reason_code,
            "action": ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
            "operator_reason": evidence.operator_reason,
            "evidence_source": evidence.evidence_source,
            "external_post_id": evidence.external_post_id,
            "external_post_url": evidence.external_post_url,
            "observed_at": (
                cls._canonical_observed_at(evidence.observed_at)
                if evidence.observed_at is not None
                else None
            ),
            "attempt_status": attempt.status,
            "attempt_external_post_id": attempt.external_post_id,
            "attempt_external_post_url": attempt.external_post_url,
            "correlation_id": command.correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "content_repair": "skipped_unsafe_aggregate",
            "publication_repair": "deferred_minimal_e2_2",
            "provenance": "manual_resolution_e2_2",
            # Explicit: operator attestation only — no provider I/O in E2-2.
            "evidence_attestation": "operator_attested_unverified",
        }
        return await PlatformAuditService.record(
            db,
            actor_type=actor_type if actor_id else "system",
            actor_id=actor_id,
            tenant_id=command.tenant_id,
            event_type=AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
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
        action: str,
        terminal_status: str,
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
            f"{action} command_id={command_id} "
            f"terminal_status={terminal_status}"
        )
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

    @classmethod
    def _normalize_success_evidence(
        cls,
        *,
        operator_reason: str,
        evidence_source: str | None,
        external_post_id: str | None,
        external_post_url: str | None,
        observed_at: datetime | None,
    ) -> _SuccessEvidence:
        reason = cls._normalize_operator_reason(operator_reason)

        if evidence_source is None or not str(evidence_source).strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "evidence_insufficient",
                    "message": (
                        "evidence_source is required for "
                        f"{ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS}"
                    ),
                },
            )
        source = str(evidence_source).strip()
        if len(source) > EVIDENCE_SOURCE_MAX_LEN:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "evidence_insufficient",
                    "message": (
                        f"evidence_source exceeds maximum length "
                        f"({EVIDENCE_SOURCE_MAX_LEN})"
                    ),
                },
            )

        if external_post_id is None or not str(external_post_id).strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "evidence_insufficient",
                    "message": (
                        "external_post_id is required for "
                        f"{ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS}"
                    ),
                },
            )
        post_id = str(external_post_id).strip()
        if len(post_id) > EXTERNAL_POST_ID_MAX_LEN:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "evidence_insufficient",
                    "message": (
                        f"external_post_id exceeds maximum length "
                        f"({EXTERNAL_POST_ID_MAX_LEN}); input is not truncated"
                    ),
                },
            )

        url = cls._normalize_external_post_url(external_post_url)
        observed = cls._normalize_observed_at(observed_at)

        return _SuccessEvidence(
            operator_reason=reason,
            evidence_source=source,
            external_post_id=post_id,
            external_post_url=url,
            observed_at=observed,
        )

    @classmethod
    def _normalize_external_post_url(cls, external_post_url: str | None) -> str | None:
        if external_post_url is None:
            return None
        text = str(external_post_url).strip()
        if not text:
            return None
        if len(text) > EXTERNAL_POST_URL_MAX_LEN:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "evidence_insufficient",
                    "message": (
                        f"external_post_url exceeds maximum length "
                        f"({EXTERNAL_POST_URL_MAX_LEN})"
                    ),
                },
            )
        if any(marker in text for marker in _SIGNED_URL_MARKERS):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "evidence_insufficient",
                    "message": "external_post_url must not contain signed-URL markers",
                },
            )
        parsed = urlparse(text)
        if parsed.scheme.lower() not in _SAFE_PERMALINK_SCHEMES:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "evidence_insufficient",
                    "message": "external_post_url must be http or https",
                },
            )
        if not parsed.netloc:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "evidence_insufficient",
                    "message": "external_post_url must include a network location",
                },
            )
        # Reference only — never fetched.
        return text

    @classmethod
    def _normalize_observed_at(cls, observed_at: datetime | None) -> datetime | None:
        if observed_at is None:
            return None
        if observed_at.tzinfo is None:
            return observed_at.replace(tzinfo=timezone.utc)
        return observed_at.astimezone(timezone.utc)
