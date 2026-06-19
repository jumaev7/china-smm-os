from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_auth_context import resolve_tenant_id_param
from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.schemas.revenue_forecast import (
    RevenueForecastExecutiveResponse,
    RevenueForecastGenerateRequest,
    RevenueForecastGenerateResponse,
    RevenueForecastOverviewResponse,
    RevenueForecastPipelineResponse,
    RevenueForecastRisksResponse,
    RevenueForecastSummaryWidget,
)
from app.services.revenue_forecast_service import RevenueForecastService

router = APIRouter(prefix="/revenue-forecast", tags=["revenue-forecast"])


@router.get("/overview", response_model=RevenueForecastOverviewResponse)
async def revenue_forecast_overview(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope — filters to tenant-owned clients"),
    db: AsyncSession = Depends(get_db),
):
    scoped_tenant = resolve_tenant_id_param(tenant_id)
    return await run_guarded(
        RevenueForecastService.overview(db, client_id=client_id, tenant_id=scoped_tenant),
        label="revenue_forecast.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/pipeline", response_model=RevenueForecastPipelineResponse)
async def revenue_forecast_pipeline(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueForecastService.pipeline(db, client_id=client_id),
        label="revenue_forecast.pipeline",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/risks", response_model=RevenueForecastRisksResponse)
async def revenue_forecast_risks(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueForecastService.risks(db, client_id=client_id),
        label="revenue_forecast.risks",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/executive", response_model=RevenueForecastExecutiveResponse)
async def revenue_forecast_executive(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueForecastService.executive(db, client_id=client_id),
        label="revenue_forecast.executive",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary-widget", response_model=RevenueForecastSummaryWidget)
async def revenue_forecast_summary_widget(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueForecastService.summary_widget(db, client_id=client_id),
        label="revenue_forecast.summary_widget",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/generate-forecast", response_model=RevenueForecastGenerateResponse)
async def revenue_forecast_generate(
    body: RevenueForecastGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    client_id = body.client_id if body else None
    return await run_guarded(
        RevenueForecastService.generate_forecast(db, client_id=client_id),
        label="revenue_forecast.generate_forecast",
        timeout=SCAN_TIMEOUT_SEC,
    )
