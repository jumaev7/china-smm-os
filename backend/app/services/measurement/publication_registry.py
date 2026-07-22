"""Canonical external publication identity registration.

Publications are created only from verified successful publish results.
Campaign linkage is frozen at publish time from a valid slot assignment —
later reassignment never rewrites historical publication rows.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_planner import (
    TenantCampaignCalendarSlot,
    TenantCampaignSlotAssignment,
)
from app.models.content import ContentItem
from app.models.measurement import TenantExternalPublication
from app.models.publish_attempt import PublishAttempt
from app.models.publishing_account import PublishingAccount
from app.services.automation_domain_events import emit_domain_event
from app.services.measurement.attribution_service import record_publish_attribution
from app.services.measurement.freshness_service import next_collection_at
from app.services.measurement.job_service import schedule_collection_job

logger = logging.getLogger(__name__)

_SAFE_PERMALINK_SCHEMES = frozenset({"http", "https"})
_SIGNED_URL_MARKERS = ("X-Amz-Signature", "Signature=", "X-Goog-Signature", "sig=")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_permalink(url: str | None) -> str | None:
    if not url:
        return None
    text = str(url).strip()
    if not text or len(text) > 2000:
        return None
    if any(marker in text for marker in _SIGNED_URL_MARKERS):
        return None
    parsed = urlparse(text)
    if parsed.scheme.lower() not in _SAFE_PERMALINK_SCHEMES:
        return None
    if not parsed.netloc:
        return None
    return text


def _source_fingerprint(content: ContentItem, *, variant_id: UUID | None = None) -> str:
    raw = "|".join([
        str(content.id),
        str(variant_id or ""),
        (content.caption_short_en or "")[:200],
        (content.caption_long_en or "")[:200],
        (content.caption_short_ru or "")[:200],
        (content.caption_long_ru or "")[:200],
        ",".join(sorted(content.platforms or [])),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


async def _find_assignment_for_publish(
    db: AsyncSession,
    tenant_id: UUID,
    content_id: UUID,
    *,
    platform: str | None = None,
) -> tuple[TenantCampaignSlotAssignment | None, TenantCampaignCalendarSlot | None]:
    rows = list(
        (
            await db.execute(
                select(TenantCampaignSlotAssignment)
                .where(
                    TenantCampaignSlotAssignment.tenant_id == tenant_id,
                    TenantCampaignSlotAssignment.content_id == content_id,
                )
                .order_by(TenantCampaignSlotAssignment.assigned_at.desc().nullslast())
            )
        ).scalars().all()
    )
    if not rows:
        return None, None

    assignment = rows[0]
    if platform:
        matched = [
            a for a in rows
            if (a.assigned_platform or "").lower() == platform.lower()
        ]
        if matched:
            assignment = matched[0]

    slot = (
        await db.execute(
            select(TenantCampaignCalendarSlot).where(
                TenantCampaignCalendarSlot.id == assignment.slot_id,
                TenantCampaignCalendarSlot.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    return assignment, slot


async def register_from_publish_attempt(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    content: ContentItem,
    attempt: PublishAttempt,
    result: dict[str, Any],
    account: PublishingAccount | None,
) -> TenantExternalPublication | None:
    """Upsert an external publication from a verified successful publish result.

    Returns None when the result cannot safely identify a provider publication
    (no fabricated IDs). Never raises into the publish path — callers should
    still wrap if needed, but this function itself is defensive.
    """
    try:
        if not result.get("success"):
            return None

        provider_publication_id = result.get("platform_post_id")
        if provider_publication_id is None or str(provider_publication_id).strip() == "":
            return None
        provider_publication_id = str(provider_publication_id).strip()[:255]

        platform = (result.get("platform") or attempt.platform or "").strip().lower()
        if not platform:
            return None

        if account is not None and account.tenant_id != tenant_id:
            logger.warning("measurement.publication_registration_tenant_mismatch")
            return None

        permalink = _validate_permalink(result.get("post_url"))
        assignment, slot = await _find_assignment_for_publish(
            db, tenant_id, content.id, platform=platform,
        )
        variant_id = assignment.content_variant_id if assignment else None
        fingerprint = _source_fingerprint(content, variant_id=variant_id)
        now = utcnow()
        is_mock = bool(result.get("mock")) or (account is not None and account.status == "mock")

        existing = (
            await db.execute(
                select(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_id,
                    TenantExternalPublication.publishing_account_id == (account.id if account else None),
                    TenantExternalPublication.platform == platform,
                    TenantExternalPublication.provider_publication_id == provider_publication_id,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.last_seen_at = now
            if permalink and not existing.provider_permalink:
                existing.provider_permalink = permalink
            if existing.publish_attempt_id is None:
                existing.publish_attempt_id = attempt.id
            await db.flush()
            return existing

        generation_method = None
        if assignment is not None:
            if assignment.assignment_type == "ai_variant":
                generation_method = "ai_assisted"
            elif assignment.assignment_type == "deterministic_variant":
                generation_method = "deterministic"
            else:
                generation_method = "manual"

        pub = TenantExternalPublication(
            id=uuid4(),
            tenant_id=tenant_id,
            content_id=content.id,
            content_variant_id=variant_id,
            publishing_account_id=account.id if account else None,
            platform=platform,
            provider_publication_id=provider_publication_id,
            provider_parent_id=None,
            provider_permalink=permalink,
            publication_status="published",
            published_at=content.published_at or now,
            first_seen_at=now,
            last_seen_at=now,
            freshness_status="unavailable",
            source_fingerprint=fingerprint,
            generation_method=generation_method,
            publishing_review_id=assignment.publishing_review_id if assignment else None,
            publishing_score_at_publish=None,
            campaign_id=assignment.campaign_id if assignment else None,
            campaign_plan_version_id=assignment.plan_version_id if assignment else None,
            campaign_slot_id=assignment.slot_id if assignment else None,
            assignment_id=assignment.id if assignment else None,
            publish_attempt_id=attempt.id,
            content_pillar_id=slot.pillar_id if slot else None,
            campaign_phase_id=slot.phase_id if slot else None,
            locale=(assignment.assigned_locale if assignment else None),
            is_mock=is_mock,
            metadata_json={
                "account_name": result.get("account_name"),
                "registered_from": "publish_attempt",
            },
        )
        db.add(pub)
        await db.flush()

        await record_publish_attribution(db, publication=pub)

        try:
            await schedule_collection_job(
                db,
                tenant_id=tenant_id,
                publication=pub,
                available_at=next_collection_at(
                    published_at=pub.published_at,
                    last_metric_at=None,
                    now=now,
                ),
                cadence_key="1h",
            )
        except Exception:
            logger.exception("measurement.schedule_collection_failed")

        await emit_domain_event(
            db,
            "publication.registered",
            tenant_id,
            payload={
                "external_publication_id": str(pub.id),
                "platform": pub.platform,
                "content_id": str(content.id),
                "campaign_id": str(pub.campaign_id) if pub.campaign_id else None,
                "is_mock": pub.is_mock,
                "has_assignment": assignment is not None,
            },
            resource_type="external_publication",
            resource_id=str(pub.id),
            title="Publication registered for measurement",
        )
        return pub
    except Exception:
        logger.exception("measurement.publication_registration_failed")
        return None


async def get_publication(
    db: AsyncSession,
    tenant_id: UUID,
    publication_id: UUID,
) -> TenantExternalPublication:
    from app.services.measurement.errors import PublicationNotFoundError

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
    return pub


async def list_publications(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    platform: str | None = None,
    campaign_id: UUID | None = None,
    freshness_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[TenantExternalPublication], int]:
    from sqlalchemy import func

    filters = [TenantExternalPublication.tenant_id == tenant_id]
    if platform:
        filters.append(TenantExternalPublication.platform == platform)
    if campaign_id:
        filters.append(TenantExternalPublication.campaign_id == campaign_id)
    if freshness_status:
        filters.append(TenantExternalPublication.freshness_status == freshness_status)

    total = (
        await db.execute(
            select(func.count()).select_from(TenantExternalPublication).where(*filters)
        )
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(TenantExternalPublication)
                .where(*filters)
                .order_by(TenantExternalPublication.published_at.desc().nullslast())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    return rows, int(total)


__all__ = [
    "register_from_publish_attempt",
    "get_publication",
    "list_publications",
]
