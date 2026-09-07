"""Publish retry-command claim / lease / reclaim foundation (Phase 3C.1C-B).

Ownership only: pending → claimed, and reclaim of stale claimed rows that are
provably pre-write (provider_write_started_at IS NULL).

Never creates PublishAttempt, never sets resulting_attempt_id / retry_command_id,
never sets provider_write_started*, never calls PublishService / adapters / alerts.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.publish_retry_command import (
    RETRY_COMMAND_TERMINAL_STATUSES,
    PublishRetryCommand,
)
from app.services import publish_retry_command_metrics as claim_metrics
from app.services.platform_audit_service import PlatformAuditService

logger = logging.getLogger(__name__)

ClaimKind = Literal["claimed", "reclaimed", "none", "disabled"]

# Conservative bounds for pre-execution ownership leases.
_MIN_LEASE_SECONDS = 30
_MAX_LEASE_SECONDS = 3600
_MIN_BATCH = 1
_MAX_BATCH = 5

# Statuses that must never be selected by claim or reclaim (defense in depth).
_FORBIDDEN_CLAIM_STATUSES = frozenset({"provider_write_started"}) | RETRY_COMMAND_TERMINAL_STATUSES


@dataclass(frozen=True)
class ClaimResult:
    """Internal claim/reclaim outcome. Does not expose lease_owner to APIs."""

    kind: ClaimKind
    command_id: UUID | None = None
    status: str | None = None
    correlation_id: str | None = None
    is_reclaim: bool = False
    tenant_id: UUID | None = None
    original_attempt_id: UUID | None = None
    content_id: UUID | None = None
    platform: str | None = None
    requested_source: str | None = None
    reason: str | None = None
    # Scrubbed prior owner token for reclaim audit only (never raw hostname).
    prior_worker_instance: str | None = None


def scrubbed_worker_instance(worker_id: str) -> str:
    """Stable non-secret process-instance token for audit (no raw hostname)."""
    digest = hashlib.sha256((worker_id or "").encode("utf-8")).hexdigest()
    return f"winst_{digest[:16]}"


def lease_seconds() -> int:
    raw = int(settings.PUBLISH_RETRY_COMMAND_LEASE_SECONDS)
    return max(_MIN_LEASE_SECONDS, min(raw, _MAX_LEASE_SECONDS))


def batch_size(requested: int | None = None) -> int:
    raw = int(
        requested
        if requested is not None
        else settings.PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE
    )
    return max(_MIN_BATCH, min(raw, _MAX_BATCH))


def claim_gates_open() -> tuple[bool, str]:
    """Return (allowed, reason) for claim/reclaim DB mutation.

    Precedence (all required):
      PUBLISH_RETRY_COMMANDS_ENABLED
      AND PUBLISH_RETRY_COMMAND_WORKER_ENABLED
      AND PUBLISH_RETRY_COMMAND_CLAIM_ENABLED

    EXECUTION flag is irrelevant in 3C.1C-B (execution unimplemented).
    Worker flag alone must not enable command creation.
    """
    if not settings.PUBLISH_RETRY_COMMANDS_ENABLED:
        return False, "commands_disabled"
    if not settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED:
        return False, "worker_disabled"
    if not settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED:
        return False, "claim_disabled"
    return True, "ok"


class PublishRetryCommandClaimService:
    """Claim and reclaim ownership only. No provider execution."""

    @classmethod
    async def claim_batch(
        cls,
        db: AsyncSession,
        *,
        worker_id: str,
        batch: int | None = None,
        commit: bool = True,
    ) -> list[ClaimResult]:
        """Claim pending and/or reclaim stale claimed rows (SKIP LOCKED).

        Short transaction: select + update + commit. No provider work while locked.
        Prefer reclaim of expired pre-write claimed rows, then pending claims.
        """
        allowed, reason = claim_gates_open()
        if not allowed:
            claim_metrics.inc("retry_command_claim_disabled_total")
            return [ClaimResult(kind="disabled", reason=reason)]

        limit = batch_size(batch)
        lease = lease_seconds()
        results: list[ClaimResult] = []

        try:
            reclaimed = await cls._reclaim_stale(
                db, worker_id=worker_id, limit=limit, lease=lease,
            )
            results.extend(reclaimed)
            remaining = limit - len(reclaimed)
            if remaining > 0:
                claimed = await cls._claim_pending(
                    db, worker_id=worker_id, limit=remaining, lease=lease,
                )
                results.extend(claimed)

            if commit:
                await db.commit()
            else:
                await db.flush()
        except Exception:
            claim_metrics.inc("retry_command_claim_error_total")
            logger.exception(
                "[RetryCommandClaim] claim_batch failed worker=%s",
                scrubbed_worker_instance(worker_id),
            )
            if commit:
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
            raise

        if not results:
            claim_metrics.inc("retry_command_claim_none_total")
            return [ClaimResult(kind="none", reason="no_eligible")]

        for item in results:
            if item.is_reclaim:
                claim_metrics.inc("retry_command_reclaim_total")
            else:
                claim_metrics.inc("retry_command_claim_total")

        return results

    @classmethod
    async def _claim_pending(
        cls,
        db: AsyncSession,
        *,
        worker_id: str,
        limit: int,
        lease: int,
    ) -> list[ClaimResult]:
        rows = list(
            (
                await db.scalars(
                    select(PublishRetryCommand)
                    .where(PublishRetryCommand.status == "pending")
                    .order_by(PublishRetryCommand.created_at.asc())
                    .limit(limit)
                    .with_for_update(skip_locked=True),
                )
            ).all(),
        )
        out: list[ClaimResult] = []
        for row in rows:
            # Defense: never touch forbidden statuses even if query drifts.
            if row.status in _FORBIDDEN_CLAIM_STATUSES:
                continue
            if row.provider_write_started_at is not None:
                continue
            await cls._apply_ownership(
                db,
                row,
                worker_id=worker_id,
                lease=lease,
                preserve_claim_timestamps=False,
            )
            out.append(
                ClaimResult(
                    kind="claimed",
                    command_id=row.id,
                    status="claimed",
                    correlation_id=row.correlation_id,
                    is_reclaim=False,
                    tenant_id=row.tenant_id,
                    original_attempt_id=row.original_attempt_id,
                    content_id=row.content_id,
                    platform=row.platform,
                    requested_source=row.requested_source,
                    reason="pending_claim",
                ),
            )
        return out

    @classmethod
    async def _reclaim_stale(
        cls,
        db: AsyncSession,
        *,
        worker_id: str,
        limit: int,
        lease: int,
    ) -> list[ClaimResult]:
        """Reclaim status=claimed with expired lease and no provider write barrier."""
        rows = list(
            (
                await db.scalars(
                    select(PublishRetryCommand)
                    .where(
                        PublishRetryCommand.status == "claimed",
                        PublishRetryCommand.lease_expires_at.is_not(None),
                        PublishRetryCommand.lease_expires_at < func.now(),
                        PublishRetryCommand.provider_write_started_at.is_(None),
                    )
                    .order_by(PublishRetryCommand.created_at.asc())
                    .limit(limit)
                    .with_for_update(skip_locked=True),
                )
            ).all(),
        )
        out: list[ClaimResult] = []
        for row in rows:
            if row.status != "claimed":
                continue
            if row.provider_write_started_at is not None:
                continue
            if row.status in _FORBIDDEN_CLAIM_STATUSES:
                continue
            prior_owner = row.lease_owner
            await cls._apply_ownership(
                db,
                row,
                worker_id=worker_id,
                lease=lease,
                preserve_claim_timestamps=True,
            )
            out.append(
                ClaimResult(
                    kind="reclaimed",
                    command_id=row.id,
                    status="claimed",
                    correlation_id=row.correlation_id,
                    is_reclaim=True,
                    tenant_id=row.tenant_id,
                    original_attempt_id=row.original_attempt_id,
                    content_id=row.content_id,
                    platform=row.platform,
                    requested_source=row.requested_source,
                    reason="stale_claimed_reclaim",
                    prior_worker_instance=(
                        scrubbed_worker_instance(prior_owner) if prior_owner else None
                    ),
                ),
            )
        return out

    @staticmethod
    async def _apply_ownership(
        db: AsyncSession,
        row: PublishRetryCommand,
        *,
        worker_id: str,
        lease: int,
        preserve_claim_timestamps: bool,
    ) -> None:
        """Update ownership using database clock for lease expiry."""
        # SQLAlchemy emits now() + interval; comparison authority remains DB time.
        lease_expires = func.now() + timedelta(seconds=lease)
        values: dict[str, Any] = {
            "status": "claimed",
            "lease_owner": worker_id,
            "lease_expires_at": lease_expires,
            "updated_at": func.now(),
        }
        if preserve_claim_timestamps:
            # Keep original claimed_at / started_at (reclaim in place).
            pass
        else:
            values["claimed_at"] = func.coalesce(
                PublishRetryCommand.claimed_at, func.now(),
            )
            values["started_at"] = func.coalesce(
                PublishRetryCommand.started_at, func.now(),
            )

        await db.execute(
            update(PublishRetryCommand)
            .where(PublishRetryCommand.id == row.id)
            .values(**values),
        )
        # Refresh local attributes used for result/audit without relying on app clock
        # for lease correctness (lease_expires_at remains DB-authored).
        row.status = "claimed"
        row.lease_owner = worker_id
        await db.refresh(row, attribute_names=[
            "status",
            "lease_owner",
            "lease_expires_at",
            "claimed_at",
            "started_at",
            "updated_at",
            "provider_write_started_at",
            "resulting_attempt_id",
            "correlation_id",
        ])

    @classmethod
    async def record_claim_audits(
        cls,
        session_factory,
        results: Sequence[ClaimResult],
        *,
        worker_id: str,
    ) -> None:
        """Best-effort audits AFTER claim commit. Failures must not undo claims."""
        instance = scrubbed_worker_instance(worker_id)
        for item in results:
            if item.kind not in ("claimed", "reclaimed") or item.command_id is None:
                continue
            event_type = (
                "publishing.retry_command_reclaimed"
                if item.is_reclaim
                else "publishing.retry_command_claimed"
            )
            details: dict[str, Any] = {
                "command_id": str(item.command_id),
                "original_attempt_id": (
                    str(item.original_attempt_id) if item.original_attempt_id else None
                ),
                "content_id": str(item.content_id) if item.content_id else None,
                "platform": item.platform,
                "requested_source": item.requested_source,
                "correlation_id": item.correlation_id,
                "worker_event": item.kind,
                "claim_reason": item.reason,
                "worker_instance": instance,
                "is_reclaim": item.is_reclaim,
            }
            if item.prior_worker_instance:
                details["prior_worker_instance"] = item.prior_worker_instance
            try:
                async with session_factory() as db:
                    await PlatformAuditService.record(
                        db,
                        actor_type="system",
                        actor_id=None,
                        tenant_id=item.tenant_id,
                        event_type=event_type,
                        resource_type="publish_retry_command",
                        resource_id=str(item.command_id),
                        details=details,
                        commit=True,
                    )
            except Exception:  # noqa: BLE001 — audit must not corrupt claim semantics
                logger.exception(
                    "[RetryCommandClaim] audit failed command_id=%s event=%s",
                    item.command_id,
                    event_type,
                )

