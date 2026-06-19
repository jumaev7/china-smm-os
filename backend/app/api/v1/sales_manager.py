from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.schemas.sales_manager import (
    SalesManagerBriefingRequest,
    SalesManagerBriefingResponse,
    SalesManagerOpportunitiesResponse,
    SalesManagerOverviewResponse,
    SalesManagerRecommendationsResponse,
    SalesManagerRisksResponse,
)
from app.services.sales_manager_service import SalesManagerService

router = APIRouter(prefix="/sales-manager", tags=["sales-manager"])


@router.get("/overview", response_model=SalesManagerOverviewResponse)
async def sales_manager_overview(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesManagerService.overview(db, client_id=client_id),
        label="sales_manager.overview",
    )


@router.get("/opportunities", response_model=SalesManagerOpportunitiesResponse)
async def sales_manager_opportunities(
    client_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesManagerService.opportunities(db, client_id=client_id, limit=limit),
        label="sales_manager.opportunities",
    )


@router.get("/risks", response_model=SalesManagerRisksResponse)
async def sales_manager_risks(
    client_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesManagerService.risks(db, client_id=client_id, limit=limit),
        label="sales_manager.risks",
    )


@router.get("/recommendations", response_model=SalesManagerRecommendationsResponse)
async def sales_manager_recommendations(
    client_id: UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesManagerService.recommendations(db, client_id=client_id, limit=limit),
        label="sales_manager.recommendations",
    )


@router.post("/generate-briefing", response_model=SalesManagerBriefingResponse)
async def sales_manager_generate_briefing(
    body: SalesManagerBriefingRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    use_ai = body.use_ai if body else False
    client_id = body.client_id if body else None
    return await run_guarded(
        SalesManagerService.generate_briefing(db, use_ai=use_ai, client_id=client_id),
        label="sales_manager.generate_briefing",
        timeout=SCAN_TIMEOUT_SEC,
    )
