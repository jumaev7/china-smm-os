"""Optional explicit tracked-link contracts.

No automatic caption rewriting. Public redirect handling is deferred —
this module provides data contracts and explicit-link APIs only.
Click counts are aggregate daily totals; raw IP/PII is not stored.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import TenantTrackedLink, TenantTrackedLinkClicksDaily
from app.services.automation_domain_events import emit_domain_event
from app.services.measurement.errors import TrackedLinkNotFoundError, ValidationError
from app.services.measurement.limits import MAX_TRACKED_LINKS, enforce_child_count

_SAFE_SCHEMES = frozenset({"http", "https"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_destination(url: str) -> str:
    text = (url or "").strip()
    if not text or len(text) > 2000:
        raise ValidationError("invalid destination_url", details={"field": "destination_url"})
    lower = text.lower()
    if lower.startswith("javascript:") or lower.startswith("data:") or lower.startswith("vbscript:"):
        raise ValidationError("unsafe destination_url scheme", details={"field": "destination_url"})
    parsed = urlparse(text)
    if parsed.scheme.lower() not in _SAFE_SCHEMES or not parsed.netloc:
        raise ValidationError("destination_url must be http(s) with a host", details={"field": "destination_url"})
    return text


async def create_tracked_link(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    destination_url: str,
    campaign_id: UUID | None = None,
    content_id: UUID | None = None,
    content_variant_id: UUID | None = None,
    platform: str | None = None,
    created_by: UUID | None = None,
) -> TenantTrackedLink:
    existing_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(TenantTrackedLink)
                .where(TenantTrackedLink.tenant_id == tenant_id)
            )
        ).scalar_one()
        or 0
    )
    enforce_child_count(existing_count, MAX_TRACKED_LINKS, "max_tracked_links")

    url = _validate_destination(destination_url)
    code = secrets.token_urlsafe(12)[:32]
    row = TenantTrackedLink(
        id=uuid4(),
        tenant_id=tenant_id,
        destination_url=url,
        tracking_code=code,
        campaign_id=campaign_id,
        content_id=content_id,
        content_variant_id=content_variant_id,
        platform=platform,
        status="active",
        created_by=created_by,
    )
    db.add(row)
    await db.flush()

    await emit_domain_event(
        db,
        "tracked_link.created",
        tenant_id,
        payload={
            "tracked_link_id": str(row.id),
            "tracking_code": code,
            "campaign_id": str(campaign_id) if campaign_id else None,
            "content_id": str(content_id) if content_id else None,
            "platform": platform,
            # Intentionally omit destination_url from event payload (may be sensitive).
        },
        resource_type="tracked_link",
        resource_id=str(row.id),
        title="Tracked link created",
    )
    return row


async def get_tracked_link(db: AsyncSession, tenant_id: UUID, link_id: UUID) -> TenantTrackedLink:
    row = (
        await db.execute(
            select(TenantTrackedLink).where(
                TenantTrackedLink.id == link_id,
                TenantTrackedLink.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise TrackedLinkNotFoundError("tracked link not found")
    return row


async def list_tracked_links(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[TenantTrackedLink], int]:
    filters = [TenantTrackedLink.tenant_id == tenant_id]
    if status:
        filters.append(TenantTrackedLink.status == status)
    total = int(
        (await db.execute(select(func.count()).select_from(TenantTrackedLink).where(*filters))).scalar_one()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(TenantTrackedLink)
                .where(*filters)
                .order_by(TenantTrackedLink.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    return rows, total


async def disable_tracked_link(db: AsyncSession, tenant_id: UUID, link_id: UUID) -> TenantTrackedLink:
    row = await get_tracked_link(db, tenant_id, link_id)
    row.status = "disabled"
    row.disabled_at = utcnow()
    await db.flush()
    return row


__all__ = [
    "create_tracked_link",
    "get_tracked_link",
    "list_tracked_links",
    "disable_tracked_link",
]
