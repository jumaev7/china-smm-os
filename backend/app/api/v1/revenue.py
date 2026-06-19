from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.services.admin_rbac_service import CurrentAdminUser
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.revenue import (
    RevenueAiInsightsResponse,
    RevenueDealRow,
    RevenueOverviewResponse,
)
from app.services.revenue_service import RevenueService

router = APIRouter(prefix="/revenue", tags=["revenue"])


@router.get("/overview", response_model=RevenueOverviewResponse)
async def revenue_overview(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    admin: CurrentAdminUser = Depends(require_admin_permission("business.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueService.overview(db, deals_limit=limit),
        label="revenue.overview",
    )


@router.post("/deals/{deal_id}/approve-commission", response_model=RevenueDealRow)
async def approve_commission(
    deal_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("billing.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await RevenueService.approve_commission(db, deal_id)


@router.post("/deals/{deal_id}/mark-paid", response_model=RevenueDealRow)
async def mark_commission_paid(
    deal_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("billing.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await RevenueService.mark_commission_paid(db, deal_id)


@router.post("/ai-insights", response_model=RevenueAiInsightsResponse)
async def revenue_ai_insights(
    admin: CurrentAdminUser = Depends(require_admin_permission("business.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueService.ai_insights(db),
        label="revenue.ai-insights",
        timeout=25.0,
    )
