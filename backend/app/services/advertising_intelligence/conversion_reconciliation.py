"""Conversion reconciliation: provider-reported vs CRM-confirmed.

Provider-reported conversions are NEVER treated as CRM-confirmed. Matching a
provider conversion to a CRM outcome requires *explicit* linkage evidence
(explicit id / UTM / tracked link / CRM lead-source) — never timing alone.

Because CRM outcome ingestion is a separate concern, this module reports what it
can prove: reported counts, whether a campaign has an explicit internal link,
and a per-campaign status. When no CRM outcome source is wired, campaigns with
provider conversions are ``provider_only`` rather than ``matched``.

Statuses: ``not_available`` | ``provider_only`` | ``crm_only`` | ``matched`` |
``partial_match`` | ``discrepant`` | ``unattributed``.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdCampaign, TenantAdCampaignLink
from app.services.advertising_intelligence import spend_service  # noqa: F401  (kept for symmetry)
from app.services.advertising_intelligence._entity_metrics import metric_decimal, latest_metric_map
from app.services.automation_domain_events import emit_domain_event

RECONCILIATION_STATUSES = (
    "not_available",
    "provider_only",
    "crm_only",
    "matched",
    "partial_match",
    "discrepant",
    "unattributed",
)


def compute_reconciliation(
    *,
    reported: int | None,
    crm_confirmed: int | None,
    has_explicit_link: bool,
) -> dict:
    """Pure per-campaign reconciliation classification."""
    reported = reported or 0
    if crm_confirmed is None:
        # No CRM outcome source available for this campaign.
        if reported > 0:
            status = "provider_only"
        elif has_explicit_link:
            status = "not_available"
        else:
            status = "unattributed"
        return {
            "status": status,
            "reported": reported,
            "crm_confirmed": None,
            "matched": 0,
            "unmatched_reported": reported,
        }
    if reported == 0 and crm_confirmed == 0:
        status = "unattributed"
    elif reported == 0 and crm_confirmed > 0:
        status = "crm_only"
    elif reported > 0 and crm_confirmed == 0:
        status = "provider_only"
    elif not has_explicit_link:
        # Cannot claim a match without explicit linkage evidence.
        status = "provider_only"
    elif reported == crm_confirmed:
        status = "matched"
    elif abs(reported - crm_confirmed) <= max(1, int(0.1 * reported)):
        status = "partial_match"
    else:
        status = "discrepant"
    matched = min(reported, crm_confirmed) if status in ("matched", "partial_match") else 0
    return {
        "status": status,
        "reported": reported,
        "crm_confirmed": crm_confirmed,
        "matched": matched,
        "unmatched_reported": max(0, reported - matched),
    }


async def reconcile(db: AsyncSession, tenant_id: UUID, *, account_id: UUID | None = None) -> dict:
    """Reconcile provider vs CRM conversions across a tenant's campaigns."""
    filters = [TenantAdCampaign.tenant_id == tenant_id]
    if account_id is not None:
        filters.append(TenantAdCampaign.advertising_account_id == account_id)
    campaigns = list((await db.execute(select(TenantAdCampaign).where(*filters))).scalars().all())

    links = {
        row.ad_campaign_id
        for row in (
            await db.execute(
                select(TenantAdCampaignLink).where(
                    TenantAdCampaignLink.tenant_id == tenant_id,
                    TenantAdCampaignLink.status == "active",
                )
            )
        ).scalars().all()
    }

    total_reported = total_matched = total_unmatched = 0
    by_campaign: list[dict] = []
    for campaign in campaigns:
        metrics = await latest_metric_map(db, tenant_id, "campaign", campaign.id)
        reported_dec = metric_decimal(metrics, "conversions")
        reported = int(reported_dec) if reported_dec is not None else 0
        result = compute_reconciliation(
            reported=reported,
            crm_confirmed=None,  # No CRM outcome source wired in Phase 1.
            has_explicit_link=campaign.id in links,
        )
        total_reported += result["reported"]
        total_matched += result["matched"]
        total_unmatched += result["unmatched_reported"]
        by_campaign.append({
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.name or campaign.provider_campaign_id,
            "reconciliation_status": result["status"],
            "conversions_reported": result["reported"],
            "conversions_crm_confirmed": result["crm_confirmed"],
            "matched": result["matched"],
            "linked": campaign.id in links,
        })
        if result["status"] == "discrepant":
            await emit_domain_event(
                db, "advertising.conversion_reconciled", tenant_id,
                payload={
                    "campaign_id": str(campaign.id),
                    "reconciliation_status": result["status"],
                    "status": result["status"],
                },
                resource_type="advertising_campaign", resource_id=str(campaign.id),
                title="Advertising conversion reconciliation",
            )

    coverage = (total_matched / total_reported) if total_reported else None
    return {
        "read_only": True,
        "reported_conversions": total_reported,
        "crm_confirmed_conversions": total_matched,
        "matched_conversions": total_matched,
        "unmatched_reported": total_unmatched,
        "coverage_ratio": coverage,
        "by_campaign": by_campaign,
        "note": (
            "Provider-reported conversions are not CRM-confirmed. Matching "
            "requires explicit linkage evidence (explicit id / UTM / tracked "
            "link / CRM lead-source); timing alone is never sufficient."
        ),
    }


__all__ = ["RECONCILIATION_STATUSES", "compute_reconciliation", "reconcile"]
