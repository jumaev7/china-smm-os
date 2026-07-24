"""Advertising data freshness classification.

Deterministic mapping of "how old is our newest observation" to a freshness
status, using the same thresholds as ``limits``. ``unsupported`` is reserved for
accounts whose provider/connection cannot deliver insights at all.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdvertisingAccount
from app.services.advertising_intelligence.errors import AdAccountNotFoundError
from app.services.advertising_intelligence.limits import (
    AGING_MAX_AGE_SECONDS,
    FRESH_MAX_AGE_SECONDS,
)


def compute_freshness(
    last_observation_at: datetime | None,
    *,
    now: datetime | None = None,
    supported: bool = True,
) -> dict:
    """Return ``{"status", "age_seconds", "last_observation_at", "reason"}``."""
    if not supported:
        return {
            "status": "unsupported",
            "age_seconds": None,
            "last_observation_at": last_observation_at,
            "reason": "Provider/connection does not support insights.",
        }
    if last_observation_at is None:
        return {
            "status": "unavailable",
            "age_seconds": None,
            "last_observation_at": None,
            "reason": "No metric observations have been ingested yet.",
        }
    now = now or datetime.now(timezone.utc)
    ref = last_observation_at if last_observation_at.tzinfo else last_observation_at.replace(tzinfo=timezone.utc)
    age = (now - ref).total_seconds()
    if age <= FRESH_MAX_AGE_SECONDS:
        status = "fresh"
    elif age <= AGING_MAX_AGE_SECONDS:
        status = "aging"
    else:
        status = "stale"
    return {
        "status": status,
        "age_seconds": age,
        "last_observation_at": last_observation_at,
        "reason": None,
    }


async def account_freshness(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> dict:
    account = (
        await db.execute(
            select(TenantAdvertisingAccount).where(
                TenantAdvertisingAccount.id == account_id,
                TenantAdvertisingAccount.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise AdAccountNotFoundError("advertising account not found")
    supported = not (
        account.connection_status not in ("connected",) and not account.is_mock
    )
    last = account.last_metrics_sync_at or account.last_successful_sync_at
    result = compute_freshness(last, supported=supported)
    result["account_id"] = account_id
    return result


__all__ = ["compute_freshness", "account_freshness"]
