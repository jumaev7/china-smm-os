"""Deterministic campaign attribution for external publications.

Methods are explicit and non-probabilistic:
- direct_slot_assignment (confidence 1.0)
- direct_campaign_publication (confidence 0.9)
- manual_link (confidence 0.7 or override)
- unattributed (confidence 0.0)

One publication may not be fully counted in multiple campaigns without an
explicit allocation rule (not implemented in Phase 2).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import (
    ATTRIBUTION_METHODS,
    TenantAttributionRecord,
    TenantExternalPublication,
)
from app.services.automation_domain_events import emit_domain_event
from app.services.measurement.confidence_engine import confidence_for_method
from app.services.measurement.errors import (
    CampaignNotFoundError,
    PublicationNotFoundError,
    ValidationError,
)
from app.services.measurement.schemas import AttributionResult


async def record_publish_attribution(
    db: AsyncSession,
    *,
    publication: TenantExternalPublication,
) -> TenantAttributionRecord:
    """Create the initial attribution record frozen at publish registration."""
    if publication.campaign_slot_id and publication.campaign_id:
        method = "direct_slot_assignment"
        evidence = {
            "campaign_id": str(publication.campaign_id),
            "campaign_slot_id": str(publication.campaign_slot_id),
            "assignment_id": str(publication.assignment_id) if publication.assignment_id else None,
            "plan_version_id": str(publication.campaign_plan_version_id)
            if publication.campaign_plan_version_id else None,
            "frozen_at_publish": True,
        }
        target_id = str(publication.campaign_id)
        target_type = "campaign"
    elif publication.campaign_id:
        method = "direct_campaign_publication"
        evidence = {
            "campaign_id": str(publication.campaign_id),
            "frozen_at_publish": True,
            "note": "Publication linked to campaign without a calendar slot assignment.",
        }
        target_id = str(publication.campaign_id)
        target_type = "campaign"
    else:
        method = "unattributed"
        evidence = {"frozen_at_publish": True, "note": "No campaign linkage at publish time."}
        target_id = "none"
        target_type = "none"

    confidence = confidence_for_method(method)
    row = TenantAttributionRecord(
        id=uuid4(),
        tenant_id=publication.tenant_id,
        entity_type="external_publication",
        entity_id=str(publication.id),
        source_type="publish_registration",
        source_id=str(publication.publish_attempt_id or publication.id),
        target_type=target_type,
        target_id=target_id,
        attribution_method=method,
        confidence=confidence,
        evidence=evidence,
        status="active",
    )
    db.add(row)
    await db.flush()

    await emit_domain_event(
        db,
        "attribution.recorded",
        publication.tenant_id,
        payload={
            "attribution_id": str(row.id),
            "external_publication_id": str(publication.id),
            "attribution_method": method,
            "confidence": str(confidence),
            "campaign_id": str(publication.campaign_id) if publication.campaign_id else None,
        },
        resource_type="external_publication",
        resource_id=str(publication.id),
        title="Attribution recorded",
    )
    return row


async def create_manual_link(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    publication_id: UUID,
    campaign_id: UUID,
    confidence_override: Decimal | None = None,
    evidence: dict[str, Any] | None = None,
) -> TenantAttributionRecord:
    """Explicit operator-created campaign link — does not rewrite publish-time freeze."""
    from app.models.campaign_planner import TenantMarketingCampaign

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

    campaign = (
        await db.execute(
            select(TenantMarketingCampaign).where(
                TenantMarketingCampaign.id == campaign_id,
                TenantMarketingCampaign.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise CampaignNotFoundError("campaign not found")

    # Supersede other active campaign attributions for this publication
    # (no double full counting without allocation rules).
    existing = list(
        (
            await db.execute(
                select(TenantAttributionRecord).where(
                    TenantAttributionRecord.tenant_id == tenant_id,
                    TenantAttributionRecord.entity_type == "external_publication",
                    TenantAttributionRecord.entity_id == str(publication_id),
                    TenantAttributionRecord.target_type == "campaign",
                    TenantAttributionRecord.status == "active",
                )
            )
        ).scalars().all()
    )
    for row in existing:
        row.status = "superseded"

    method = "manual_link"
    confidence = confidence_for_method(method, override=confidence_override)
    payload_evidence = {
        "campaign_id": str(campaign_id),
        "manual": True,
        **(evidence or {}),
    }
    row = TenantAttributionRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        entity_type="external_publication",
        entity_id=str(publication_id),
        source_type="manual_link",
        source_id=str(uuid4()),
        target_type="campaign",
        target_id=str(campaign_id),
        attribution_method=method,
        confidence=confidence,
        evidence=payload_evidence,
        status="active",
    )
    db.add(row)
    await db.flush()

    await emit_domain_event(
        db,
        "attribution.updated",
        tenant_id,
        payload={
            "attribution_id": str(row.id),
            "external_publication_id": str(publication_id),
            "attribution_method": method,
            "confidence": str(confidence),
            "campaign_id": str(campaign_id),
        },
        resource_type="external_publication",
        resource_id=str(publication_id),
        title="Attribution updated",
    )
    return row


async def list_attribution_for_publication(
    db: AsyncSession,
    tenant_id: UUID,
    publication_id: UUID,
) -> list[TenantAttributionRecord]:
    return list(
        (
            await db.execute(
                select(TenantAttributionRecord)
                .where(
                    TenantAttributionRecord.tenant_id == tenant_id,
                    TenantAttributionRecord.entity_type == "external_publication",
                    TenantAttributionRecord.entity_id == str(publication_id),
                )
                .order_by(TenantAttributionRecord.created_at.desc())
            )
        ).scalars().all()
    )


async def list_attribution_for_campaign(
    db: AsyncSession,
    tenant_id: UUID,
    campaign_id: UUID,
) -> list[TenantAttributionRecord]:
    return list(
        (
            await db.execute(
                select(TenantAttributionRecord)
                .where(
                    TenantAttributionRecord.tenant_id == tenant_id,
                    TenantAttributionRecord.target_type == "campaign",
                    TenantAttributionRecord.target_id == str(campaign_id),
                    TenantAttributionRecord.status == "active",
                )
                .order_by(TenantAttributionRecord.created_at.desc())
            )
        ).scalars().all()
    )


def to_result(row: TenantAttributionRecord) -> AttributionResult:
    return AttributionResult(
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        source_type=row.source_type,
        source_id=row.source_id,
        target_type=row.target_type,
        target_id=row.target_id,
        attribution_method=row.attribution_method,
        confidence=row.confidence,
        evidence=row.evidence or {},
        status=row.status,
    )


def require_method(method: str) -> None:
    if method not in ATTRIBUTION_METHODS:
        raise ValidationError(f"unknown attribution method: {method}", details={"field": "attribution_method"})


__all__ = [
    "record_publish_attribution",
    "create_manual_link",
    "list_attribution_for_publication",
    "list_attribution_for_campaign",
    "to_result",
    "require_method",
]
