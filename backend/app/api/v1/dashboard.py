from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.dashboard import DashboardAiSummaryResponse, DashboardOverviewResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverviewResponse)
async def dashboard_overview(db: AsyncSession = Depends(get_db)):
    return await run_guarded(
        DashboardService.overview(db),
        label="dashboard.overview",
    )


@router.post("/ai-summary", response_model=DashboardAiSummaryResponse)
async def dashboard_ai_summary(db: AsyncSession = Depends(get_db)):
    return await run_guarded(
        DashboardService.ai_summary(db),
        label="dashboard.ai-summary",
        timeout=25.0,
    )
