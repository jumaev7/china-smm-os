"""Explicit, deterministic attribution — never probabilistic MTA.

Attribution here means: *by what explicit evidence* is an advertising entity
linked to an internal outcome (a marketing campaign, a piece of content, or a
CRM source)? Every method carries a confidence, an evidence type, and explicit
limitations. Timing/correlation alone is never sufficient — it resolves to
``unattributed``.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    TenantAdCampaign,
    TenantAdCampaignLink,
    TenantAdCreativeLink,
)
from app.services.advertising_intelligence.errors import AdCrossTenantReferenceError
from app.services.automation_domain_events import emit_domain_event

ATTRIBUTION_METHODS = (
    "provider_reported",
    "tracked_link_direct",
    "crm_explicit_source",
    "campaign_plan_link",
    "creative_publication_link",
    "manual_link",
    "unattributed",
)

# Deterministic confidence per method (higher = stronger explicit evidence).
_METHOD_CONFIDENCE: dict[str, Decimal] = {
    "crm_explicit_source": Decimal("1.000"),
    "tracked_link_direct": Decimal("0.950"),
    "manual_link": Decimal("0.900"),
    "campaign_plan_link": Decimal("0.850"),
    "creative_publication_link": Decimal("0.800"),
    "provider_reported": Decimal("0.600"),
    "unattributed": Decimal("0.000"),
}

_EVIDENCE_TYPE: dict[str, str] = {
    "crm_explicit_source": "crm_lead_source",
    "tracked_link_direct": "tracked_link",
    "manual_link": "explicit_operator_link",
    "campaign_plan_link": "campaign_plan_reference",
    "creative_publication_link": "creative_to_content_link",
    "provider_reported": "provider_attribution",
    "unattributed": "none",
}

_LIMITATIONS: dict[str, str] = {
    "provider_reported": "Provider's own attribution model; not CRM-confirmed.",
    "tracked_link_direct": "Requires the tracked link to be present on the ad destination.",
    "crm_explicit_source": "Depends on CRM lead-source hygiene.",
    "campaign_plan_link": "Reflects planning intent, not measured outcomes.",
    "creative_publication_link": "Links creative to content, not directly to conversions.",
    "manual_link": "Operator-asserted; only as reliable as the operator.",
    "unattributed": "No explicit evidence; timing/correlation alone is insufficient.",
}


def classify_attribution(
    *,
    has_crm_source: bool = False,
    has_tracked_link: bool = False,
    has_manual_link: bool = False,
    has_campaign_plan_link: bool = False,
    has_creative_publication: bool = False,
    provider_reported_conversions: bool = False,
    timing_correlation_only: bool = False,
) -> dict:
    """Pick the strongest *explicit* attribution method available.

    ``timing_correlation_only`` is never sufficient on its own.
    """
    if has_crm_source:
        method = "crm_explicit_source"
    elif has_tracked_link:
        method = "tracked_link_direct"
    elif has_manual_link:
        method = "manual_link"
    elif has_campaign_plan_link:
        method = "campaign_plan_link"
    elif has_creative_publication:
        method = "creative_publication_link"
    elif provider_reported_conversions:
        method = "provider_reported"
    else:
        method = "unattributed"
    return {
        "method": method,
        "confidence": _METHOD_CONFIDENCE[method],
        "evidence_type": _EVIDENCE_TYPE[method],
        "limitations": _LIMITATIONS[method],
        "timing_only_ignored": bool(timing_correlation_only),
    }


async def entity_attribution(
    db: AsyncSession,
    tenant_id: UUID,
    campaign_id: UUID,
    *,
    emit_event: bool = False,
) -> dict:
    """Summarize the explicit attribution posture of a campaign."""
    campaign = (
        await db.execute(
            select(TenantAdCampaign).where(
                TenantAdCampaign.id == campaign_id,
                TenantAdCampaign.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise AdCrossTenantReferenceError("advertising campaign not found")

    link = (
        await db.execute(
            select(TenantAdCampaignLink).where(
                TenantAdCampaignLink.tenant_id == tenant_id,
                TenantAdCampaignLink.ad_campaign_id == campaign_id,
                TenantAdCampaignLink.status == "active",
            )
        )
    ).scalar_one_or_none()

    has_plan_link = bool(link and link.campaign_plan_version_id)
    result = classify_attribution(
        has_manual_link=bool(link and link.link_method == "manual_link"),
        has_campaign_plan_link=has_plan_link,
    )
    summary = {
        "campaign_id": campaign_id,
        "linked_internal_campaign_id": link.marketing_campaign_id if link else None,
        "attribution_method": result["method"],
        "confidence": result["confidence"],
        "evidence_type": result["evidence_type"],
        "limitations": result["limitations"],
    }
    if emit_event and link is not None:
        await emit_domain_event(
            db,
            "advertising.attribution_recorded",
            tenant_id,
            payload={
                "campaign_id": str(campaign_id),
                "attribution_method": result["method"],
                "confidence": str(result["confidence"]),
            },
            resource_type="advertising_campaign",
            resource_id=str(campaign_id),
            title="Advertising attribution recorded",
        )
    return summary


async def creative_publication_attribution(db: AsyncSession, tenant_id: UUID, creative_id: UUID) -> dict:
    link = (
        await db.execute(
            select(TenantAdCreativeLink).where(
                TenantAdCreativeLink.tenant_id == tenant_id,
                TenantAdCreativeLink.creative_id == creative_id,
                TenantAdCreativeLink.status == "active",
            )
        )
    ).scalar_one_or_none()
    result = classify_attribution(has_creative_publication=bool(link))
    return {
        "creative_id": creative_id,
        "linked_content_id": (link.content_id or link.target_id) if link else None,
        "attribution_method": result["method"],
        "confidence": result["confidence"],
        "evidence_type": result["evidence_type"],
        "limitations": result["limitations"],
    }


__all__ = [
    "ATTRIBUTION_METHODS",
    "classify_attribution",
    "entity_attribution",
    "creative_publication_attribution",
]
