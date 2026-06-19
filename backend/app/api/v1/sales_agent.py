from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.sales_agent import (
    SalesAgentAcceptResponse,
    SalesAgentRecommendationListResponse,
    SalesAgentRecommendationResponse,
    SalesAgentScanResponse,
    SalesAgentSummaryResponse,
)
from app.services.sales_agent_service import SalesAgentService

router = APIRouter(prefix="/sales-agent", tags=["sales-agent"])


@router.post("/scan", response_model=SalesAgentScanResponse)
async def scan_sales_agent(db: AsyncSession = Depends(get_db)):
    return await run_guarded(
        SalesAgentService.scan(db),
        label="sales-agent.scan",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/recommendations", response_model=SalesAgentRecommendationListResponse)
async def list_recommendations(
    status: str | None = None,
    priority: str | None = None,
    client_id: UUID | None = None,
    recommendation_type: str | None = Query(None, alias="type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesAgentService.list_recommendations(
            db,
            status=status,
            priority=priority,
            client_id=client_id,
            recommendation_type=recommendation_type,
            skip=skip,
            limit=limit,
        ),
        label="sales-agent.recommendations",
    )


@router.get("/summary", response_model=SalesAgentSummaryResponse)
async def sales_agent_summary(db: AsyncSession = Depends(get_db)):
    return await run_guarded(
        SalesAgentService.summary(db),
        label="sales-agent.summary",
    )


@router.post("/recommendations/{recommendation_id}/accept", response_model=SalesAgentAcceptResponse)
async def accept_recommendation(
    recommendation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await SalesAgentService.accept(db, recommendation_id)


@router.post("/recommendations/{recommendation_id}/dismiss", response_model=SalesAgentRecommendationResponse)
async def dismiss_recommendation(
    recommendation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await SalesAgentService.dismiss(db, recommendation_id)


@router.post("/recommendations/{recommendation_id}/mark-done", response_model=SalesAgentRecommendationResponse)
async def mark_done_recommendation(
    recommendation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await SalesAgentService.mark_done(db, recommendation_id)
