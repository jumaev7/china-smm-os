"""Pilot Demo Polish & Sales Presentation v1 — [PILOT_EXECUTION_V1] sales walkthrough."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.pilot_sales_demo import (
    PilotSalesDemoFactoryOwnerStory,
    PilotSalesDemoFlow,
    PilotSalesDemoMetrics,
    PilotSalesDemoOverview,
    PilotSalesDemoRefreshResponse,
    PilotSalesDemoSummaryWidget,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.pilot_sales_demo_service import PilotSalesDemoService

router = APIRouter(prefix="/pilot-sales-demo", tags=["pilot-sales-demo"])


@router.get("/overview", response_model=PilotSalesDemoOverview)
async def pilot_sales_demo_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotSalesDemoService.overview(db),
        label="pilot_sales_demo.overview",
        timeout=25.0,
    )


@router.get("/metrics", response_model=PilotSalesDemoMetrics)
async def pilot_sales_demo_metrics(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotSalesDemoService.demo_metrics(db),
        label="pilot_sales_demo.metrics",
    )


@router.get("/factory-owner-story", response_model=PilotSalesDemoFactoryOwnerStory)
async def pilot_sales_demo_factory_owner_story(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotSalesDemoService.factory_owner_story(db),
        label="pilot_sales_demo.factory_owner_story",
    )


@router.get("/demo-flow", response_model=PilotSalesDemoFlow)
async def pilot_sales_demo_flow(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
):
    return await PilotSalesDemoService.demo_flow()


@router.get("/summary-widget", response_model=PilotSalesDemoSummaryWidget)
async def pilot_sales_demo_summary_widget(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotSalesDemoService.summary_widget(db),
        label="pilot_sales_demo.summary_widget",
        timeout=25.0,
    )


@router.post("/refresh", response_model=PilotSalesDemoRefreshResponse)
async def pilot_sales_demo_refresh(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotSalesDemoService.refresh(db)
