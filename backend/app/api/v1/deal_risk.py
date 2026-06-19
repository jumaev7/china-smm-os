"""Deal Risk Engine v2 — read-only deal health endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.deal_risk import (
    DealRiskDetail,
    DealRiskHighRiskResponse,
    DealRiskListResponse,
    DealRiskOpportunitiesResponse,
    DealRiskOverview,
    DealRiskRecalculateRequest,
    DealRiskRecalculateResponse,
    DealRiskSummaryWidget,
)
from app.services.deal_risk_service import DealRiskService

router = APIRouter(prefix="/deal-risk", tags=["deal-risk"])


@router.get("/overview", response_model=DealRiskOverview)
async def deal_risk_overview(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope — filters to tenant-owned clients"),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRiskService.overview(db, client_id=client_id, tenant_id=tenant_id),
        label="deal_risk.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/deals", response_model=DealRiskListResponse)
async def deal_risk_deals(
    client_id: UUID | None = None,
    risk_level: str | None = Query(
        None,
        description="healthy | watchlist | at_risk | critical | stalled | lost_probability_high",
    ),
    min_health: int | None = Query(None, ge=0, le=100),
    max_health: int | None = Query(None, ge=0, le=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRiskService.list_deals(
            db,
            client_id=client_id,
            risk_level=risk_level,
            min_health=min_health,
            max_health=max_health,
            skip=skip,
            limit=limit,
        ),
        label="deal_risk.deals",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/high-risk", response_model=DealRiskHighRiskResponse)
async def deal_risk_high_risk(
    client_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRiskService.high_risk(db, client_id=client_id, limit=limit),
        label="deal_risk.high_risk",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/opportunities", response_model=DealRiskOpportunitiesResponse)
async def deal_risk_opportunities(
    client_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRiskService.opportunities(db, client_id=client_id, limit=limit),
        label="deal_risk.opportunities",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary-widget", response_model=DealRiskSummaryWidget)
async def deal_risk_summary_widget(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRiskService.summary_widget(db, client_id=client_id),
        label="deal_risk.summary_widget",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/{deal_id}", response_model=DealRiskDetail)
async def deal_risk_detail(
    deal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRiskService.deal_detail(db, deal_id),
        label="deal_risk.detail",
    )


@router.post("/recalculate", response_model=DealRiskRecalculateResponse)
async def deal_risk_recalculate(
    body: DealRiskRecalculateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or DealRiskRecalculateRequest()
    return await run_guarded(
        DealRiskService.recalculate(
            db,
            client_id=req.client_id,
            limit=req.limit,
        ),
        label="deal_risk.recalculate",
        timeout=SCAN_TIMEOUT_SEC,
    )
