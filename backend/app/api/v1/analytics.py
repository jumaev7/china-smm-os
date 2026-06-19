from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.analytics import (
    AnalyticsActivityResponse,
    AnalyticsOverviewResponse,
    AnalyticsPlatformsResponse,
)
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverviewResponse)
async def analytics_overview(db: AsyncSession = Depends(get_db)):
    """Summary counts, posts over time, success rate, and top clients."""
    return await AnalyticsService.overview(db)


@router.get("/platforms", response_model=AnalyticsPlatformsResponse)
async def analytics_platforms(db: AsyncSession = Depends(get_db)):
    """Posts and publish attempts grouped by platform."""
    return await AnalyticsService.platforms(db)


@router.get("/activity", response_model=AnalyticsActivityResponse)
async def analytics_activity(db: AsyncSession = Depends(get_db)):
    """Daily publishing volume and recent publish attempts."""
    return await AnalyticsService.activity(db)
