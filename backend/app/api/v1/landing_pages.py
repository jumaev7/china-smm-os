from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.landing_page import (
    LandingPageCreate,
    LandingPageListResponse,
    LandingPageResponse,
    LandingPageUpdate,
    PublicLandingLeadResponse,
    PublicLandingLeadSubmit,
    PublicLandingPageResponse,
)
from app.services.landing_page_service import LandingPageService

router = APIRouter(prefix="/landing-pages", tags=["landing-pages"])


@router.post("", response_model=LandingPageResponse, status_code=201)
async def create_landing_page(
    body: LandingPageCreate,
    db: AsyncSession = Depends(get_db),
):
    return await LandingPageService.create(db, body)


@router.get("", response_model=LandingPageListResponse)
async def list_landing_pages(
    client_id: UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await LandingPageService.list_pages(
        db, client_id=client_id, status=status, skip=skip, limit=limit,
    )


@router.get("/{page_id}", response_model=LandingPageResponse)
async def get_landing_page(
    page_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await LandingPageService.get_page(db, page_id)


@router.patch("/{page_id}", response_model=LandingPageResponse)
async def update_landing_page(
    page_id: UUID,
    body: LandingPageUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await LandingPageService.update(db, page_id, body)
