"""Revenue Attribution Automation v1 — read-only analytics endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.revenue_attribution import (
    RevenueAttributionChannelsResponse,
    RevenueAttributionConversionsResponse,
    RevenueAttributionInsightsResponse,
    RevenueAttributionLeadSummary,
    RevenueAttributionOverviewResponse,
    RevenueAttributionRecalculateRequest,
    RevenueAttributionRecalculateResponse,
    RevenueAttributionSourcesResponse,
    RevenueAttributionSummaryWidget,
)
from app.services.revenue_attribution_service import RevenueAttributionService

router = APIRouter(prefix="/revenue-attribution", tags=["revenue-attribution"])


@router.get("/overview", response_model=RevenueAttributionOverviewResponse)
async def revenue_attribution_overview(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueAttributionService.overview(db, client_id=client_id),
        label="revenue_attribution.overview",
    )


@router.get("/sources", response_model=RevenueAttributionSourcesResponse)
async def revenue_attribution_sources(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueAttributionService.sources(db, client_id=client_id),
        label="revenue_attribution.sources",
    )


@router.get("/channels", response_model=RevenueAttributionChannelsResponse)
async def revenue_attribution_channels(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueAttributionService.channels(db, client_id=client_id),
        label="revenue_attribution.channels",
    )


@router.get("/conversions", response_model=RevenueAttributionConversionsResponse)
async def revenue_attribution_conversions(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueAttributionService.conversions(db, client_id=client_id),
        label="revenue_attribution.conversions",
    )


@router.get("/insights", response_model=RevenueAttributionInsightsResponse)
async def revenue_attribution_insights(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueAttributionService.insights(db, client_id=client_id),
        label="revenue_attribution.insights",
    )


@router.get("/summary-widget", response_model=RevenueAttributionSummaryWidget)
async def revenue_attribution_summary_widget(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueAttributionService.summary_widget(db, client_id=client_id),
        label="revenue_attribution.summary_widget",
    )


@router.get("/lead/{lead_id}", response_model=RevenueAttributionLeadSummary)
async def revenue_attribution_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RevenueAttributionService.lead_attribution(db, lead_id),
        label="revenue_attribution.lead",
    )


@router.post("/recalculate", response_model=RevenueAttributionRecalculateResponse)
async def revenue_attribution_recalculate(
    body: RevenueAttributionRecalculateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or RevenueAttributionRecalculateRequest()
    return await run_guarded(
        RevenueAttributionService.recalculate(db, client_id=req.client_id),
        label="revenue_attribution.recalculate",
    )
