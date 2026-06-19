from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.partner import (
    PartnerActivityCreate,
    PartnerActivityResponse,
    PartnerAiInsightsResponse,
    PartnerCreate,
    PartnerFiltersResponse,
    PartnerHubResponse,
    PartnerListResponse,
    PartnerMatchLeadResponse,
    PartnerMatchProductResponse,
    PartnerPerformanceResponse,
    PartnerResponse,
    PartnerUpdate,
)
from app.services.partner_service import PartnerService

router = APIRouter(prefix="/partners", tags=["partners"])


@router.get("", response_model=PartnerListResponse)
async def list_partners(
    status: str | None = Query(None, description="active | inactive"),
    search: str | None = None,
    country: str | None = None,
    partner_type: str | None = None,
    industry: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PartnerService.list_partners(
            db,
            status=status,
            search=search,
            country=country,
            partner_type=partner_type,
            industry=industry,
            skip=skip,
            limit=limit,
        ),
        label="partners.list",
    )


@router.get("/filters/list", response_model=PartnerFiltersResponse)
async def partner_filters(db: AsyncSession = Depends(get_db)):
    return await PartnerService.list_filters(db)


@router.post("", response_model=PartnerResponse, status_code=201)
async def create_partner(
    body: PartnerCreate,
    db: AsyncSession = Depends(get_db),
):
    return await PartnerService.create_partner(db, body)


@router.post("/match-product/{product_id}", response_model=PartnerMatchProductResponse)
async def match_partners_for_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PartnerService.match_product(db, product_id),
        label="partners.match_product",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/match-lead/{lead_id}", response_model=PartnerMatchLeadResponse)
async def match_partners_for_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PartnerService.match_lead(db, lead_id),
        label="partners.match_lead",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/{partner_id}", response_model=PartnerResponse)
async def get_partner(
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await PartnerService.get_partner(db, partner_id)


@router.get("/{partner_id}/hub", response_model=PartnerHubResponse)
async def get_partner_hub(
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PartnerService.get_hub(db, partner_id),
        label="partners.hub",
    )


@router.post("/{partner_id}/activities", response_model=PartnerActivityResponse, status_code=201)
async def add_partner_activity(
    partner_id: UUID,
    body: PartnerActivityCreate,
    db: AsyncSession = Depends(get_db),
):
    return await PartnerService.add_activity(
        db,
        partner_id,
        activity_type=body.activity_type,
        description=body.description,
    )


@router.patch("/{partner_id}", response_model=PartnerResponse)
async def update_partner(
    partner_id: UUID,
    body: PartnerUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await PartnerService.update_partner(db, partner_id, body)


@router.delete("/{partner_id}", status_code=204)
async def delete_partner(
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await PartnerService.delete_partner(db, partner_id)


@router.get("/{partner_id}/performance", response_model=PartnerPerformanceResponse)
async def partner_performance(
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PartnerService.performance(db, partner_id),
        label="partners.performance",
    )


@router.post("/{partner_id}/insights", response_model=PartnerAiInsightsResponse)
async def partner_ai_insights(
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await PartnerService.ai_insights(db, partner_id)
