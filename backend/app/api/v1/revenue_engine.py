"""Revenue Engine v1 — deal pipeline, forecasting, and factory revenue endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_auth_context import scoped_tenant_id_dependency
from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.revenue_engine import (
    RevenueEngineDealsResponse,
    RevenueEngineFactoriesResponse,
    RevenueEngineForecastResponse,
    RevenueEngineGuidedActionsResponse,
    RevenueEngineHealthResponse,
    RevenueEngineOpportunitiesResponse,
    RevenueEngineOverview,
    RevenueEnginePipelineResponse,
    RevenueEngineRefreshResponse,
    RevenueEngineSummary,
)
from app.services.revenue_engine_service import RevenueEngineService

router = APIRouter(prefix="/revenue-engine", tags=["revenue-engine"])


@router.get("/overview", response_model=RevenueEngineOverview)
async def revenue_engine_overview(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.overview(db, client_id=client_id, tenant_id=tenant_id),
        label="revenue_engine.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/deals", response_model=RevenueEngineDealsResponse)
async def revenue_engine_deals(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    stage: str | None = Query(
        None,
        description="lead | qualified | negotiation | quotation | sample | contract | won | lost",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.list_deals(
            db,
            client_id=client_id,
            tenant_id=tenant_id,
            stage=stage,
            skip=skip,
            limit=limit,
        ),
        label="revenue_engine.deals",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/pipeline", response_model=RevenueEnginePipelineResponse)
async def revenue_engine_pipeline(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.pipeline(db, client_id=client_id, tenant_id=tenant_id),
        label="revenue_engine.pipeline",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/forecast", response_model=RevenueEngineForecastResponse)
async def revenue_engine_forecast(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.forecast(db, client_id=client_id, tenant_id=tenant_id),
        label="revenue_engine.forecast",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/factories", response_model=RevenueEngineFactoriesResponse)
async def revenue_engine_factories(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.factories(
            db, client_id=client_id, tenant_id=tenant_id, skip=skip, limit=limit,
        ),
        label="revenue_engine.factories",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/opportunities", response_model=RevenueEngineOpportunitiesResponse)
async def revenue_engine_opportunities(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.opportunities(db, client_id=client_id, tenant_id=tenant_id),
        label="revenue_engine.opportunities",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/health", response_model=RevenueEngineHealthResponse)
async def revenue_engine_health(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.health(db, client_id=client_id, tenant_id=tenant_id),
        label="revenue_engine.health",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary", response_model=RevenueEngineSummary)
async def revenue_engine_summary(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.summary(db, client_id=client_id, tenant_id=tenant_id),
        label="revenue_engine.summary",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/actions", response_model=RevenueEngineGuidedActionsResponse)
async def revenue_engine_actions(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.guided_actions(db, client_id=client_id, tenant_id=tenant_id),
        label="revenue_engine.actions",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary-widget")
async def revenue_engine_summary_widget(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.summary_widget(db, client_id=client_id, tenant_id=tenant_id),
        label="revenue_engine.summary_widget",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/revenue-impact-panel")
async def revenue_engine_revenue_impact_panel(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.revenue_impact_panel(
            db, client_id=client_id, tenant_id=tenant_id,
        ),
        label="revenue_engine.revenue_impact_panel",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/revenue-readiness-panel")
async def revenue_engine_revenue_readiness_panel(
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.revenue_readiness_panel(db, tenant_id=tenant_id),
        label="revenue_engine.revenue_readiness_panel",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/revenue-performance-panel")
async def revenue_engine_revenue_performance_panel(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueEngineService.revenue_performance_panel(
            db, client_id=client_id, tenant_id=tenant_id,
        ),
        label="revenue_engine.revenue_performance_panel",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/refresh", response_model=RevenueEngineRefreshResponse)
async def revenue_engine_refresh(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Depends(scoped_tenant_id_dependency()),
    db: AsyncSession = Depends(get_db),
):
    return await RevenueEngineService.refresh(
        db, client_id=client_id, tenant_id=tenant_id,
    )
