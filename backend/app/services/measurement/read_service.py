"""Thin read orchestration for measurement HTTP APIs.

Composes existing measurement / performance services. Does not invent metrics.
"""
from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_planner import TenantMarketingCampaign
from app.models.measurement import (
    ATTRIBUTION_METHODS,
    CALCULATION_VERSION,
    FRESHNESS_STATUSES,
    MEASUREMENT_VERSION,
    METRIC_SEMANTICS_VERSION,
    WINDOW_KEYS,
    TenantCampaignMetricAggregate,
    TenantExternalPublication,
    TenantMeasurementAnomaly,
    TenantPublicationMetricSnapshot,
    TenantTrackedLink,
)
from app.services.measurement.errors import CampaignNotFoundError
from app.services.measurement.limits import (
    MAX_BASELINE_LOOKBACK_DAYS,
    MAX_PUBLICATIONS_PER_INGESTION_RUN,
    MAX_REFRESH_REQUESTS_PER_TENANT_PER_HOUR,
    MAX_SNAPSHOTS_PER_PUBLICATION_PER_DAY,
    MAX_TRACKED_LINKS,
)
from app.services.measurement.metric_catalog import ALL_METRIC_KEYS, CATALOG_VERSION
from app.services.measurement.providers import get_adapter, registered_platforms
from app.services.measurement.schemas import MEASUREMENT_SERVICE_VERSION


async def require_campaign(
    db: AsyncSession,
    tenant_id: UUID,
    campaign_id: UUID,
) -> TenantMarketingCampaign:
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


async def get_campaign_aggregates(
    db: AsyncSession,
    tenant_id: UUID,
    campaign_id: UUID,
) -> list[TenantCampaignMetricAggregate]:
    await require_campaign(db, tenant_id, campaign_id)
    return list(
        (
            await db.execute(
                select(TenantCampaignMetricAggregate)
                .where(
                    TenantCampaignMetricAggregate.tenant_id == tenant_id,
                    TenantCampaignMetricAggregate.campaign_id == campaign_id,
                    TenantCampaignMetricAggregate.calculation_version == CALCULATION_VERSION,
                )
                .order_by(TenantCampaignMetricAggregate.metric_key.asc())
            )
        ).scalars().all()
    )


async def list_snapshots(
    db: AsyncSession,
    tenant_id: UUID,
    publication_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[TenantPublicationMetricSnapshot], int]:
    filters = [
        TenantPublicationMetricSnapshot.tenant_id == tenant_id,
        TenantPublicationMetricSnapshot.external_publication_id == publication_id,
    ]
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(TenantPublicationMetricSnapshot).where(*filters)
            )
        ).scalar_one()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(TenantPublicationMetricSnapshot)
                .where(*filters)
                .order_by(TenantPublicationMetricSnapshot.observed_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    return rows, total


async def list_anomalies(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    status: str | None = "open",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[TenantMeasurementAnomaly], int]:
    filters = [TenantMeasurementAnomaly.tenant_id == tenant_id]
    if status:
        filters.append(TenantMeasurementAnomaly.status == status)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(TenantMeasurementAnomaly).where(*filters)
            )
        ).scalar_one()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(TenantMeasurementAnomaly)
                .where(*filters)
                .order_by(TenantMeasurementAnomaly.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    return rows, total


async def freshness_overview(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    rows = list(
        (
            await db.execute(
                select(TenantExternalPublication.freshness_status).where(
                    TenantExternalPublication.tenant_id == tenant_id,
                )
            )
        ).scalars().all()
    )
    counts = Counter(rows)
    dominant = "unavailable"
    if counts:
        dominant = counts.most_common(1)[0][0]
    return {
        "status": dominant,
        "age_seconds": None,
        "last_observation_at": None,
        "reason": "tenant_freshness_rollup",
        "counts_by_status": {k: int(v) for k, v in sorted(counts.items())},
    }


async def measurement_overview(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    pubs = list(
        (
            await db.execute(
                select(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_id,
                )
            )
        ).scalars().all()
    )
    freshness = Counter(p.freshness_status for p in pubs)
    open_anomalies = int(
        (
            await db.execute(
                select(func.count())
                .select_from(TenantMeasurementAnomaly)
                .where(
                    TenantMeasurementAnomaly.tenant_id == tenant_id,
                    TenantMeasurementAnomaly.status == "open",
                )
            )
        ).scalar_one()
        or 0
    )
    tracked_links = int(
        (
            await db.execute(
                select(func.count())
                .select_from(TenantTrackedLink)
                .where(
                    TenantTrackedLink.tenant_id == tenant_id,
                    TenantTrackedLink.status == "active",
                )
            )
        ).scalar_one()
        or 0
    )
    return {
        "publication_count": len(pubs),
        "fresh_count": freshness.get("fresh", 0),
        "aging_count": freshness.get("aging", 0),
        "stale_count": freshness.get("stale", 0),
        "unavailable_count": freshness.get("unavailable", 0),
        "unsupported_count": freshness.get("unsupported", 0),
        "open_anomaly_count": open_anomalies,
        "tracked_link_count": tracked_links,
        "platforms": sorted({p.platform for p in pubs}),
        "catalog_version": CATALOG_VERSION,
        "measurement_version": MEASUREMENT_VERSION,
    }


def platform_capabilities(*, account_status: str = "connected") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for platform in sorted(registered_platforms()):
        caps = get_adapter(platform).capabilities(account_status=account_status)
        items.append({
            "platform": caps.platform,
            "capability_status": caps.capability_status,
            "supports_post_level_metrics": caps.supports_post_level_metrics,
            "supported_metric_keys": sorted(caps.supported_metric_keys),
            "unsupported_reason": caps.unsupported_reason,
            "notes": caps.notes,
        })
    return items


def configuration_payload() -> dict[str, Any]:
    return {
        "catalog_version": CATALOG_VERSION,
        "measurement_version": MEASUREMENT_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "metric_semantics_version": METRIC_SEMANTICS_VERSION,
        "metric_keys": sorted(ALL_METRIC_KEYS),
        "window_keys": sorted(WINDOW_KEYS),
        "attribution_methods": sorted(ATTRIBUTION_METHODS),
        "freshness_statuses": sorted(FRESHNESS_STATUSES),
        "platforms": platform_capabilities(),
        "limits": {
            "max_publications_per_ingestion_run": MAX_PUBLICATIONS_PER_INGESTION_RUN,
            "max_snapshots_per_publication_per_day": MAX_SNAPSHOTS_PER_PUBLICATION_PER_DAY,
            "max_refresh_requests_per_tenant_per_hour": MAX_REFRESH_REQUESTS_PER_TENANT_PER_HOUR,
            "max_baseline_lookback_days": MAX_BASELINE_LOOKBACK_DAYS,
            "max_tracked_links": MAX_TRACKED_LINKS,
        },
        "service_version": MEASUREMENT_SERVICE_VERSION,
    }


__all__ = [
    "require_campaign",
    "get_campaign_aggregates",
    "list_snapshots",
    "list_anomalies",
    "freshness_overview",
    "measurement_overview",
    "platform_capabilities",
    "configuration_payload",
]
