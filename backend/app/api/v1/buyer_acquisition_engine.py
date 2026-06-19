"""Buyer Acquisition Engine v1 — lead generation and matching endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.buyer_acquisition_engine import (
    BuyerEngineBuyersResponse,
    BuyerEngineCrmSummary,
    BuyerEngineGuidedActionsResponse,
    BuyerEngineMatchesResponse,
    BuyerEngineOpportunitiesResponse,
    BuyerEngineOverview,
    BuyerEnginePipelineResponse,
    BuyerEngineRefreshResponse,
)
from app.services.buyer_acquisition_engine_service import BuyerAcquisitionEngineService

router = APIRouter(prefix="/buyer-acquisition-engine", tags=["buyer-acquisition-engine"])


@router.get("/overview", response_model=BuyerEngineOverview)
async def buyer_acquisition_engine_overview(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope — filters to tenant-owned clients"),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionEngineService.overview(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_acquisition_engine.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/buyers", response_model=BuyerEngineBuyersResponse)
async def buyer_acquisition_engine_buyers(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    pipeline_status: str | None = Query(
        None,
        description="new | contacted | replied | negotiating | quotation_sent | sample_sent | won | lost",
    ),
    min_match_score: int | None = Query(None, ge=0, le=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionEngineService.list_buyers(
            db,
            client_id=client_id,
            tenant_id=tenant_id,
            pipeline_status=pipeline_status,
            min_match_score=min_match_score,
            skip=skip,
            limit=limit,
        ),
        label="buyer_acquisition_engine.buyers",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/matches", response_model=BuyerEngineMatchesResponse)
async def buyer_acquisition_engine_matches(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    min_score: int = Query(0, ge=0, le=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionEngineService.matches(
            db,
            client_id=client_id,
            tenant_id=tenant_id,
            min_score=min_score,
            skip=skip,
            limit=limit,
        ),
        label="buyer_acquisition_engine.matches",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/pipeline", response_model=BuyerEnginePipelineResponse)
async def buyer_acquisition_engine_pipeline(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionEngineService.pipeline(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_acquisition_engine.pipeline",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/opportunities", response_model=BuyerEngineOpportunitiesResponse)
async def buyer_acquisition_engine_opportunities(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionEngineService.opportunities(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_acquisition_engine.opportunities",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary", response_model=BuyerEngineCrmSummary)
async def buyer_acquisition_engine_summary(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionEngineService.summary(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_acquisition_engine.summary",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/actions", response_model=BuyerEngineGuidedActionsResponse)
async def buyer_acquisition_engine_actions(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionEngineService.guided_actions(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_acquisition_engine.actions",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary-widget")
async def buyer_acquisition_engine_summary_widget(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerAcquisitionEngineService.summary_widget(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_acquisition_engine.summary_widget",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/refresh", response_model=BuyerEngineRefreshResponse)
async def buyer_acquisition_engine_refresh(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await BuyerAcquisitionEngineService.refresh(
        db, client_id=client_id, tenant_id=tenant_id,
    )
