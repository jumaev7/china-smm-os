from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.sales_assistant import (
    SalesAssistantCreateTaskResponse,
    SalesAssistantRecommendationListResponse,
    SalesAssistantRecommendationResponse,
    SalesAssistantScanRequest,
    SalesAssistantScanResponse,
)
from app.services.sales_assistant_service import SalesAssistantService

router = APIRouter(prefix="/sales-assistant", tags=["sales-assistant"])


@router.get("/recommendations", response_model=SalesAssistantRecommendationListResponse)
async def list_recommendations(
    status: str | None = None,
    priority: str | None = None,
    client_id: UUID | None = None,
    lead_id: UUID | None = None,
    deal_id: UUID | None = None,
    conversation_id: str | None = None,
    recommendation_type: str | None = Query(None, alias="type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesAssistantService.list_recommendations(
            db,
            status=status,
            priority=priority,
            client_id=client_id,
            lead_id=lead_id,
            deal_id=deal_id,
            conversation_id=conversation_id,
            recommendation_type=recommendation_type,
            skip=skip,
            limit=limit,
        ),
        label="sales-assistant.recommendations",
    )


@router.post("/scan", response_model=SalesAssistantScanResponse)
async def scan_sales_assistant(
    body: SalesAssistantScanRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    use_ai = body.use_ai if body else False
    return await run_guarded(
        SalesAssistantService.scan(db, use_ai=use_ai),
        label="sales-assistant.scan",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/recommendations/{recommendation_id}/dismiss", response_model=SalesAssistantRecommendationResponse)
async def dismiss_recommendation(
    recommendation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await SalesAssistantService.dismiss(db, recommendation_id)


@router.post("/recommendations/{recommendation_id}/complete", response_model=SalesAssistantRecommendationResponse)
async def complete_recommendation(
    recommendation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await SalesAssistantService.complete(db, recommendation_id)


@router.post("/recommendations/{recommendation_id}/create-task", response_model=SalesAssistantCreateTaskResponse)
async def create_task_from_recommendation(
    recommendation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await SalesAssistantService.create_task(db, recommendation_id)
