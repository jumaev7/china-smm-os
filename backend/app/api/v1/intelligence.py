"""Read-only Marketing Intelligence Platform APIs."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.intelligence import (
    MarketingHealthResponse,
    MarketingHistoryResponse,
    MarketingInsightListResponse,
    MarketingRecommendationListResponse,
    MarketingScoreListResponse,
    MarketingSignalListResponse,
)
from app.services.intelligence.service import IntelligenceService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get("/health", response_model=MarketingHealthResponse)
async def intelligence_health(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        IntelligenceService.get_health(db, user.tenant_id),
        label="intelligence.health",
    )
    await db.commit()
    return result


@router.get("/signals", response_model=MarketingSignalListResponse)
async def list_signals(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    signal_type: str | None = None,
    source: str | None = None,
    severity: str | None = None,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        IntelligenceService.list_signals(
            db,
            user.tenant_id,
            signal_type=signal_type,
            source=source,
            severity=severity,
            page=page,
            page_size=page_size,
        ),
        label="intelligence.signals",
    )


@router.get("/scores", response_model=MarketingScoreListResponse)
async def list_scores(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        IntelligenceService.list_scores(db, user.tenant_id),
        label="intelligence.scores",
    )
    await db.commit()
    return result


@router.get("/recommendations", response_model=MarketingRecommendationListResponse)
async def list_recommendations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: str | None = Query("open"),
    category: str | None = None,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        IntelligenceService.list_recommendations(
            db,
            user.tenant_id,
            status=status,
            category=category,
            page=page,
            page_size=page_size,
        ),
        label="intelligence.recommendations",
    )


@router.get("/insights", response_model=MarketingInsightListResponse)
async def list_insights(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        IntelligenceService.list_insights(
            db, user.tenant_id, page=page, page_size=page_size,
        ),
        label="intelligence.insights",
    )


@router.get("/history", response_model=MarketingHistoryResponse)
async def intelligence_history(
    days: int = Query(30, ge=1, le=365),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        IntelligenceService.get_history(db, user.tenant_id, days=days),
        label="intelligence.history",
    )
