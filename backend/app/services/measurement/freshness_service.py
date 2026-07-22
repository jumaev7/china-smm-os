"""Publication and aggregate freshness classification.

Freshness is descriptive of observation age relative to expected collection
cadence — never a claim about content quality or future performance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import TenantExternalPublication
from app.models.publishing_account import PublishingAccount
from app.services.measurement.errors import PublicationNotFoundError
from app.services.measurement.providers import get_adapter
from app.services.measurement.providers.base import DISCONNECTED_ACCOUNT_STATUSES
from app.services.measurement.schemas import FreshnessResult

# Cadence thresholds (seconds since last successful observation).
_FRESH_MAX = 6 * 3600
_AGING_MAX = 36 * 3600
# Beyond _AGING_MAX → stale (unless unsupported/unavailable).


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_freshness(
    *,
    last_metric_at: datetime | None,
    published_at: datetime | None = None,
    capability_status: str | None = None,
    account_status: str | None = None,
    now: datetime | None = None,
) -> FreshnessResult:
    """Classify freshness from observation age + capability + account state."""
    reference = now or utcnow()

    if account_status in DISCONNECTED_ACCOUNT_STATUSES:
        return FreshnessResult(
            status="unavailable",
            age_seconds=None,
            last_observation_at=last_metric_at,
            reason="publishing_account_disconnected",
        )

    if capability_status in {"unsupported", "limited"} and last_metric_at is None:
        return FreshnessResult(
            status="unsupported" if capability_status == "unsupported" else "unavailable",
            age_seconds=None,
            last_observation_at=None,
            reason=f"capability_{capability_status}",
        )

    if last_metric_at is None:
        # Recently published with no observation yet → unavailable, not stale.
        if published_at is not None:
            age = (reference - published_at).total_seconds()
            if age < 3600:
                return FreshnessResult(
                    status="unavailable",
                    age_seconds=None,
                    last_observation_at=None,
                    reason="awaiting_first_observation",
                )
        return FreshnessResult(
            status="unavailable",
            age_seconds=None,
            last_observation_at=None,
            reason="no_observation",
        )

    age = max((reference - last_metric_at).total_seconds(), 0.0)
    if age <= _FRESH_MAX:
        status = "fresh"
        reason = "within_expected_cadence"
    elif age <= _AGING_MAX:
        status = "aging"
        reason = "approaching_stale"
    else:
        status = "stale"
        reason = "observation_older_than_cadence"

    if capability_status == "unsupported":
        status = "unsupported"
        reason = "capability_unsupported"

    return FreshnessResult(
        status=status,
        age_seconds=age,
        last_observation_at=last_metric_at,
        reason=reason,
    )


async def refresh_publication_freshness(
    db: AsyncSession,
    tenant_id: UUID,
    publication_id: UUID,
    *,
    now: datetime | None = None,
) -> FreshnessResult:
    """Recompute and persist freshness_status for one publication."""
    pub = (
        await db.execute(
            select(TenantExternalPublication).where(
                TenantExternalPublication.id == publication_id,
                TenantExternalPublication.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if pub is None:
        raise PublicationNotFoundError("publication not found")

    account_status: str | None = None
    capability_status: str | None = None
    if pub.publishing_account_id is not None:
        account = (
            await db.execute(
                select(PublishingAccount).where(
                    PublishingAccount.id == pub.publishing_account_id,
                    PublishingAccount.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if account is not None:
            account_status = account.status
            caps = get_adapter(pub.platform).capabilities(account_status=account.status)
            capability_status = caps.capability_status

    result = compute_freshness(
        last_metric_at=pub.last_metric_at,
        published_at=pub.published_at,
        capability_status=capability_status,
        account_status=account_status,
        now=now,
    )
    pub.freshness_status = result.status
    await db.flush()
    return result


def next_collection_at(
    *,
    published_at: datetime | None,
    last_metric_at: datetime | None,
    now: datetime | None = None,
) -> datetime:
    """Policy-driven next collection time (internal cadence, not posting advice)."""
    reference = now or utcnow()
    published = published_at or reference
    age = (reference - published).total_seconds()

    # Recent: denser cadence. Older active: daily. Past 30d: no auto refresh.
    if age > 30 * 24 * 3600:
        return reference + timedelta(days=3650)  # effectively paused

    if age <= 24 * 3600:
        interval = timedelta(hours=1)
    elif age <= 72 * 3600:
        interval = timedelta(hours=6)
    elif age <= 7 * 24 * 3600:
        interval = timedelta(hours=24)
    else:
        interval = timedelta(hours=24)

    base = last_metric_at or published
    candidate = base + interval
    return candidate if candidate > reference else reference


__all__ = [
    "compute_freshness",
    "refresh_publication_freshness",
    "next_collection_at",
    "utcnow",
]
