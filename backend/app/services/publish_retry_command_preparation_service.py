"""Publish retry-command pre-I/O preparation (Phase 3C.1C-C).

Canonical path after claim, before any provider write:

  claimed command
  → FOR UPDATE lock + ownership/lease validation
  → canonical manual-retry eligibility revalidation
  → newer authoritative success check
  → create OR reuse exactly one linked PublishAttempt
  → persist bidirectional lineage
  → COMMIT
  → STOP

Never calls PublishService.publish_content, adapters, finalize_attempt, or
provider HTTP. Never sets provider_write_started*. Never transitions command
status away from ``claimed``.

PublishAttempt status for newly prepared rows
--------------------------------------------
``operator_review`` — chosen because:

* ``in_progress`` is an active publish claim (unique partial index) and is
  recovered/mutated by stale-attempt workers.
* ``retrying`` is selected by ScheduledPublishService /
  PublishAttemptOpsService.due_retry_content_ids /
  PublishResilienceService.claim_due_retries.
* ``operator_review`` is intentionally outside auto-retry / active-claim
  selectors; it already means "do not auto-execute".

Prepared attempts set ``retryable=False``, ``next_retry_at=NULL``, and a
forensic failure_code of ``retry_command_prepared``. Phase 3C.1C-D1
(``PublishRetryCommandBarrierService``) consumes a still-``claimed`` command
with ``resulting_attempt_id`` set and ``provider_write_started_at IS NULL``,
then crosses the DB-only write barrier (no provider I/O).

``PublishResilienceService.begin_attempt`` is NOT reused: it creates
``in_progress``, may supersede unrelated ``retrying`` rows, and does not set
``retry_command_id``.

Reachability
------------
Not wired into PublishRetryCommandWorker. Callable only as an explicit
internal/test entrypoint. ``prepare_gates_open`` requires COMMANDS + WORKER +
CLAIM + EXECUTION so accidental production calls fail closed while EXECUTION
remains false.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

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
from app.services import publish_retry_command_metrics as prep_metrics
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
    utc_now,
)
from app.services.publish_retry_command_claim_service import scrubbed_worker_instance
from app.services.publishing_tenant_scope import tenant_id_for_content_optional

logger = logging.getLogger(__name__)

# Pre-provider attempt status — see module docstring (auto-execution audit).
PREPARED_ATTEMPT_STATUS = STATUS_OPERATOR_REVIEW
PREPARED_FAILURE_CODE = "retry_command_prepared"
PREPARED_FAILURE_CATEGORY = "command_orchestration"
PREPARED_ATTEMPT_ERROR = (
    "Prepared for durable retry-command execution; provider write not started"
)

PreparationOutcome = Literal[
    "prepared",
    "reused_existing_attempt",
    "repaired_attempt_side_link",
    "blocked_ineligible",
    "blocked_newer_success",
    "blocked_lease_or_ownership",
    "blocked_terminal_or_post_write",
    "invariant_violation",
    "disabled",
]


@dataclass(frozen=True)
class PreparationResult:
    """Structured pre-I/O preparation outcome. No provider payloads."""

    ok: bool
    outcome: PreparationOutcome
    command_id: UUID | None = None
    resulting_attempt_id: UUID | None = None
    original_attempt_id: UUID | None = None
    reused_existing_attempt: bool = False
    reason_code: str | None = None
    message: str | None = None
    eligibility_reason_code: str | None = None
    safety_class: str | None = None
    newer_success_attempt_id: UUID | None = None
    correlation_id: str | None = None
    tenant_id: UUID | None = None
    platform: str | None = None
    requested_source: str | None = None
    command_status: str | None = None
    provider_write_started_at_is_null: bool = True


def prepare_gates_open() -> tuple[bool, str]:
    """Return (allowed, reason) for preparation mutations.

    All four flags required. EXECUTION is included so preparation remains
    unreachable in production while EXECUTION stays false, even if claim
    gates are opened for observation. Worker must not call this service yet.
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


