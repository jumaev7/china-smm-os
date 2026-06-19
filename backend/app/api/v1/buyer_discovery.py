"""Export Buyer Discovery Engine v1 — read-only buyer discovery endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.buyer_discovery import (
    BuyerDiscoveryExecutiveInsights,
    BuyerDiscoveryOverview,
    BuyerDiscoveryRecalculateRequest,
    BuyerDiscoveryRecalculateResponse,
    BuyerDiscoverySummaryWidget,
    BuyerMarketInsightsResponse,
    BuyerPipelineResponse,
    BuyerRegistryResponse,
    BuyerTopOpportunitiesResponse,
)
from app.services.buyer_discovery_service import BuyerDiscoveryService

router = APIRouter(prefix="/buyer-discovery", tags=["buyer-discovery"])


@router.get("/overview", response_model=BuyerDiscoveryOverview)
async def buyer_discovery_overview(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope — filters to tenant-owned clients"),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerDiscoveryService.overview(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_discovery.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/buyers", response_model=BuyerRegistryResponse)
async def buyer_discovery_buyers(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    category: str | None = Query(
        None,
        description="high_potential | strategic | active | new | watchlist",
    ),
    pipeline_stage: str | None = Query(
        None,
        description="discovered | researched | qualified | contacted | opportunity | customer",
    ),
    min_score: int | None = Query(None, ge=0, le=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerDiscoveryService.list_buyers(
            db,
            client_id=client_id,
            tenant_id=tenant_id,
            category=category,
            pipeline_stage=pipeline_stage,
            min_score=min_score,
            skip=skip,
            limit=limit,
        ),
        label="buyer_discovery.buyers",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/top-opportunities", response_model=BuyerTopOpportunitiesResponse)
async def buyer_discovery_top_opportunities(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerDiscoveryService.top_opportunities(
            db, client_id=client_id, tenant_id=tenant_id, limit=limit,
        ),
        label="buyer_discovery.top_opportunities",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/market-insights", response_model=BuyerMarketInsightsResponse)
async def buyer_discovery_market_insights(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerDiscoveryService.market_insights(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_discovery.market_insights",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/pipeline", response_model=BuyerPipelineResponse)
async def buyer_discovery_pipeline(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerDiscoveryService.pipeline(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_discovery.pipeline",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary-widget", response_model=BuyerDiscoverySummaryWidget)
async def buyer_discovery_summary_widget(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerDiscoveryService.summary_widget(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_discovery.summary_widget",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/executive-insights", response_model=BuyerDiscoveryExecutiveInsights)
async def buyer_discovery_executive_insights(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerDiscoveryService.executive_insights(
            db, client_id=client_id, tenant_id=tenant_id, limit=limit,
        ),
        label="buyer_discovery.executive_insights",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/recalculate", response_model=BuyerDiscoveryRecalculateResponse)
async def buyer_discovery_recalculate(
    body: BuyerDiscoveryRecalculateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or BuyerDiscoveryRecalculateRequest()
    return await run_guarded(
        BuyerDiscoveryService.recalculate(
            db,
            client_id=req.client_id,
            tenant_id=req.tenant_id,
            limit=req.limit,
        ),
        label="buyer_discovery.recalculate",
        timeout=SCAN_TIMEOUT_SEC,
    )
