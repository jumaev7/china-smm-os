"""Marketplace & Lead Exchange v1 — opportunity exchange endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.marketplace import (
    MarketplaceActivityResponse,
    MarketplaceClaimOpportunityRequest,
    MarketplaceClaimOpportunityResponse,
    MarketplaceCreateOpportunityRequest,
    MarketplaceCreateOpportunityResponse,
    MarketplaceExpressInterestRequest,
    MarketplaceExpressInterestResponse,
    MarketplaceInsightsResponse,
    MarketplaceOpportunityListResponse,
    MarketplaceOverview,
    MarketplaceTopOpportunitiesResponse,
)
from app.services.marketplace_service import MarketplaceService

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


@router.get("/overview", response_model=MarketplaceOverview)
async def marketplace_overview(
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MarketplaceService.overview(db, tenant_id=tenant_id),
        label="marketplace.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/opportunities", response_model=MarketplaceOpportunityListResponse)
async def marketplace_opportunities(
    country: str | None = None,
    industry: str | None = None,
    opportunity_type: str | None = None,
    min_value: float | None = Query(None, ge=0),
    max_value: float | None = Query(None, ge=0),
    status: str | None = None,
    tenant_id: UUID | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MarketplaceService.list_opportunities(
            db,
            country=country,
            industry=industry,
            opportunity_type=opportunity_type,
            min_value=min_value,
            max_value=max_value,
            status=status,
            tenant_id=tenant_id,
            skip=skip,
            limit=limit,
        ),
        label="marketplace.opportunities",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/top-opportunities", response_model=MarketplaceTopOpportunitiesResponse)
async def marketplace_top_opportunities(
    tenant_id: UUID | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MarketplaceService.top_opportunities(db, tenant_id=tenant_id, limit=limit),
        label="marketplace.top_opportunities",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/insights", response_model=MarketplaceInsightsResponse)
async def marketplace_insights(
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MarketplaceService.insights(db, tenant_id=tenant_id),
        label="marketplace.insights",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/activity", response_model=MarketplaceActivityResponse)
async def marketplace_activity(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MarketplaceService.activity(db, limit=limit),
        label="marketplace.activity",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/create-opportunity", response_model=MarketplaceCreateOpportunityResponse)
async def marketplace_create_opportunity(
    body: MarketplaceCreateOpportunityRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MarketplaceService.create_opportunity(
            db,
            title=body.title,
            buyer_company=body.buyer_company,
            description=body.description,
            country=body.country,
            industry=body.industry,
            opportunity_type=body.opportunity_type,
            estimated_value=body.estimated_value,
            visibility=body.visibility,
            created_by_tenant=body.created_by_tenant,
        ),
        label="marketplace.create_opportunity",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/express-interest", response_model=MarketplaceExpressInterestResponse)
async def marketplace_express_interest(
    body: MarketplaceExpressInterestRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MarketplaceService.express_interest(
            db,
            opportunity_id=body.opportunity_id,
            tenant_id=body.tenant_id,
            note=body.note,
        ),
        label="marketplace.express_interest",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/claim-opportunity", response_model=MarketplaceClaimOpportunityResponse)
async def marketplace_claim_opportunity(
    body: MarketplaceClaimOpportunityRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MarketplaceService.claim_opportunity(
            db,
            opportunity_id=body.opportunity_id,
            tenant_id=body.tenant_id,
        ),
        label="marketplace.claim_opportunity",
        timeout=SCAN_TIMEOUT_SEC,
    )
