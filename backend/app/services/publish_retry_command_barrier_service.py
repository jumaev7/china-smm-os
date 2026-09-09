"""Publish retry-command DB-only write barrier (Phase 3C.1C-D1).

Canonical durable transition after preparation, before any provider I/O:

  claimed + prepared command
  → FOR UPDATE lock + ownership/lease validation
  → revalidate feature gates inside the transaction
  → validate linked prepared attempt + original lineage
  → eligibility + live-success revalidation
  → atomically mark command + attempt post-barrier
  → COMMIT
  → STOP

Never calls PublishService.publish_content, adapters, begin_attempt,
finalize_attempt, fake providers, or provider HTTP.

Post-barrier attempt remains ``operator_review`` with forensic failure_code
``retry_command_write_started`` so automatic retry / claim / stale-recovery
selectors (which key on ``retrying`` / ``in_progress``) cannot adopt it.

Reachability
------------
Not wired into PublishRetryCommandWorker. Callable only as an explicit
internal/test entrypoint. ``barrier_gates_open`` requires COMMANDS + WORKER +
CLAIM + EXECUTION so accidental production calls fail closed while flags
remain false.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import (
    RETRY_COMMAND_TERMINAL_STATUSES,
    PublishRetryCommand,
)
from app.models.publishing_account import PublishingAccount
from app.services import publish_retry_command_metrics as barrier_metrics
from app.services.manual_retry_eligibility import (
    build_manual_retry_live_state,
    evaluate_manual_retry_eligibility,
    log_manual_retry_denied,
)
from app.services.publish_retry_command_eligibility import (
    RetryCommandEligibilityContext,
    RetryCommandEligibilityEvaluator,
    default_eligibility_evaluator,
    synthetic_tenant_marker,
)
from app.services.platform_audit_service import PlatformAuditService
from app.services.publish_resilience import (
    STATUS_OPERATOR_REVIEW,
    PublishResilienceService,
    build_idempotency_key,
)
from app.services.publish_retry_command_claim_service import scrubbed_worker_instance
from app.services.publish_retry_command_preparation_service import (
    PREPARED_FAILURE_CODE,
)
from app.services.publishing_tenant_scope import tenant_id_for_content_optional

logger = logging.getLogger(__name__)

# Post-barrier forensic markers — attempt stays non-auto-executable.
WRITE_STARTED_ATTEMPT_STATUS = STATUS_OPERATOR_REVIEW
WRITE_STARTED_FAILURE_CODE = "retry_command_write_started"
WRITE_STARTED_FAILURE_CATEGORY = "command_orchestration"
WRITE_STARTED_ATTEMPT_ERROR = (
    "Retry-command write barrier crossed; provider write not yet executed"
)

BarrierOutcome = Literal[
    "barrier_crossed",
    "already_barriered",
    "blocked_ineligible",
    "blocked_newer_success",
    "blocked_lease_or_ownership",
    "blocked_terminal",
    "invariant_violation",
    "disabled",
]


@dataclass(frozen=True)
class BarrierResult:
    """Structured DB-only barrier outcome. No provider payloads."""

    ok: bool
    outcome: BarrierOutcome
    command_id: UUID | None = None
    resulting_attempt_id: UUID | None = None
    original_attempt_id: UUID | None = None
    reason_code: str | None = None
    message: str | None = None
    eligibility_reason_code: str | None = None
    safety_class: str | None = None
    newer_success_attempt_id: UUID | None = None
    correlation_id: str | None = None
    tenant_id: UUID | None = None
    platform: str | None = None
    requested_source: str | None = None
    previous_command_status: str | None = None
    command_status: str | None = None
    provider_write_started_at_is_null: bool = True
    lease_expires_at_is_null: bool | None = None
    lease_owner_preserved: bool | None = None


def barrier_gates_open() -> tuple[bool, str]:
    """Return (allowed, reason) for write-barrier mutations.

    All four flags required. EXECUTION must be true to cross the barrier;
    earlier caller checks are not sufficient.
    """
    if not settings.PUBLISH_RETRY_COMMANDS_ENABLED:
        return False, "commands_disabled"
    if not settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED:
        return False, "worker_disabled"
    if not settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED:
        return False, "claim_disabled"
    if not settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED:
        return False, "execution_disabled"
    return True, "ok"


class PublishRetryCommandBarrierService:
    """DB-only claimed+prepared → provider_write_started barrier.

    Constructor default uses CanonicalManualRetryEligibility. Staging behavior
    requires explicit evaluator injection — never derived from APP_ENV.
    """

    def __init__(
        self,
        eligibility_evaluator: RetryCommandEligibilityEvaluator | None = None,
    ) -> None:
        self.eligibility_evaluator = (
            eligibility_evaluator
            if eligibility_evaluator is not None
            else default_eligibility_evaluator()
        )

    @classmethod
    async def cross_barrier(
        cls,
        db: AsyncSession,
        *,
        command_id: UUID,
        worker_id: str,
        correlation_id: str | None = None,
        commit: bool = True,
        eligibility_evaluator: RetryCommandEligibilityEvaluator | None = None,
    ) -> BarrierResult:
        """Cross the write barrier: validate, mutate, commit, stop.

        Loads canonical DB state itself. Does not trust caller-supplied
        platform, tenant, attempt/command status, provider state, or eligibility.
        """
        allowed, gate_reason = barrier_gates_open()
        if not allowed:
            barrier_metrics.inc("retry_command_barrier_denied_total")
            return BarrierResult(
                ok=False,
                outcome="disabled",
                command_id=command_id,
                reason_code=gate_reason,
                message="Retry command write barrier is disabled",
            )

        evaluator = eligibility_evaluator
        try:
            result = await cls._cross_locked(
                db,
                command_id=command_id,
                worker_id=worker_id,
                correlation_id=correlation_id,
                eligibility_evaluator=evaluator,
            )
            if commit:
                await db.commit()
            else:
                await db.flush()
        except Exception:
            barrier_metrics.inc("retry_command_barrier_invariant_error_total")
            logger.exception(
                "[RetryCommandBarrier] failed command_id=%s worker=%s",
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
    async def cross_barrier_and_audit(
        cls,
        db: AsyncSession,
        session_factory,
        *,
        command_id: UUID,
        worker_id: str,
        correlation_id: str | None = None,
        eligibility_evaluator: RetryCommandEligibilityEvaluator | None = None,
    ) -> BarrierResult:
        """Cross barrier with commit, then best-effort audit in a separate session."""
        result = await cls.cross_barrier(
            db,
            command_id=command_id,
            worker_id=worker_id,
            correlation_id=correlation_id,
            commit=True,
            eligibility_evaluator=eligibility_evaluator,
        )
        await cls.record_barrier_audit(
            session_factory,
            result,
            worker_id=worker_id,
        )
        return result

    @classmethod
    async def _cross_locked(
        cls,
        db: AsyncSession,
        *,
        command_id: UUID,
        worker_id: str,
        correlation_id: str | None,
        eligibility_evaluator: RetryCommandEligibilityEvaluator | None,
    ) -> BarrierResult:
        # Revalidate gates inside the locked path (defense in depth).
        allowed, gate_reason = barrier_gates_open()
        if not allowed:
            return BarrierResult(
                ok=False,
                outcome="disabled",
                command_id=command_id,
                reason_code=gate_reason,
                message="Retry command write barrier is disabled",
            )

        command = (
            await db.scalars(
                select(PublishRetryCommand)
                .where(PublishRetryCommand.id == command_id)
                .with_for_update(),
            )
        ).first()
        if command is None:
            return cls._invariant(
                command_id=command_id,
                reason_code="command_not_found",
                message="Retry command not found",
            )

        corr = correlation_id or command.correlation_id
        previous_status = command.status

        # At-most-once: already post-barrier → idempotent deny, no rewrite.
        if (
            command.status == "provider_write_started"
            or command.provider_write_started_at is not None
        ):
            return BarrierResult(
                ok=False,
                outcome="already_barriered",
                command_id=command.id,
                resulting_attempt_id=command.resulting_attempt_id,
                original_attempt_id=command.original_attempt_id,
                reason_code="already_barriered",
                message="Command has already crossed the provider write barrier",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                previous_command_status=previous_status,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
                lease_expires_at_is_null=command.lease_expires_at is None,
                lease_owner_preserved=True,
            )

        if command.status in RETRY_COMMAND_TERMINAL_STATUSES:
            return BarrierResult(
                ok=False,
                outcome="blocked_terminal",
                command_id=command.id,
                reason_code="terminal_command",
                message=f"Command is terminal ({command.status})",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                previous_command_status=previous_status,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
            )

        ownership = await cls._validate_ownership_and_lease(
            db, command, worker_id=worker_id, correlation_id=corr,
        )
        if ownership is not None:
            return ownership

        if command.resulting_attempt_id is None:
            return cls._invariant(
                command_id=command.id,
                reason_code="missing_resulting_attempt",
                message="resulting_attempt_id is required before write barrier",
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
            )

        lineage = await cls._load_and_validate_original_lineage(db, command)
        if isinstance(lineage, BarrierResult):
            return lineage
        original, content, client, account = lineage

        linked = await cls._load_and_validate_linked_attempt(db, command)
        if isinstance(linked, BarrierResult):
            return linked
        attempt = linked

        # Eligibility against ORIGINAL attempt.
        # Default path uses module-global evaluate_manual_retry_eligibility
        # (patch-compatible). Injected staging evaluators bypass.
        live_state = await build_manual_retry_live_state(db, original, content=content)
        source = (command.requested_source or "admin").strip().lower()
        source_norm = source if source != "api" else "admin"
        if eligibility_evaluator is None:
            eligibility = evaluate_manual_retry_eligibility(
                original,
                live_state,
                source=source_norm,
            )
        else:
            eligibility = eligibility_evaluator.evaluate(
                RetryCommandEligibilityContext(
                    attempt=original,
                    live_state=live_state,
                    source=source_norm,
                    correlation_id=corr,
                    tenant_company_name=synthetic_tenant_marker(client),
                    command_id=command.id,
                    tenant_id=command.tenant_id,
                ),
            )
        if not eligibility.allowed:
            log_manual_retry_denied(
                eligibility,
                attempt_id=original.id,
                tenant_id=command.tenant_id,
                source=source,
            )
            return BarrierResult(
                ok=False,
                outcome="blocked_ineligible",
                command_id=command.id,
                resulting_attempt_id=command.resulting_attempt_id,
                original_attempt_id=command.original_attempt_id,
                reason_code=eligibility.reason_code,
                message=eligibility.operator_message or "Manual retry unavailable",
                eligibility_reason_code=eligibility.reason_code,
                safety_class=eligibility.safety_class,
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                previous_command_status=previous_status,
                command_status=command.status,
                provider_write_started_at_is_null=True,
            )

        newer = await cls._find_newer_success(db, command, original)
        if newer is not None:
            return BarrierResult(
                ok=False,
                outcome="blocked_newer_success",
                command_id=command.id,
                resulting_attempt_id=command.resulting_attempt_id,
                original_attempt_id=command.original_attempt_id,
                reason_code="newer_success",
                message="Authoritative live success exists; write barrier denied",
                newer_success_attempt_id=newer.id,
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                previous_command_status=previous_status,
                command_status=command.status,
                provider_write_started_at_is_null=True,
            )

        del account  # validated; not needed for mutation
        await cls._apply_barrier_mutation(db, command, attempt)
        await db.flush()
        await db.refresh(
            command,
            attribute_names=[
                "status",
                "provider_write_started_at",
                "lease_expires_at",
                "lease_owner",
                "started_at",
                "claimed_at",
                "resulting_attempt_id",
                "updated_at",
            ],
        )
        await db.refresh(
            attempt,
            attribute_names=[
                "status",
                "failure_code",
                "failure_category",
                "retryable",
                "next_retry_at",
                "finished_at",
                "error",
                "external_post_id",
                "external_post_url",
            ],
        )

        return BarrierResult(
            ok=True,
            outcome="barrier_crossed",
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            original_attempt_id=command.original_attempt_id,
            reason_code="barrier_crossed",
            message="Retry command crossed the DB write barrier",
            correlation_id=corr,
            tenant_id=command.tenant_id,
            platform=command.platform,
            requested_source=command.requested_source,
            previous_command_status=previous_status,
            command_status=command.status,
            provider_write_started_at_is_null=command.provider_write_started_at is None,
            lease_expires_at_is_null=command.lease_expires_at is None,
            lease_owner_preserved=command.lease_owner == worker_id,
        )

    @classmethod
    async def _validate_ownership_and_lease(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        *,
        worker_id: str,
        correlation_id: str | None,
    ) -> BarrierResult | None:
        """Fail closed unless claimed by this worker with a non-expired lease."""
        if command.status != "claimed":
            return BarrierResult(
                ok=False,
                outcome="blocked_lease_or_ownership",
                command_id=command.id,
                reason_code="not_claimed",
                message=f"Command status must be claimed (got {command.status})",
                correlation_id=correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                previous_command_status=command.status,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
            )
        if command.lease_owner != worker_id:
            return BarrierResult(
                ok=False,
                outcome="blocked_lease_or_ownership",
                command_id=command.id,
                reason_code="lease_owner_mismatch",
                message="Command lease owner does not match current worker",
                correlation_id=correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                previous_command_status=command.status,
                command_status=command.status,
                provider_write_started_at_is_null=True,
            )
        if command.lease_expires_at is None:
            return BarrierResult(
                ok=False,
                outcome="blocked_lease_or_ownership",
                command_id=command.id,
                reason_code="lease_missing",
                message="Command has no lease expiry",
                correlation_id=correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                previous_command_status=command.status,
                command_status=command.status,
                provider_write_started_at_is_null=True,
            )

        expired = (
            await db.execute(
                select(
                    PublishRetryCommand.lease_expires_at < func.now(),
                ).where(PublishRetryCommand.id == command.id),
            )
        ).scalar_one()
        if expired:
            return BarrierResult(
                ok=False,
                outcome="blocked_lease_or_ownership",
                command_id=command.id,
                reason_code="lease_expired",
                message="Command lease has expired",
                correlation_id=correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                previous_command_status=command.status,
                command_status=command.status,
                provider_write_started_at_is_null=True,
            )
        return None

    @classmethod
    async def _load_and_validate_original_lineage(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
    ) -> (
        tuple[PublishAttempt, ContentItem, Client, PublishingAccount | None]
        | BarrierResult
    ):
        original = (
            await db.execute(
                select(PublishAttempt).where(
                    PublishAttempt.id == command.original_attempt_id,
                ),
            )
        ).scalar_one_or_none()
        if original is None:
            return cls._invariant(
                command_id=command.id,
                reason_code="original_attempt_missing",
                message="Original PublishAttempt not found",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
            )

        row = (
            await db.execute(
                select(ContentItem, Client)
                .join(Client, Client.id == ContentItem.client_id)
                .where(ContentItem.id == command.content_id)
                .options(
                    load_only(
                        ContentItem.id,
                        ContentItem.client_id,
                        ContentItem.status,
                        ContentItem.caption_long_ru,
                        ContentItem.caption_long_en,
                        ContentItem.caption_short_ru,
                        ContentItem.hashtags,
                        ContentItem.media_file_id,
                        ContentItem.platforms,
                        ContentItem.updated_at,
                    ),
                    load_only(Client.id, Client.tenant_id, Client.company_name),
                ),
            )
        ).one_or_none()
        if row is None:
            return cls._invariant(
                command_id=command.id,
                reason_code="content_missing",
                message="Command content not found",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
            )
        content, client = row

        content_tenant = await tenant_id_for_content_optional(db, content)
        if (
            command.tenant_id != client.tenant_id
            or content_tenant != command.tenant_id
            or original.content_id != command.content_id
            or content.client_id != command.client_id
            or content.client_id != client.id
        ):
            return cls._invariant(
                command_id=command.id,
                reason_code="tenant_lineage_mismatch",
                message="Tenant/content lineage mismatch — fail closed",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
            )

        if (original.platform or "").strip().lower() != (command.platform or "").strip().lower():
            return cls._invariant(
                command_id=command.id,
                reason_code="platform_lineage_mismatch",
                message="Original attempt platform does not match command",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
            )

        if original.account_id != command.publishing_account_id:
            return cls._invariant(
                command_id=command.id,
                reason_code="account_lineage_mismatch",
                message="Original attempt account does not match command",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
            )

        orig_version = (original.publish_version or "").strip() or "unknown"
        if orig_version != (command.publish_version or "").strip():
            return cls._invariant(
                command_id=command.id,
                reason_code="publish_version_mismatch",
                message="Original attempt publish_version does not match command",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
            )

        account: PublishingAccount | None = None
        if command.publishing_account_id is not None:
            account = (
                await db.execute(
                    select(PublishingAccount)
                    .where(PublishingAccount.id == command.publishing_account_id)
                    .options(
                        load_only(
                            PublishingAccount.id,
                            PublishingAccount.tenant_id,
                            PublishingAccount.platform,
                            PublishingAccount.status,
                            PublishingAccount.account_name,
                        ),
                    ),
                )
            ).scalar_one_or_none()
            if account is None:
                return cls._invariant(
                    command_id=command.id,
                    reason_code="account_missing",
                    message="Publishing account not found",
                    correlation_id=command.correlation_id,
                    tenant_id=command.tenant_id,
                    platform=command.platform,
                )
            if account.tenant_id != command.tenant_id:
                return cls._invariant(
                    command_id=command.id,
                    reason_code="account_tenant_mismatch",
                    message="Account tenant does not match command — fail closed",
                    correlation_id=command.correlation_id,
                    tenant_id=command.tenant_id,
                    platform=command.platform,
                )
            if (account.platform or "").strip().lower() != (command.platform or "").strip().lower():
                return cls._invariant(
                    command_id=command.id,
                    reason_code="account_platform_mismatch",
                    message="Account platform does not match command",
                    correlation_id=command.correlation_id,
                    tenant_id=command.tenant_id,
                    platform=command.platform,
                )

        if account is not None:
            original.account = account

        return original, content, client, account

    @classmethod
    async def _load_and_validate_linked_attempt(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
    ) -> PublishAttempt | BarrierResult:
        attempt = await db.get(PublishAttempt, command.resulting_attempt_id)
        if attempt is None:
            return cls._invariant(
                command_id=command.id,
                reason_code="resulting_attempt_missing",
                message="resulting_attempt_id points to missing attempt",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
            )
        if attempt.retry_command_id != command.id:
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="bidirectional_lineage_broken",
                message=(
                    "command.resulting_attempt_id set but attempt.retry_command_id "
                    "does not match — fail closed"
                ),
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
            )

        if attempt.content_id != command.content_id:
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="linked_attempt_content_mismatch",
                message="Linked attempt content_id mismatch — fail closed",
                tenant_id=command.tenant_id,
                platform=command.platform,
                correlation_id=command.correlation_id,
            )
        if (attempt.platform or "").strip().lower() != (command.platform or "").strip().lower():
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="linked_attempt_platform_mismatch",
                message="Linked attempt platform mismatch — fail closed",
                tenant_id=command.tenant_id,
                platform=command.platform,
                correlation_id=command.correlation_id,
            )
        if attempt.account_id != command.publishing_account_id:
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="linked_attempt_account_mismatch",
                message="Linked attempt account mismatch — fail closed",
                tenant_id=command.tenant_id,
                platform=command.platform,
                correlation_id=command.correlation_id,
            )
        attempt_version = (attempt.publish_version or "").strip() or "unknown"
        if attempt_version != (command.publish_version or "").strip():
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="linked_attempt_version_mismatch",
                message="Linked attempt publish_version mismatch — fail closed",
                tenant_id=command.tenant_id,
                platform=command.platform,
                correlation_id=command.correlation_id,
            )

        # Exact C prepared state required — do not repair in D1.
        if attempt.status != STATUS_OPERATOR_REVIEW:
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="linked_attempt_status_mismatch",
                message=(
                    f"Linked attempt must be operator_review "
                    f"(got {attempt.status})"
                ),
                tenant_id=command.tenant_id,
                platform=command.platform,
                correlation_id=command.correlation_id,
            )
        if (attempt.failure_code or "") != PREPARED_FAILURE_CODE:
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="linked_attempt_failure_code_mismatch",
                message=(
                    f"Linked attempt failure_code must be {PREPARED_FAILURE_CODE} "
                    f"(got {attempt.failure_code})"
                ),
                tenant_id=command.tenant_id,
                platform=command.platform,
                correlation_id=command.correlation_id,
            )
        if attempt.retryable is not False:
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="linked_attempt_retryable_mismatch",
                message="Linked attempt must have retryable=false",
                tenant_id=command.tenant_id,
                platform=command.platform,
                correlation_id=command.correlation_id,
            )
        if attempt.next_retry_at is not None:
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="linked_attempt_next_retry_set",
                message="Linked attempt next_retry_at must be NULL",
                tenant_id=command.tenant_id,
                platform=command.platform,
                correlation_id=command.correlation_id,
            )
        if attempt.external_post_id is not None or attempt.external_post_url is not None:
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="linked_attempt_provider_markers_present",
                message="Linked attempt must not have provider write markers",
                tenant_id=command.tenant_id,
                platform=command.platform,
                correlation_id=command.correlation_id,
            )
        if attempt.finished_at is not None:
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="linked_attempt_finished",
                message="Linked prepared attempt must have finished_at NULL",
                tenant_id=command.tenant_id,
                platform=command.platform,
                correlation_id=command.correlation_id,
            )
        return attempt

    @classmethod
    async def _find_newer_success(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        original: PublishAttempt,
    ) -> PublishAttempt | None:
        key = original.idempotency_key or build_idempotency_key(
            content_id=command.content_id,
            platform=command.platform,
            account_id=command.publishing_account_id,
            publish_version=command.publish_version,
        )
        prior = await PublishResilienceService.find_live_success(db, idempotency_key=key)
        if prior is not None:
            return prior
        return await PublishResilienceService.find_live_success(
            db,
            content_id=command.content_id,
            platform=command.platform,
            account_id=command.publishing_account_id,
        )

    @classmethod
    async def _apply_barrier_mutation(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
    ) -> None:
        """Atomically mark command + attempt post-barrier (same transaction)."""
        # Command: claimed → provider_write_started; clear lease expiry.
        command.status = "provider_write_started"
        command.provider_write_started_at = func.now()
        command.lease_expires_at = None
        if command.started_at is None:
            command.started_at = func.now()
        command.updated_at = func.now()
        # Preserve: resulting_attempt_id, lease_owner, claimed_at

        # Attempt: keep operator_review; forensic failure_code advances.
        attempt.status = WRITE_STARTED_ATTEMPT_STATUS
        attempt.failure_code = WRITE_STARTED_FAILURE_CODE
        attempt.failure_category = WRITE_STARTED_FAILURE_CATEGORY
        attempt.retryable = False
        attempt.next_retry_at = None
        attempt.finished_at = None
        attempt.error = WRITE_STARTED_ATTEMPT_ERROR
        # Do not set external_post_id/url, response, or provider outcome fields.
        await db.flush()

    @classmethod
    def _invariant(
        cls,
        *,
        command_id: UUID | None,
        reason_code: str,
        message: str,
        resulting_attempt_id: UUID | None = None,
        correlation_id: str | None = None,
        tenant_id: UUID | None = None,
        platform: str | None = None,
    ) -> BarrierResult:
        return BarrierResult(
            ok=False,
            outcome="invariant_violation",
            command_id=command_id,
            resulting_attempt_id=resulting_attempt_id,
            reason_code=reason_code,
            message=message,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            platform=platform,
            provider_write_started_at_is_null=True,
        )

    @classmethod
    def _record_metrics(cls, result: BarrierResult) -> None:
        if result.outcome == "barrier_crossed":
            barrier_metrics.inc("retry_command_barrier_crossed_total")
            return
        if result.outcome == "invariant_violation":
            barrier_metrics.inc("retry_command_barrier_invariant_error_total")
            return
        # disabled / already_barriered / blocked_*
        barrier_metrics.inc("retry_command_barrier_denied_total")

    @classmethod
    async def record_barrier_audit(
        cls,
        session_factory,
        result: BarrierResult,
        *,
        worker_id: str,
    ) -> None:
        """Best-effort forensic audit AFTER barrier commit. Must not undo barrier."""
        if result.command_id is None:
            return
        if result.outcome == "disabled":
            return
        if result.outcome != "barrier_crossed":
            # D1 only audits successful barrier crossings (denials remain metrics-only).
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
            "previous_command_status": result.previous_command_status or "claimed",
            "new_command_status": "provider_write_started",
            "barrier_outcome": result.outcome,
            "reason_code": result.reason_code,
        }
        try:
            async with session_factory() as db:
                await PlatformAuditService.record(
                    db,
                    actor_type="system",
                    actor_id=None,
                    tenant_id=result.tenant_id,
                    event_type="publishing.retry_command_barrier_crossed",
                    resource_type="publish_retry_command",
                    resource_id=str(result.command_id),
                    details=details,
                    commit=True,
                )
        except Exception:  # noqa: BLE001 — audit must not corrupt barrier semantics
            logger.exception(
                "[RetryCommandBarrier] audit failed command_id=%s",
                result.command_id,
            )
