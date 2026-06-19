"""Buyer Acquisition Platform Consolidation v1 — unified aggregation endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.buyer_acquisition import (
    BuyerAcquisitionInsights,
    BuyerAcquisitionOverview,
    BuyerAcquisitionSummaryWidget,
    UnifiedBuyersResponse,
    UnifiedOpportunitiesResponse,
    UnifiedPipelineResponse,
)
from app.services.buyer_acquisition_service import BuyerAcquisitionService

router = APIRouter(prefix="/buyer-acquisition", tags=["buyer-acquisition"])


@router.get("/overview", response_model=BuyerAcquisitionOverview)
async def buyer_acquisition_overview(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope — filters to tenant-owned clients"),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionService.overview(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_acquisition.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/buyers", response_model=UnifiedBuyersResponse)
async def buyer_acquisition_buyers(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
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
        BuyerAcquisitionService.list_buyers(
            db,
            client_id=client_id,
            tenant_id=tenant_id,
            pipeline_stage=pipeline_stage,
            min_score=min_score,
            skip=skip,
            limit=limit,
        ),
        label="buyer_acquisition.buyers",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/opportunities", response_model=UnifiedOpportunitiesResponse)
async def buyer_acquisition_opportunities(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    source: str | None = Query(None, description="marketplace | discovery | network"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionService.list_opportunities(
            db,
            client_id=client_id,
            tenant_id=tenant_id,
            source=source,
            skip=skip,
            limit=limit,
        ),
        label="buyer_acquisition.opportunities",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/pipeline", response_model=UnifiedPipelineResponse)
async def buyer_acquisition_pipeline(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionService.pipeline(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_acquisition.pipeline",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/insights", response_model=BuyerAcquisitionInsights)
async def buyer_acquisition_insights(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    limit: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionService.insights(
            db, client_id=client_id, tenant_id=tenant_id, limit=limit,
        ),
        label="buyer_acquisition.insights",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary-widget", response_model=BuyerAcquisitionSummaryWidget)
async def buyer_acquisition_summary_widget(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionService.summary_widget(
            db, client_id=client_id, tenant_id=tenant_id,
        ),
        label="buyer_acquisition.summary_widget",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/factory-readiness")
async def buyer_acquisition_factory_readiness(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    from app.services.factory_profile_service import FactoryProfileService

    return await run_guarded(
        FactoryProfileService.readiness_indicators(
            db, client_id=client_id, tenant_id=tenant_id,
        ),
        label="buyer_acquisition.factory_readiness",
        timeout=SCAN_TIMEOUT_SEC,
    )
