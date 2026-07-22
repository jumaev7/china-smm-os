"""Campaign-level metric rollups and honest KPI progress.

KPI statuses describe measured progress only — never predicted outcomes.
Lead/sales KPIs are never marked achieved from likes or views.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_planner import TenantCampaignKpi, TenantMarketingCampaign
from app.models.measurement import (
    CALCULATION_VERSION,
    TenantAttributionRecord,
    TenantCampaignMetricAggregate,
    TenantExternalPublication,
    TenantPublicationMetricAggregate,
)
from app.services.automation_domain_events import emit_domain_event
from app.services.measurement.errors import CampaignNotFoundError
from app.services.measurement.metric_catalog import METRIC_CATALOG
from app.services.measurement.schemas import KpiProgressResult

# KPIs that require CRM/tracked conversion evidence — never inferred from engagement.
_LEAD_OR_SALES_KEYS = frozenset({
    "leads",
    "lead_count",
    "conversions",
    "sales",
    "revenue",
    "deals",
    "crm_leads",
    "qualified_leads",
})

_ENGAGEMENT_PROXY_KEYS = frozenset({
    "likes", "comments", "shares", "saves", "reactions", "engagements",
    "impressions", "reach", "views", "video_views",
})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _require_campaign(db: AsyncSession, tenant_id: UUID, campaign_id: UUID) -> TenantMarketingCampaign:
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
    return campaign


async def attributed_publications(
    db: AsyncSession,
    tenant_id: UUID,
    campaign_id: UUID,
) -> list[TenantExternalPublication]:
    """Publications with active attribution to this campaign OR frozen campaign_id."""
    attrs = list(
        (
            await db.execute(
                select(TenantAttributionRecord).where(
                    TenantAttributionRecord.tenant_id == tenant_id,
                    TenantAttributionRecord.target_type == "campaign",
                    TenantAttributionRecord.target_id == str(campaign_id),
                    TenantAttributionRecord.status == "active",
                    TenantAttributionRecord.entity_type == "external_publication",
                )
            )
        ).scalars().all()
    )
    pub_ids = {UUID(a.entity_id) for a in attrs}
    frozen = list(
        (
            await db.execute(
                select(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_id,
                    TenantExternalPublication.campaign_id == campaign_id,
                )
            )
        ).scalars().all()
    )
    for p in frozen:
        pub_ids.add(p.id)

    if not pub_ids:
        return []
    return list(
        (
            await db.execute(
                select(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_id,
                    TenantExternalPublication.id.in_(list(pub_ids)),
                )
            )
        ).scalars().all()
    )


async def recalculate_campaign_aggregates(
    db: AsyncSession,
    tenant_id: UUID,
    campaign_id: UUID,
    *,
    metric_keys: list[str] | None = None,
    window_key: str = "lifetime",
) -> list[TenantCampaignMetricAggregate]:
    await _require_campaign(db, tenant_id, campaign_id)
    pubs = await attributed_publications(db, tenant_id, campaign_id)
    if not pubs:
        return []

    keys = metric_keys or sorted(k for k in METRIC_CATALOG if METRIC_CATALOG[k].aggregation_type != "derived" or k == "engagements")
    # Prefer lifetime publication aggregates with direct_slot_assignment confidence.
    results: list[TenantCampaignMetricAggregate] = []

    for metric_key in keys:
        total = Decimal("0")
        count = 0
        confidences: list[Decimal] = []
        for pub in pubs:
            agg = (
                await db.execute(
                    select(TenantPublicationMetricAggregate).where(
                        TenantPublicationMetricAggregate.tenant_id == tenant_id,
                        TenantPublicationMetricAggregate.external_publication_id == pub.id,
                        TenantPublicationMetricAggregate.window_key == window_key,
                        TenantPublicationMetricAggregate.metric_key == metric_key,
                        TenantPublicationMetricAggregate.calculation_version == CALCULATION_VERSION,
                    )
                )
            ).scalar_one_or_none()
            if agg is None:
                continue
            total += agg.metric_value
            count += 1
            confidences.append(agg.confidence)

        if count == 0:
            continue

        # Attribution scope: if all pubs have slot assignment, use that; else mixed.
        methods = set()
        for pub in pubs:
            if pub.campaign_slot_id:
                methods.add("direct_slot_assignment")
            elif pub.campaign_id:
                methods.add("direct_campaign_publication")
            else:
                methods.add("manual_or_other")
        if methods == {"direct_slot_assignment"}:
            scope = "direct_slot_assignment"
            confidence = Decimal("1.000")
        elif "direct_slot_assignment" in methods or "direct_campaign_publication" in methods:
            scope = "mixed_direct"
            confidence = min(confidences) if confidences else Decimal("0.900")
        else:
            scope = "attributed"
            confidence = min(confidences) if confidences else Decimal("0.700")

        existing = (
            await db.execute(
                select(TenantCampaignMetricAggregate).where(
                    TenantCampaignMetricAggregate.tenant_id == tenant_id,
                    TenantCampaignMetricAggregate.campaign_id == campaign_id,
                    TenantCampaignMetricAggregate.metric_key == metric_key,
                    TenantCampaignMetricAggregate.attribution_scope == scope,
                    TenantCampaignMetricAggregate.calculation_version == CALCULATION_VERSION,
                    TenantCampaignMetricAggregate.window_start.is_(None),
                    TenantCampaignMetricAggregate.window_end.is_(None),
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.metric_value = total
            existing.confidence = confidence
            existing.publication_count = count
            existing.aggregation_method = "sum_attributed"
            existing.calculated_at = utcnow()
            results.append(existing)
        else:
            row = TenantCampaignMetricAggregate(
                id=uuid4(),
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                campaign_plan_version_id=None,
                metric_key=metric_key,
                metric_value=total,
                aggregation_method="sum_attributed",
                attribution_scope=scope,
                confidence=confidence,
                window_start=None,
                window_end=None,
                calculation_version=CALCULATION_VERSION,
                publication_count=count,
                calculated_at=utcnow(),
            )
            db.add(row)
            results.append(row)

    await db.flush()
    if results:
        await emit_domain_event(
            db,
            "campaign.metrics_updated",
            tenant_id,
            payload={
                "campaign_id": str(campaign_id),
                "metric_count": len(results),
                "publication_count": len(pubs),
            },
            resource_type="campaign",
            resource_id=str(campaign_id),
            title="Campaign metrics updated",
        )
    return results


async def evaluate_campaign_kpis(
    db: AsyncSession,
    tenant_id: UUID,
    campaign_id: UUID,
) -> list[KpiProgressResult]:
    await _require_campaign(db, tenant_id, campaign_id)
    kpis = list(
        (
            await db.execute(
                select(TenantCampaignKpi)
                .where(
                    TenantCampaignKpi.tenant_id == tenant_id,
                    TenantCampaignKpi.campaign_id == campaign_id,
                )
                .order_by(TenantCampaignKpi.sort_order.asc())
            )
        ).scalars().all()
    )
    pubs = await attributed_publications(db, tenant_id, campaign_id)
    campaign_aggs = {
        a.metric_key: a
        for a in (
            await db.execute(
                select(TenantCampaignMetricAggregate).where(
                    TenantCampaignMetricAggregate.tenant_id == tenant_id,
                    TenantCampaignMetricAggregate.campaign_id == campaign_id,
                    TenantCampaignMetricAggregate.calculation_version == CALCULATION_VERSION,
                )
            )
        ).scalars().all()
    }

    results: list[KpiProgressResult] = []
    for kpi in kpis:
        metric_key = kpi.metric_key
        target = Decimal(str(kpi.target_value)) if kpi.target_value is not None else None

        # Lead/sales honesty: never mark achieved from engagement proxies.
        if metric_key in _LEAD_OR_SALES_KEYS or metric_key.startswith("lead") or metric_key.startswith("sales"):
            results.append(
                KpiProgressResult(
                    kpi_id=kpi.id,
                    campaign_id=campaign_id,
                    metric_key=metric_key,
                    target_value=target,
                    current_value=None,
                    comparator=kpi.comparator,
                    status="not_measurable",
                    progress_ratio=None,
                    confidence=Decimal("0.000"),
                    freshness_status="unavailable",
                    evidence={
                        "reason": "Lead/sales KPIs require verified CRM or tracked conversion linkage.",
                        "engagement_inference_forbidden": True,
                    },
                )
            )
            continue

        if metric_key not in METRIC_CATALOG and not metric_key.startswith("provider:"):
            results.append(
                KpiProgressResult(
                    kpi_id=kpi.id,
                    campaign_id=campaign_id,
                    metric_key=metric_key,
                    target_value=target,
                    current_value=None,
                    comparator=kpi.comparator,
                    status="not_measurable",
                    progress_ratio=None,
                    confidence=Decimal("0.000"),
                    freshness_status="unavailable",
                    evidence={"reason": "metric_key not in measurement catalog"},
                )
            )
            continue

        if not pubs:
            results.append(
                KpiProgressResult(
                    kpi_id=kpi.id,
                    campaign_id=campaign_id,
                    metric_key=metric_key,
                    target_value=target,
                    current_value=None,
                    comparator=kpi.comparator,
                    status="no_data",
                    progress_ratio=None,
                    confidence=Decimal("0.000"),
                    freshness_status="unavailable",
                    evidence={"reason": "no_attributed_publications"},
                )
            )
            continue

        agg = campaign_aggs.get(metric_key)
        if agg is None:
            # Attempt recalculation once.
            await recalculate_campaign_aggregates(db, tenant_id, campaign_id, metric_keys=[metric_key])
            agg = (
                await db.execute(
                    select(TenantCampaignMetricAggregate).where(
                        TenantCampaignMetricAggregate.tenant_id == tenant_id,
                        TenantCampaignMetricAggregate.campaign_id == campaign_id,
                        TenantCampaignMetricAggregate.metric_key == metric_key,
                        TenantCampaignMetricAggregate.calculation_version == CALCULATION_VERSION,
                    )
                )
            ).scalar_one_or_none()

        if agg is None:
            results.append(
                KpiProgressResult(
                    kpi_id=kpi.id,
                    campaign_id=campaign_id,
                    metric_key=metric_key,
                    target_value=target,
                    current_value=None,
                    comparator=kpi.comparator,
                    status="no_data",
                    progress_ratio=None,
                    confidence=Decimal("0.000"),
                    freshness_status="unavailable",
                    evidence={"reason": "no_aggregated_observations"},
                )
            )
            continue

        freshness_statuses = {p.freshness_status for p in pubs}
        if freshness_statuses <= {"stale", "unavailable", "unsupported"}:
            status = "data_stale"
        else:
            current = agg.metric_value
            status = "in_progress"
            if target is not None and target > 0:
                if current >= target:
                    status = "target_exceeded" if current > target else "target_reached"
            elif target is not None and target == 0 and current >= 0:
                status = "target_reached"

        progress = None
        if target is not None and target > 0:
            progress = (agg.metric_value / target).quantize(Decimal("0.0001"))

        proxy_note = None
        if metric_key in _ENGAGEMENT_PROXY_KEYS:
            proxy_note = "Observed engagement/awareness proxy — not a sales or lead conversion."

        results.append(
            KpiProgressResult(
                kpi_id=kpi.id,
                campaign_id=campaign_id,
                metric_key=metric_key,
                target_value=target,
                current_value=agg.metric_value,
                comparator=kpi.comparator,
                status=status,
                progress_ratio=progress,
                confidence=agg.confidence,
                freshness_status=next(iter(freshness_statuses)) if len(freshness_statuses) == 1 else "mixed",
                evidence={
                    "attribution_scope": agg.attribution_scope,
                    "publication_count": agg.publication_count,
                    "aggregation_method": agg.aggregation_method,
                    "proxy_note": proxy_note,
                },
            )
        )

    if results:
        await emit_domain_event(
            db,
            "campaign.kpi_progress_updated",
            tenant_id,
            payload={
                "campaign_id": str(campaign_id),
                "kpi_count": len(results),
                "statuses": [r.status for r in results],
            },
            resource_type="campaign",
            resource_id=str(campaign_id),
            title="Campaign KPI progress updated",
        )
    return results


__all__ = [
    "attributed_publications",
    "recalculate_campaign_aggregates",
    "evaluate_campaign_kpis",
]
