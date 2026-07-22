"""Tenant-scoped Marketing Intelligence Phase 2 measurement APIs.

Prefix: /measurement. Cross-tenant access resolves to 404 via service errors.
Clients cannot inject tenant_id or metric observation values.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.measurement import (
    AggregateResponse,
    AnomalyResponse,
    AttributionResponse,
    BaselineResponse,
    CampaignMeasurementResponse,
    ConfigurationResponse,
    FreshnessResponse,
    KpiProgressResponse,
    OverviewResponse,
    PerformanceResponse,
    PlatformCapabilityResponse,
    PublicationListResponse,
    PublicationResponse,
    RefreshResponse,
    SnapshotListResponse,
    SnapshotResponse,
    TrackedLinkCreateRequest,
    TrackedLinkListResponse,
    TrackedLinkResponse,
)
from app.services.measurement.aggregation_service import get_publication_aggregates
from app.services.measurement.attribution_service import list_attribution_for_campaign
from app.services.measurement.campaign_measurement import (
    attributed_publications,
    evaluate_campaign_kpis,
)
from app.services.measurement.errors import MeasurementError
from app.services.measurement.metric_ingestion_service import refresh_publication
from app.services.measurement.publication_registry import get_publication, list_publications
from app.services.measurement.read_service import (
    configuration_payload,
    freshness_overview,
    get_campaign_aggregates,
    list_anomalies,
    list_snapshots,
    measurement_overview,
    platform_capabilities,
    require_campaign,
)
from app.services.measurement.tracked_link_service import (
    create_tracked_link,
    disable_tracked_link,
    get_tracked_link,
    list_tracked_links,
)
from app.services.performance_intelligence.content_performance import (
    classify_relative_performance,
)
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/measurement", tags=["measurement"])


async def _guarded(coro, *, label: str):
    try:
        return await run_guarded(coro, label=label)
    except MeasurementError as exc:
        raise exc.to_http() from exc


def _publication_dict(p) -> dict:
    return {
        "id": p.id,
        "content_id": p.content_id,
        "content_variant_id": p.content_variant_id,
        "publishing_account_id": p.publishing_account_id,
        "platform": p.platform,
        "provider_publication_id": p.provider_publication_id,
        "provider_permalink": p.provider_permalink,
        "publication_status": p.publication_status,
        "published_at": p.published_at,
        "first_seen_at": p.first_seen_at,
        "last_seen_at": p.last_seen_at,
        "last_metric_at": p.last_metric_at,
        "freshness_status": p.freshness_status,
        "generation_method": p.generation_method,
        "campaign_id": p.campaign_id,
        "campaign_plan_version_id": p.campaign_plan_version_id,
        "campaign_slot_id": p.campaign_slot_id,
        "assignment_id": p.assignment_id,
        "publish_attempt_id": p.publish_attempt_id,
        "content_pillar_id": p.content_pillar_id,
        "campaign_phase_id": p.campaign_phase_id,
        "locale": p.locale,
        "is_mock": bool(p.is_mock),
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def _snapshot_dict(s) -> dict:
    return {
        "id": s.id,
        "external_publication_id": s.external_publication_id,
        "platform": s.platform,
        "observed_at": s.observed_at,
        "provider_data_timestamp": s.provider_data_timestamp,
        "snapshot_fingerprint": s.snapshot_fingerprint,
        "ingestion_run_id": s.ingestion_run_id,
        "status": s.status,
        "source": s.source,
        "created_at": s.created_at,
    }


def _aggregate_dict(a) -> dict:
    return {
        "id": a.id,
        "external_publication_id": getattr(a, "external_publication_id", None),
        "campaign_id": getattr(a, "campaign_id", None),
        "window_key": getattr(a, "window_key", None),
        "window_start": a.window_start,
        "window_end": a.window_end,
        "metric_key": a.metric_key,
        "metric_value": a.metric_value,
        "calculation_method": getattr(a, "calculation_method", None),
        "calculation_version": getattr(a, "calculation_version", None),
        "aggregation_method": getattr(a, "aggregation_method", None),
        "attribution_scope": getattr(a, "attribution_scope", None),
        "freshness_status": getattr(a, "freshness_status", None),
        "confidence": a.confidence,
        "publication_count": getattr(a, "publication_count", None),
        "source_snapshot_ids": getattr(a, "source_snapshot_ids", None),
        "calculated_at": a.calculated_at,
    }


def _kpi_dict(k) -> dict:
    return {
        "kpi_id": k.kpi_id,
        "campaign_id": k.campaign_id,
        "metric_key": k.metric_key,
        "target_value": k.target_value,
        "current_value": k.current_value,
        "comparator": k.comparator,
        "status": k.status,
        "progress_ratio": k.progress_ratio,
        "confidence": k.confidence,
        "freshness_status": k.freshness_status,
        "evidence": k.evidence or {},
    }


def _attribution_dict(a) -> dict:
    return {
        "id": a.id,
        "entity_type": a.entity_type,
        "entity_id": a.entity_id,
        "source_type": a.source_type,
        "source_id": a.source_id,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "attribution_method": a.attribution_method,
        "confidence": a.confidence,
        "evidence": a.evidence or {},
        "status": a.status,
        "created_at": a.created_at,
    }


def _tracked_link_dict(row) -> dict:
    return {
        "id": row.id,
        "destination_url": row.destination_url,
        "tracking_code": row.tracking_code,
        "campaign_id": row.campaign_id,
        "content_id": row.content_id,
        "content_variant_id": row.content_variant_id,
        "platform": row.platform,
        "status": row.status,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "disabled_at": row.disabled_at,
    }


def _anomaly_dict(a) -> dict:
    return {
        "id": a.id,
        "external_publication_id": a.external_publication_id,
        "metric_snapshot_id": a.metric_snapshot_id,
        "anomaly_key": a.anomaly_key,
        "severity": a.severity,
        "metric_key": a.metric_key,
        "evidence": a.evidence or {},
        "status": a.status,
        "created_at": a.created_at,
        "resolved_at": a.resolved_at,
    }


def _performance_dict(result) -> dict:
    baseline = None
    if result.baseline is not None:
        baseline = BaselineResponse(
            metric_key=result.baseline.metric_key,
            platform=result.baseline.platform,
            sample_size=result.baseline.sample_size,
            median=result.baseline.median,
            mean=result.baseline.mean,
            p75=result.baseline.p75,
            lookback_days=result.baseline.lookback_days,
            sufficient=result.baseline.sufficient,
        )
    return {
        "entity_type": result.entity_type,
        "entity_id": result.entity_id,
        "metric_key": result.metric_key,
        "classification": result.classification,
        "value": result.value,
        "baseline": baseline,
        "delta_ratio": result.delta_ratio,
        "evidence": result.evidence or {},
    }


# ===========================================================================
# Publications
# ===========================================================================


@router.get("/publications", response_model=PublicationListResponse)
async def list_publications_endpoint(
    platform: str | None = Query(None),
    campaign_id: UUID | None = Query(None),
    freshness_status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await _guarded(
        list_publications(
            db,
            user.tenant_id,
            platform=platform,
            campaign_id=campaign_id,
            freshness_status=freshness_status,
            limit=limit,
            offset=offset,
        ),
        label="measurement.list_publications",
    )
    return PublicationListResponse(
        items=[PublicationResponse(**_publication_dict(p)) for p in items],
        total=total,
    )


@router.get("/publications/{publication_id}", response_model=PublicationResponse)
async def get_publication_endpoint(
    publication_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    pub = await _guarded(
        get_publication(db, user.tenant_id, publication_id),
        label="measurement.get_publication",
    )
    return PublicationResponse(**_publication_dict(pub))


@router.get("/publications/{publication_id}/snapshots", response_model=SnapshotListResponse)
async def list_publication_snapshots(
    publication_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await _guarded(
        get_publication(db, user.tenant_id, publication_id),
        label="measurement.get_publication_for_snapshots",
    )
    items, total = await _guarded(
        list_snapshots(
            db, user.tenant_id, publication_id, limit=limit, offset=offset,
        ),
        label="measurement.list_snapshots",
    )
    return SnapshotListResponse(
        items=[SnapshotResponse(**_snapshot_dict(s)) for s in items],
        total=total,
    )


@router.get("/publications/{publication_id}/metrics", response_model=list[AggregateResponse])
async def get_publication_metrics(
    publication_id: UUID,
    window_key: str | None = Query(None),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await _guarded(
        get_publication(db, user.tenant_id, publication_id),
        label="measurement.get_publication_for_metrics",
    )
    rows = await _guarded(
        get_publication_aggregates(
            db, user.tenant_id, publication_id, window_key=window_key,
        ),
        label="measurement.get_publication_metrics",
    )
    return [AggregateResponse(**_aggregate_dict(a)) for a in rows]


@router.get("/publications/{publication_id}/performance", response_model=PerformanceResponse)
async def get_publication_performance(
    publication_id: UUID,
    metric_key: str = Query("engagements"),
    window_key: str = Query("lifetime"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    pub = await _guarded(
        get_publication(db, user.tenant_id, publication_id),
        label="measurement.get_publication_for_performance",
    )
    result = await _guarded(
        classify_relative_performance(
            db,
            user.tenant_id,
            publication_id=publication_id,
            metric_key=metric_key,
            window_key=window_key,
        ),
        label="measurement.publication_performance",
    )
    payload = _performance_dict(result)
    payload["freshness_status"] = pub.freshness_status
    return PerformanceResponse(**payload)


@router.post("/publications/{publication_id}/refresh", response_model=RefreshResponse)
async def refresh_publication_endpoint(
    publication_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _guarded(
        refresh_publication(db, user.tenant_id, publication_id),
        label="measurement.refresh_publication",
    )
    await db.commit()
    return RefreshResponse(
        ingestion_run_id=run.id,
        publication_id=publication_id,
        platform=run.platform,
        status=run.status,
        publications_requested=run.publications_requested,
        publications_succeeded=run.publications_succeeded,
        publications_failed=run.publications_failed,
        failure_code=run.failure_code,
        requested_at=run.requested_at,
        completed_at=run.completed_at,
    )


# ===========================================================================
# Campaigns
# ===========================================================================


@router.get("/campaigns/{campaign_id}", response_model=CampaignMeasurementResponse)
async def get_campaign_measurement(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await _guarded(
        require_campaign(db, user.tenant_id, campaign_id),
        label="measurement.campaign_exists",
    )
    pubs = await _guarded(
        attributed_publications(db, user.tenant_id, campaign_id),
        label="measurement.campaign_publications",
    )
    metrics = await _guarded(
        get_campaign_aggregates(db, user.tenant_id, campaign_id),
        label="measurement.campaign_metrics",
    )
    kpis = await _guarded(
        evaluate_campaign_kpis(db, user.tenant_id, campaign_id),
        label="measurement.campaign_kpis",
    )
    attrs = await _guarded(
        list_attribution_for_campaign(db, user.tenant_id, campaign_id),
        label="measurement.campaign_attribution",
    )
    freshness_statuses = {p.freshness_status for p in pubs}
    freshness = next(iter(freshness_statuses)) if len(freshness_statuses) == 1 else (
        "mixed" if freshness_statuses else "unavailable"
    )
    confidences = [m.confidence for m in metrics]
    confidence = min(confidences) if confidences else None
    return CampaignMeasurementResponse(
        campaign_id=campaign_id,
        publication_count=len(pubs),
        metrics=[AggregateResponse(**_aggregate_dict(m)) for m in metrics],
        kpi_progress=[KpiProgressResponse(**_kpi_dict(k)) for k in kpis],
        attribution=[AttributionResponse(**_attribution_dict(a)) for a in attrs],
        freshness_status=freshness,
        confidence=confidence,
    )


@router.get("/campaigns/{campaign_id}/metrics", response_model=list[AggregateResponse])
async def get_campaign_metrics(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await _guarded(
        get_campaign_aggregates(db, user.tenant_id, campaign_id),
        label="measurement.campaign_metrics_only",
    )
    return [AggregateResponse(**_aggregate_dict(a)) for a in rows]


@router.get("/campaigns/{campaign_id}/kpis", response_model=list[KpiProgressResponse])
async def get_campaign_kpis(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await _guarded(
        evaluate_campaign_kpis(db, user.tenant_id, campaign_id),
        label="measurement.campaign_kpis_only",
    )
    return [KpiProgressResponse(**_kpi_dict(k)) for k in rows]


@router.get("/campaigns/{campaign_id}/attribution", response_model=list[AttributionResponse])
async def get_campaign_attribution(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await _guarded(
        require_campaign(db, user.tenant_id, campaign_id),
        label="measurement.campaign_exists_for_attribution",
    )
    rows = await _guarded(
        list_attribution_for_campaign(db, user.tenant_id, campaign_id),
        label="measurement.campaign_attribution_only",
    )
    return [AttributionResponse(**_attribution_dict(a)) for a in rows]


@router.get(
    "/campaigns/{campaign_id}/content-performance",
    response_model=list[PerformanceResponse],
)
async def get_campaign_content_performance(
    campaign_id: UUID,
    metric_key: str = Query("engagements"),
    window_key: str = Query("lifetime"),
    limit: int = Query(50, ge=1, le=200),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    pubs = await _guarded(
        attributed_publications(db, user.tenant_id, campaign_id),
        label="measurement.campaign_content_performance",
    )
    results: list[PerformanceResponse] = []
    for pub in pubs[:limit]:
        classification = await classify_relative_performance(
            db,
            user.tenant_id,
            publication_id=pub.id,
            metric_key=metric_key,
            window_key=window_key,
        )
        payload = _performance_dict(classification)
        payload["freshness_status"] = pub.freshness_status
        results.append(PerformanceResponse(**payload))
    return results


# ===========================================================================
# Tenant overview / platforms / content performance / freshness / anomalies
# ===========================================================================


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        measurement_overview(db, user.tenant_id),
        label="measurement.overview",
    )
    return OverviewResponse(**data)


@router.get("/platforms", response_model=list[PlatformCapabilityResponse])
async def get_platforms(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    _ = user.tenant_id
    return [PlatformCapabilityResponse(**p) for p in platform_capabilities()]


@router.get("/content-performance", response_model=list[PerformanceResponse])
async def get_content_performance(
    metric_key: str = Query("engagements"),
    window_key: str = Query("lifetime"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    pubs, _total = await _guarded(
        list_publications(db, user.tenant_id, limit=limit, offset=offset),
        label="measurement.content_performance_pubs",
    )
    results: list[PerformanceResponse] = []
    for pub in pubs:
        classification = await classify_relative_performance(
            db,
            user.tenant_id,
            publication_id=pub.id,
            metric_key=metric_key,
            window_key=window_key,
        )
        payload = _performance_dict(classification)
        payload["freshness_status"] = pub.freshness_status
        results.append(PerformanceResponse(**payload))
    return results


@router.get("/freshness", response_model=FreshnessResponse)
async def get_freshness(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        freshness_overview(db, user.tenant_id),
        label="measurement.freshness",
    )
    return FreshnessResponse(**data)


@router.get("/anomalies", response_model=list[AnomalyResponse])
async def get_anomalies(
    status: str | None = Query("open"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, _total = await _guarded(
        list_anomalies(
            db, user.tenant_id, status=status, limit=limit, offset=offset,
        ),
        label="measurement.anomalies",
    )
    return [AnomalyResponse(**_anomaly_dict(a)) for a in items]


@router.get("/configuration", response_model=ConfigurationResponse)
async def get_configuration(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    _ = user.tenant_id
    return ConfigurationResponse(**configuration_payload())


# ===========================================================================
# Tracked links
# ===========================================================================


@router.get("/tracked-links", response_model=TrackedLinkListResponse)
async def list_tracked_links_endpoint(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await _guarded(
        list_tracked_links(
            db, user.tenant_id, status=status, limit=limit, offset=offset,
        ),
        label="measurement.list_tracked_links",
    )
    return TrackedLinkListResponse(
        items=[TrackedLinkResponse(**_tracked_link_dict(r)) for r in items],
        total=total,
    )


@router.post("/tracked-links", response_model=TrackedLinkResponse)
async def create_tracked_link_endpoint(
    body: TrackedLinkCreateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _guarded(
        create_tracked_link(
            db,
            user.tenant_id,
            destination_url=body.destination_url,
            campaign_id=body.campaign_id,
            content_id=body.content_id,
            content_variant_id=body.content_variant_id,
            platform=body.platform,
            created_by=user.id,
        ),
        label="measurement.create_tracked_link",
    )
    await db.commit()
    return TrackedLinkResponse(**_tracked_link_dict(row))


@router.get("/tracked-links/{link_id}", response_model=TrackedLinkResponse)
async def get_tracked_link_endpoint(
    link_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _guarded(
        get_tracked_link(db, user.tenant_id, link_id),
        label="measurement.get_tracked_link",
    )
    return TrackedLinkResponse(**_tracked_link_dict(row))


@router.post("/tracked-links/{link_id}/disable", response_model=TrackedLinkResponse)
async def disable_tracked_link_endpoint(
    link_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _guarded(
        disable_tracked_link(db, user.tenant_id, link_id),
        label="measurement.disable_tracked_link",
    )
    await db.commit()
    return TrackedLinkResponse(**_tracked_link_dict(row))
