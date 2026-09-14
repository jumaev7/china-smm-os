"""Dormant publish write-coordination helpers (E2-2 Follow-up B).

Shared destination serialization for ``begin_attempt`` and E2-2
``ACKNOWLEDGE_EXTERNAL_SUCCESS``. Default-off via
``PUBLISH_WRITE_COORDINATION_ENABLED``.

Identity (cross-version):
  (tenant_id, content_id, platform, account_id|none)

Lock: transaction-scoped ``pg_advisory_xact_lock`` — never hold across
provider network I/O. Callers must commit (or rollback) the critical
section before invoking adapters.

Lock order (ack path):
  1. destination advisory lock
  2. command FOR UPDATE
  3. resulting attempt FOR UPDATE

Tenant ownership:
  - begin_attempt: caller-supplied tenant_id must match content→client tenant
  - ack: command row already scoped by tenant_id in ``_lock_command``

Pre-barrier ``claimed`` retry commands are excluded from the unresolved
guard only while retry execution remains disabled. Executor/barrier must
join this lock + guard before any future execution enablement.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import PublishRetryCommand
from app.services.publish_resilience import STATUS_IN_PROGRESS

logger = logging.getLogger(__name__)

# Stable namespace so these keys do not collide with unrelated advisory locks.
_LOCK_NAMESPACE = "publish_write_coord_v1"

UNRESOLVED_PRIOR_WRITE_REASON = "unresolved_prior_write"
UNRESOLVED_PRIOR_WRITE_FAILURE_CODE = "unresolved_prior_write"
PUBLICATION_IN_PROGRESS_ERROR = "publication_in_progress"

# Command statuses that establish unresolved external-effect risk.
# ``claimed`` intentionally omitted while execution remains disabled.
_UNRESOLVED_COMMAND_STATUSES = frozenset({
    "provider_write_started",
    "ambiguous",
})


@dataclass(frozen=True)
class DestinationIdentity:
    tenant_id: UUID
    content_id: UUID
    platform: str
    account_id: UUID | None

    @property
    def account_token(self) -> str:
        return str(self.account_id) if self.account_id is not None else "none"

    @property
    def platform_normalized(self) -> str:
        return (self.platform or "").strip().lower()


def write_coordination_enabled() -> bool:
    return bool(getattr(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", False))


def normalize_destination(
    *,
    tenant_id: UUID,
    content_id: UUID,
    platform: str,
    account_id: UUID | None,
) -> DestinationIdentity:
    return DestinationIdentity(
        tenant_id=tenant_id,
        content_id=content_id,
        platform=(platform or "").strip().lower(),
        account_id=account_id,
    )


def advisory_lock_keys(identity: DestinationIdentity) -> tuple[int, int]:
    """Deterministic signed int32 pair for ``pg_advisory_xact_lock(k1, k2)``.

    Uses SHA-256 — never Python ``hash()``.
    """
    material = "|".join(
        (
            _LOCK_NAMESPACE,
            str(identity.tenant_id),
            str(identity.content_id),
            identity.platform_normalized,
            identity.account_token,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    k1 = int.from_bytes(digest[0:4], "big", signed=True)
    k2 = int.from_bytes(digest[4:8], "big", signed=True)
    return k1, k2


async def acquire_destination_xact_lock(
    db: AsyncSession,
    identity: DestinationIdentity,
) -> None:
    """Acquire transaction-scoped destination lock (blocks until available)."""
    k1, k2 = advisory_lock_keys(identity)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k1, :k2)"),
        {"k1": k1, "k2": k2},
    )
    logger.debug(
        "[WriteCoord] acquired xact lock tenant=%s content=%s platform=%s account=%s",
        identity.tenant_id,
        identity.content_id,
        identity.platform_normalized,
        identity.account_token,
    )


async def assert_content_tenant_owns(
    db: AsyncSession,
    *,
    content_id: UUID,
    tenant_id: UUID,
) -> None:
    """Fail closed if content is missing or belongs to another tenant.

    Uses SQL join (content → client → tenant) rather than full ORM hydrate so
    callers / isolated test schemas remain compatible.
    """
    row = (
        await db.execute(
            text(
                """
                SELECT c.tenant_id AS tenant_id
                FROM content_items ci
                JOIN clients c ON c.id = ci.client_id
                WHERE ci.id = :content_id
                """
            ),
            {"content_id": content_id},
        )
    ).first()
    if row is None:
        raise ValueError(f"content_id {content_id} not found for write coordination")
    owned = row.tenant_id
    if owned != tenant_id:
        raise ValueError(
            f"tenant ownership mismatch for content {content_id}: "
            f"expected {tenant_id}, got {owned}"
        )


async def find_unresolved_destination_write(
    db: AsyncSession,
    identity: DestinationIdentity,
) -> PublishRetryCommand | None:
    """Return a relevant unresolved retry-command write for the destination.

    Matching is by tenant + content + platform + account (cross-version).
    Does not rely on command idempotency keys alone.
    """
    plat = identity.platform_normalized
    stmt = (
        select(PublishRetryCommand)
        .where(
            PublishRetryCommand.tenant_id == identity.tenant_id,
            PublishRetryCommand.content_id == identity.content_id,
            PublishRetryCommand.platform == plat,
            PublishRetryCommand.status.in_(tuple(_UNRESOLVED_COMMAND_STATUSES)),
        )
        .order_by(PublishRetryCommand.created_at.desc())
    )
    if identity.account_id is not None:
        stmt = stmt.where(
            PublishRetryCommand.publishing_account_id == identity.account_id
        )
    else:
        stmt = stmt.where(PublishRetryCommand.publishing_account_id.is_(None))

    rows = (await db.execute(stmt)).scalars().all()
    for cmd in rows:
        if cmd.status == "provider_write_started":
            if cmd.provider_write_started_at is None:
                # Incomplete marker — fail closed.
                return cmd
            return cmd
        if cmd.status == "ambiguous":
            # Ambiguous does not establish absence of a provider effect.
            return cmd
    return None


async def find_destination_in_progress_attempt(
    db: AsyncSession,
    identity: DestinationIdentity,
) -> PublishAttempt | None:
    """Any ``in_progress`` attempt for the destination (any publish_version)."""
    plat = identity.platform_normalized
    stmt = select(PublishAttempt).where(
        PublishAttempt.content_id == identity.content_id,
        PublishAttempt.platform == plat,
        PublishAttempt.status == STATUS_IN_PROGRESS,
    )
    if identity.account_id is not None:
        stmt = stmt.where(PublishAttempt.account_id == identity.account_id)
    else:
        stmt = stmt.where(PublishAttempt.account_id.is_(None))
    return (await db.execute(stmt.order_by(PublishAttempt.created_at.desc()))).scalars().first()


def unresolved_prior_write_claim_result(
    *,
    platform: str,
    account_id: UUID | None,
    account_name: str | None,
    command: PublishRetryCommand,
    mock: bool,
) -> dict[str, Any]:
    """Bounded skip payload — no synthetic failed attempt / auto-retry."""
    return {
        "platform": platform,
        "success": False,
        "error": (
            "Unresolved prior provider write for this destination; "
            "resolve the stranded retry command before republishing"
        ),
        "platform_post_id": None,
        "mock": mock,
        "account_id": str(account_id) if account_id else None,
        "account_name": account_name,
        "failure_code": UNRESOLVED_PRIOR_WRITE_FAILURE_CODE,
        "failure_category": "concurrency",
        "retryable": False,
        "unresolved_command_id": str(command.id),
        "unresolved_command_status": command.status,
    }
