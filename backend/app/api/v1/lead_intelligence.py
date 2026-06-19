"""Lead Auto Classification v1 — read-only intelligence endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.lead_classification import (
    LeadClassifyRequest,
    LeadClassifyResponse,
    LeadClassificationDetail,
    LeadClassificationListResponse,
    LeadClassificationOverview,
    LeadRecalculateRequest,
    LeadRecalculateResponse,
)
from app.services.lead_classification_service import LeadClassificationService

router = APIRouter(prefix="/lead-intelligence", tags=["lead-intelligence"])


@router.get("/overview", response_model=LeadClassificationOverview)
async def lead_intelligence_overview(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        LeadClassificationService.overview(db, client_id=client_id),
        label="lead_intelligence.overview",
    )


@router.get("/leads", response_model=LeadClassificationListResponse)
async def lead_intelligence_leads(
    client_id: UUID | None = None,
    classification: str | None = Query(
        None, description="hot | qualified | nurturing | cold | inactive",
    ),
    min_score: int | None = Query(None, ge=0, le=100),
    max_score: int | None = Query(None, ge=0, le=100),
    activity: str = Query("all", description="active | stale | inactive | all"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        LeadClassificationService.list_leads(
            db,
            client_id=client_id,
            classification=classification,
            min_score=min_score,
            max_score=max_score,
            activity=activity,
            skip=skip,
            limit=limit,
        ),
        label="lead_intelligence.leads",
    )


@router.get("/{lead_id}", response_model=LeadClassificationDetail)
async def lead_intelligence_detail(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        LeadClassificationService.lead_detail(db, lead_id),
        label="lead_intelligence.detail",
    )


@router.post("/classify", response_model=LeadClassifyResponse)
async def lead_intelligence_classify(
    body: LeadClassifyRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or LeadClassifyRequest()
    return await run_guarded(
        LeadClassificationService.classify_batch(
            db,
            lead_ids=req.lead_ids or None,
            client_id=req.client_id,
        ),
        label="lead_intelligence.classify",
    )


@router.post("/recalculate", response_model=LeadRecalculateResponse)
async def lead_intelligence_recalculate(
    body: LeadRecalculateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or LeadRecalculateRequest()
    return await run_guarded(
        LeadClassificationService.recalculate(
            db,
            client_id=req.client_id,
            limit=req.limit,
        ),
        label="lead_intelligence.recalculate",
    )
