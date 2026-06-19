"""Buyer Intelligence v2 — read-only buyer scoring endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.buyer_intelligence import (
    BuyerIntelligenceDetail,
    BuyerIntelligenceOverview,
    BuyerIntelligenceSummaryWidget,
    BuyerListResponse,
    BuyerRecalculateRequest,
    BuyerRecalculateResponse,
    BuyerRisksResponse,
    BuyerTopBuyersResponse,
)
from app.services.buyer_intelligence_service import BuyerIntelligenceService

router = APIRouter(prefix="/buyer-intelligence", tags=["buyer-intelligence"])


@router.get("/overview", response_model=BuyerIntelligenceOverview)
async def buyer_intelligence_overview(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope — filters to tenant-owned clients"),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerIntelligenceService.overview(db, client_id=client_id, tenant_id=tenant_id),
        label="buyer_intelligence.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/buyers", response_model=BuyerListResponse)
async def buyer_intelligence_buyers(
    client_id: UUID | None = None,
    classification: str | None = Query(
        None,
        description="hot_buyer | strategic_buyer | high_potential_buyer | active_buyer | "
        "inactive_buyer | price_sensitive_buyer | at_risk_buyer",
    ),
    min_score: int | None = Query(None, ge=0, le=100),
    max_score: int | None = Query(None, ge=0, le=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerIntelligenceService.list_buyers(
            db,
            client_id=client_id,
            classification=classification,
            min_score=min_score,
            max_score=max_score,
            skip=skip,
            limit=limit,
        ),
        label="buyer_intelligence.buyers",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/top-buyers", response_model=BuyerTopBuyersResponse)
async def buyer_intelligence_top_buyers(
    client_id: UUID | None = None,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerIntelligenceService.top_buyers(db, client_id=client_id, limit=limit),
        label="buyer_intelligence.top_buyers",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/risks", response_model=BuyerRisksResponse)
async def buyer_intelligence_risks(
    client_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerIntelligenceService.risks(db, client_id=client_id, limit=limit),
        label="buyer_intelligence.risks",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary-widget", response_model=BuyerIntelligenceSummaryWidget)
async def buyer_intelligence_summary_widget(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerIntelligenceService.summary_widget(db, client_id=client_id),
        label="buyer_intelligence.summary_widget",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/{buyer_id}", response_model=BuyerIntelligenceDetail)
async def buyer_intelligence_detail(
    buyer_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerIntelligenceService.buyer_detail(db, buyer_id),
        label="buyer_intelligence.detail",
    )


@router.post("/recalculate", response_model=BuyerRecalculateResponse)
async def buyer_intelligence_recalculate(
    body: BuyerRecalculateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or BuyerRecalculateRequest()
    return await run_guarded(
        BuyerIntelligenceService.recalculate(
            db,
            client_id=req.client_id,
            limit=req.limit,
        ),
        label="buyer_intelligence.recalculate",
        timeout=SCAN_TIMEOUT_SEC,
    )
