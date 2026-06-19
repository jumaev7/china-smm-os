from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.campaign import (
    CampaignAssignContentRequest,
    CampaignAssignContentResponse,
    CampaignUnassignContentResponse,
    CampaignCreate,
    CampaignDetailResponse,
    CampaignListResponse,
    CampaignUpdate,
)
from app.services.campaign_service import CampaignService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=CampaignListResponse)
async def list_campaigns(
    client_id: UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await CampaignService.list_campaigns(
        db, client_id=client_id, status=status, skip=skip, limit=limit,
    )


@router.post("", response_model=CampaignDetailResponse, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    db: AsyncSession = Depends(get_db),
):
    created = await CampaignService.create_campaign(db, body)
    return await CampaignService.get_campaign(db, created["id"])


@router.get("/{campaign_id}", response_model=CampaignDetailResponse)
async def get_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await CampaignService.get_campaign(db, campaign_id)


@router.patch("/{campaign_id}", response_model=CampaignDetailResponse)
async def update_campaign(
    campaign_id: UUID,
    body: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
):
    await CampaignService.update_campaign(db, campaign_id, body)
    return await CampaignService.get_campaign(db, campaign_id)


@router.post("/{campaign_id}/assign-content", response_model=CampaignAssignContentResponse)
async def assign_content_to_campaign(
    campaign_id: UUID,
    body: CampaignAssignContentRequest,
    db: AsyncSession = Depends(get_db),
):
    return await CampaignService.assign_content(db, campaign_id, body.content_ids)


@router.post("/{campaign_id}/unassign-content", response_model=CampaignUnassignContentResponse)
async def unassign_content_from_campaign(
    campaign_id: UUID,
    body: CampaignAssignContentRequest,
    db: AsyncSession = Depends(get_db),
):
    return await CampaignService.unassign_content(db, campaign_id, body.content_ids)
