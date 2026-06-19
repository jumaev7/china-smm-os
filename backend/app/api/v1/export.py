from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.export import (
    ExportAnalyzeProductResponse,
    ExportDashboardResponse,
    ExportOpportunityDetailResponse,
    ExportOpportunityListResponse,
)
from app.services.export_agent_service import ExportAgentService

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/dashboard", response_model=ExportDashboardResponse)
async def export_dashboard(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await ExportAgentService.dashboard(db, limit=limit)


@router.get("/opportunities", response_model=ExportOpportunityListResponse)
async def list_export_opportunities(
    client_id: UUID | None = None,
    product_id: UUID | None = None,
    country: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ExportAgentService.list_opportunities(
            db,
            client_id=client_id,
            product_id=product_id,
            country=country,
            skip=skip,
            limit=limit,
        ),
        label="export.opportunities",
    )


@router.get("/opportunities/{opportunity_id}", response_model=ExportOpportunityDetailResponse)
async def get_export_opportunity(
    opportunity_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ExportAgentService.get_opportunity(db, opportunity_id)


@router.post("/analyze-product/{product_id}", response_model=ExportAnalyzeProductResponse)
async def analyze_product_export(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ExportAgentService.analyze_product(db, product_id),
        label="export.analyze_product",
        timeout=SCAN_TIMEOUT_SEC,
    )
