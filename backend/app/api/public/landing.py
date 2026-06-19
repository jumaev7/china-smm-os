from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.landing_page import (
    PublicLandingLeadResponse,
    PublicLandingLeadSubmit,
    PublicLandingPageResponse,
)
from app.services.landing_page_service import LandingPageService

router = APIRouter(tags=["public-landing"])


@router.get("/landing/{slug}", response_model=PublicLandingPageResponse)
async def get_public_landing(slug: str, db: AsyncSession = Depends(get_db)):
    return await LandingPageService.get_public(db, slug)


@router.post("/landing/{slug}/lead", response_model=PublicLandingLeadResponse)
async def submit_public_landing_lead(
    slug: str,
    body: PublicLandingLeadSubmit,
    db: AsyncSession = Depends(get_db),
):
    return await LandingPageService.submit_lead(db, slug, body)
