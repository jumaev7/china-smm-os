from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.attribution_link import (
    AttributionLinkCreate,
    AttributionLinkListResponse,
    AttributionLinkResponse,
)
from app.services.attribution_link_service import AttributionLinkService

router = APIRouter(prefix="/attribution-links", tags=["attribution-links"])


@router.post("", response_model=AttributionLinkResponse, status_code=201)
async def create_attribution_link(
    body: AttributionLinkCreate,
    db: AsyncSession = Depends(get_db),
):
    return await AttributionLinkService.create(db, body)


@router.get("", response_model=AttributionLinkListResponse)
async def list_attribution_links(
    client_id: UUID | None = None,
    campaign_id: UUID | None = None,
    product_id: UUID | None = None,
    partner_id: UUID | None = None,
    channel: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await AttributionLinkService.list_links(
        db,
        client_id=client_id,
        campaign_id=campaign_id,
        product_id=product_id,
        partner_id=partner_id,
        channel=channel,
        skip=skip,
        limit=limit,
    )