class PublishRetryCommandPreparationService:
    """Pre-I/O revalidation + deterministic command↔attempt linkage.

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
    async def prepare(
        cls,
        db: AsyncSession,
        *,
        command_id: UUID,
        worker_id: str,
        correlation_id: str | None = None,
        commit: bool = True,
        eligibility_evaluator: RetryCommandEligibilityEvaluator | None = None,
    ) -> PreparationResult:
        """Prepare a claimed command: validate, link exactly one attempt, commit.

        Loads canonical DB state itself. Does not trust caller-supplied platform,
        attempt status, eligibility, or content version.
        """
        allowed, gate_reason = prepare_gates_open()
        if not allowed:
            prep_metrics.inc("retry_command_prepare_blocked_total")
            return PreparationResult(
                ok=False,
                outcome="disabled",
                command_id=command_id,
                reason_code=gate_reason,
                message="Retry command preparation is disabled",
            )

        evaluator = eligibility_evaluator
        try:
            result = await cls._prepare_locked(
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
            prep_metrics.inc("retry_command_prepare_invariant_error_total")
            logger.exception(
                "[RetryCommandPrepare] failed command_id=%s worker=%s",
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
    async def prepare_and_audit(
        cls,
        db: AsyncSession,
        session_factory,
        *,
        command_id: UUID,
        worker_id: str,
        correlation_id: str | None = None,
        eligibility_evaluator: RetryCommandEligibilityEvaluator | None = None,
    ) -> PreparationResult:
        """Prepare with commit, then best-effort audit in a separate session."""
        result = await cls.prepare(
            db,
            command_id=command_id,
            worker_id=worker_id,
            correlation_id=correlation_id,
            commit=True,
            eligibility_evaluator=eligibility_evaluator,
        )
        await cls.record_preparation_audit(
            session_factory,
            result,
            worker_id=worker_id,
        )
        return result

    @classmethod
    async def _prepare_locked(
        cls,
        db: AsyncSession,
        *,
        command_id: UUID,
        worker_id: str,
        correlation_id: str | None,
        eligibility_evaluator: RetryCommandEligibilityEvaluator | None,
    ) -> PreparationResult:
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
        ownership = await cls._validate_ownership_and_lease(db, command, worker_id=worker_id)
        if ownership is not None:
            return ownership

        lineage = await cls._load_and_validate_lineage(db, command)
        if isinstance(lineage, PreparationResult):
            return lineage
        original, content, client, account = lineage

        # Restart invariant: command → attempt already set.
        if command.resulting_attempt_id is not None:
            return await cls._reuse_command_side_link(
                db,
                command,
                original=original,
                content=content,
                client=client,
                correlation_id=corr,
            )

        # Crash recovery: attempt → command already set, command side NULL.
        orphan = await cls._find_attempt_side_link(db, command.id)
        if orphan is not None:
            return await cls._repair_attempt_side_link(
                db,
                command,
                orphan,
                original=original,
                content=content,
                client=client,
                correlation_id=corr,
            )

        # Eligibility against ORIGINAL attempt.
        # Default path calls module-global evaluate_manual_retry_eligibility so
        # existing unit tests can patch it. Injected evaluators (staging) bypass.
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
            return PreparationResult(
                ok=False,
                outcome="blocked_ineligible",
                command_id=command.id,
                original_attempt_id=command.original_attempt_id,
                reason_code=eligibility.reason_code,
                message=eligibility.operator_message or "Manual retry unavailable",
                eligibility_reason_code=eligibility.reason_code,
                safety_class=eligibility.safety_class,
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
            )

        # Newer authoritative success — do not create a retry attempt.
        newer = await cls._find_newer_success(db, command, original)
        if newer is not None:
            return PreparationResult(
                ok=False,
                outcome="blocked_newer_success",
                command_id=command.id,
                original_attempt_id=command.original_attempt_id,
                reason_code="newer_success",
                message="Authoritative live success exists; retry attempt not created",
                newer_success_attempt_id=newer.id,
                correlation_id=corr,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
            )

        attempt = await cls._create_prepared_attempt(
            db,
            command,
            account=account,
        )
        command.resulting_attempt_id = attempt.id
        command.updated_at = func.now()
        await db.flush()

        return PreparationResult(
            ok=True,
            outcome="prepared",
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            original_attempt_id=command.original_attempt_id,
            reused_existing_attempt=False,
            reason_code="prepared",
            message="Retry command prepared with linked PublishAttempt",
            correlation_id=corr,
            tenant_id=command.tenant_id,
            platform=command.platform,
            requested_source=command.requested_source,
            command_status=command.status,
            provider_write_started_at_is_null=command.provider_write_started_at is None,
        )

    @classmethod
    async def _validate_ownership_and_lease(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        *,
        worker_id: str,
    ) -> PreparationResult | None:
        """Fail closed unless claimed by this worker with a non-expired lease.

        Lease authority is DB ``now()`` at validation time under the row lock.
        Once ownership is valid, the short pre-I/O transaction may finish and
        commit even if wall-clock lease would expire mid-transaction (no
        provider I/O is held under the lock).
        """
        if command.status in RETRY_COMMAND_TERMINAL_STATUSES:
            return PreparationResult(
                ok=False,
                outcome="blocked_terminal_or_post_write",
                command_id=command.id,
                reason_code="terminal_command",
                message=f"Command is terminal ({command.status})",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
            )
        if command.status == "provider_write_started" or command.provider_write_started_at is not None:
            return PreparationResult(
                ok=False,
                outcome="blocked_terminal_or_post_write",
                command_id=command.id,
                reason_code="provider_write_started",
                message="Command has already crossed the provider write barrier",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
            )
        if command.status != "claimed":
            return PreparationResult(
                ok=False,
                outcome="blocked_lease_or_ownership",
                command_id=command.id,
                reason_code="not_claimed",
                message=f"Command status must be claimed (got {command.status})",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
            )
        if command.lease_owner != worker_id:
            return PreparationResult(
                ok=False,
                outcome="blocked_lease_or_ownership",
                command_id=command.id,
                reason_code="lease_owner_mismatch",
                message="Command lease owner does not match current worker",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
            )
        if command.lease_expires_at is None:
            return PreparationResult(
                ok=False,
                outcome="blocked_lease_or_ownership",
                command_id=command.id,
                reason_code="lease_missing",
                message="Command has no lease expiry",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
            )

        expired = (
            await db.execute(
                select(
                    PublishRetryCommand.lease_expires_at < func.now(),
                ).where(PublishRetryCommand.id == command.id),
            )
        ).scalar_one()
        if expired:
            return PreparationResult(
                ok=False,
                outcome="blocked_lease_or_ownership",
                command_id=command.id,
                reason_code="lease_expired",
                message="Command lease has expired",
                correlation_id=command.correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
                requested_source=command.requested_source,
                command_status=command.status,
                provider_write_started_at_is_null=command.provider_write_started_at is None,
            )
        return None

    @classmethod
    async def _load_and_validate_lineage(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
    ) -> (
        tuple[PublishAttempt, ContentItem, Client, PublishingAccount | None]
        | PreparationResult
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

        # Expose account for canonical live-state builder (no extra relationship load).
        if account is not None:
            original.account = account

        return original, content, client, account

    @classmethod
    async def _reuse_command_side_link(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        *,
        original: PublishAttempt,
        content: ContentItem,
        client: Client,
        correlation_id: str,
    ) -> PreparationResult:
        """Reuse command.resulting_attempt_id when bidirectional link is consistent."""
        del original, content, client  # lineage already validated for command itself
        attempt = await db.get(PublishAttempt, command.resulting_attempt_id)
        if attempt is None:
            return cls._invariant(
                command_id=command.id,
                reason_code="resulting_attempt_missing",
                message="resulting_attempt_id points to missing attempt",
                correlation_id=correlation_id,
                tenant_id=command.tenant_id,
            )
        if attempt.retry_command_id != command.id:
            # Inverse broken link — do NOT silently relink.
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="bidirectional_lineage_broken",
                message=(
                    "command.resulting_attempt_id set but attempt.retry_command_id "
                    "does not match — fail closed"
                ),
                correlation_id=correlation_id,
                tenant_id=command.tenant_id,
                platform=command.platform,
            )
        mismatch = cls._attempt_lineage_mismatch(command, attempt)
        if mismatch is not None:
            return mismatch

        return PreparationResult(
            ok=True,
            outcome="reused_existing_attempt",
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            original_attempt_id=command.original_attempt_id,
            reused_existing_attempt=True,
            reason_code="reused_existing_attempt",
            message="Existing linked PublishAttempt reused",
            correlation_id=correlation_id,
            tenant_id=command.tenant_id,
            platform=command.platform,
            requested_source=command.requested_source,
            command_status=command.status,
            provider_write_started_at_is_null=command.provider_write_started_at is None,
        )

    @classmethod
    async def _find_attempt_side_link(
        cls,
        db: AsyncSession,
        command_id: UUID,
    ) -> PublishAttempt | None:
        return (
            await db.execute(
                select(PublishAttempt).where(
                    PublishAttempt.retry_command_id == command_id,
                ),
            )
        ).scalar_one_or_none()

    @classmethod
    async def _repair_attempt_side_link(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
        *,
        original: PublishAttempt,
        content: ContentItem,
        client: Client,
        correlation_id: str,
    ) -> PreparationResult:
        """Recoverable historical state: attempt linked, command.resulting NULL."""
        del original, content, client
        if attempt.retry_command_id != command.id:
            return cls._invariant(
                command_id=command.id,
                resulting_attempt_id=attempt.id,
                reason_code="attempt_side_link_mismatch",
                message="Attempt-side retry_command_id mismatch",
                correlation_id=correlation_id,
                tenant_id=command.tenant_id,
            )
        mismatch = cls._attempt_lineage_mismatch(command, attempt)
        if mismatch is not None:
            return mismatch

        command.resulting_attempt_id = attempt.id
        command.updated_at = func.now()
        await db.flush()

        return PreparationResult(
            ok=True,
            outcome="repaired_attempt_side_link",
            command_id=command.id,
            resulting_attempt_id=attempt.id,
            original_attempt_id=command.original_attempt_id,
            reused_existing_attempt=True,
            reason_code="repaired_attempt_side_link",
            message="Attempt-side orphan link repaired; attempt reused",
            correlation_id=correlation_id,
            tenant_id=command.tenant_id,
            platform=command.platform,
            requested_source=command.requested_source,
            command_status=command.status,
            provider_write_started_at_is_null=command.provider_write_started_at is None,
        )

    @classmethod
    def _attempt_lineage_mismatch(
        cls,
        command: PublishRetryCommand,
        attempt: PublishAttempt,
    ) -> PreparationResult | None:
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
        return None

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
    async def _create_prepared_attempt(
        cls,
        db: AsyncSession,
        command: PublishRetryCommand,
        *,
        account: PublishingAccount | None,
    ) -> PublishAttempt:
        """Create exactly one pre-provider attempt linked to the command.

        Does not call begin_attempt (unsafe here — see module docstring).
        """
        del account  # validated; account_id taken from command
        key = build_idempotency_key(
            content_id=command.content_id,
            platform=command.platform,
            account_id=command.publishing_account_id,
            publish_version=command.publish_version,
        )
        attempt_number = await PublishResilienceService.next_attempt_number(db, key)
        now = utc_now()
        attempt = PublishAttempt(
            id=uuid4(),
            content_id=command.content_id,
            platform=command.platform,
            account_id=command.publishing_account_id,
            status=PREPARED_ATTEMPT_STATUS,
            response=None,
            error=PREPARED_ATTEMPT_ERROR,
            idempotency_key=key,
            publish_version=command.publish_version,
            attempt_number=attempt_number,
            failure_code=PREPARED_FAILURE_CODE,
            failure_category=PREPARED_FAILURE_CATEGORY,
            retryable=False,
            next_retry_at=None,
            started_at=now,
            finished_at=None,
            external_post_id=None,
            external_post_url=None,
            lease_owner=None,
            lease_expires_at=None,
            retry_after_seconds=None,
            retry_command_id=command.id,
        )
        db.add(attempt)
        await db.flush()
        return attempt

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
    ) -> PreparationResult:
        return PreparationResult(
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
    def _record_metrics(cls, result: PreparationResult) -> None:
        if result.outcome == "disabled":
            prep_metrics.inc("retry_command_prepare_blocked_total")
            return
        if result.outcome == "invariant_violation":
            prep_metrics.inc("retry_command_prepare_invariant_error_total")
            return
        if result.outcome in ("blocked_ineligible", "blocked_newer_success",
                              "blocked_lease_or_ownership", "blocked_terminal_or_post_write"):
            prep_metrics.inc("retry_command_prepare_blocked_total")
            return
        if result.reused_existing_attempt:
            prep_metrics.inc("retry_command_prepare_reuse_total")
            return
        if result.ok:
            prep_metrics.inc("retry_command_prepare_total")

    @classmethod
    async def record_preparation_audit(
        cls,
        session_factory,
        result: PreparationResult,
        *,
        worker_id: str,
    ) -> None:
        """Best-effort forensic audit AFTER prepare commit. Must not undo prepare."""
        if result.command_id is None:
            return
        if result.outcome == "disabled":
            return

        if result.outcome == "invariant_violation":
            event_type = "publishing.retry_command_lineage_invariant_failed"
        elif result.outcome in (
            "blocked_ineligible",
            "blocked_newer_success",
            "blocked_lease_or_ownership",
            "blocked_terminal_or_post_write",
        ):
            event_type = "publishing.retry_command_preparation_blocked"
        elif result.reused_existing_attempt:
            event_type = "publishing.retry_command_attempt_reused"
        elif result.ok:
            event_type = "publishing.retry_command_prepared"
        else:
            event_type = "publishing.retry_command_preparation_blocked"

        details: dict[str, Any] = {
            "command_id": str(result.command_id),
            "original_attempt_id": (
                str(result.original_attempt_id) if result.original_attempt_id else None
            ),
            "resulting_attempt_id": (
                str(result.resulting_attempt_id) if result.resulting_attempt_id else None
            ),
            "platform": result.platform,
            "requested_source": result.requested_source,
            "correlation_id": result.correlation_id,
            "preparation_outcome": result.outcome,
            "reason_code": result.reason_code,
            "reused_existing_attempt": result.reused_existing_attempt,
            "worker_instance": scrubbed_worker_instance(worker_id),
            "newer_success_attempt_id": (
                str(result.newer_success_attempt_id)
                if result.newer_success_attempt_id
                else None
            ),
            "command_status": result.command_status,
            "provider_write_started_at_is_null": result.provider_write_started_at_is_null,
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
        except Exception:  # noqa: BLE001 — audit must not corrupt prepare semantics
            logger.exception(
                "[RetryCommandPrepare] audit failed command_id=%s event=%s",
                result.command_id,
                event_type,
            )
