from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.schemas.sales_department_v3 import (
    SalesDeptV3BriefingRequest,
    SalesDeptV3BriefingResponse,
    SalesDeptV3OpportunitiesResponse,
    SalesDeptV3OverviewResponse,
    SalesDeptV3PrioritiesResponse,
    SalesDeptV3RecommendationsResponse,
    SalesDeptV3RisksResponse,
    SalesDeptV3SummaryWidget,
)
from app.services.sales_department_orchestrator import SalesDepartmentOrchestrator

router = APIRouter(prefix="/sales-department-v3", tags=["sales-department-v3"])


@router.get("/overview", response_model=SalesDeptV3OverviewResponse)
async def sales_department_v3_overview(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesDepartmentOrchestrator.overview(db, client_id=client_id),
        label="sales_department_v3.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/priorities", response_model=SalesDeptV3PrioritiesResponse)
async def sales_department_v3_priorities(
    client_id: UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesDepartmentOrchestrator.priorities(db, client_id=client_id, limit=limit),
        label="sales_department_v3.priorities",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/opportunities", response_model=SalesDeptV3OpportunitiesResponse)
async def sales_department_v3_opportunities(
    client_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesDepartmentOrchestrator.opportunities(db, client_id=client_id, limit=limit),
        label="sales_department_v3.opportunities",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/risks", response_model=SalesDeptV3RisksResponse)
async def sales_department_v3_risks(
    client_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesDepartmentOrchestrator.risks(db, client_id=client_id, limit=limit),
        label="sales_department_v3.risks",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/recommendations", response_model=SalesDeptV3RecommendationsResponse)
async def sales_department_v3_recommendations(
    client_id: UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesDepartmentOrchestrator.recommendations(db, client_id=client_id, limit=limit),
        label="sales_department_v3.recommendations",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary-widget", response_model=SalesDeptV3SummaryWidget)
async def sales_department_v3_summary_widget(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesDepartmentOrchestrator.summary_widget(db, client_id=client_id),
        label="sales_department_v3.summary_widget",
    )


@router.post("/generate-briefing", response_model=SalesDeptV3BriefingResponse)
async def sales_department_v3_generate_briefing(
    body: SalesDeptV3BriefingRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    client_id = body.client_id if body else None
    return await run_guarded(
        SalesDepartmentOrchestrator.generate_briefing(db, client_id=client_id),
        label="sales_department_v3.generate_briefing",
        timeout=SCAN_TIMEOUT_SEC,
    )
