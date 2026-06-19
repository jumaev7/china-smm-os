"""Communication Intelligence v1 — read-only conversation analysis endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.communication_intelligence import (
    CommunicationAnalyzeRequest,
    CommunicationAnalyzeResponse,
    CommunicationIntelligenceDetail,
    CommunicationIntelligenceListResponse,
    CommunicationIntelligenceOverview,
    CommunicationRecalculateRequest,
    CommunicationRecalculateResponse,
)
from app.services.communication_intelligence_service import CommunicationIntelligenceService

router = APIRouter(prefix="/communication-intelligence", tags=["communication-intelligence"])


@router.get("/overview", response_model=CommunicationIntelligenceOverview)
async def communication_intelligence_overview(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CommunicationIntelligenceService.overview(db, client_id=client_id),
        label="communication_intelligence.overview",
    )


@router.get("/conversations", response_model=CommunicationIntelligenceListResponse)
async def communication_intelligence_conversations(
    client_id: UUID | None = None,
    channel: str | None = Query(None, description="wechat | whatsapp | email | manual | wecom"),
    classification: str | None = Query(
        None, description="inquiry | qualification | negotiation | proposal | closing | inactive",
    ),
    urgency: str | None = Query(None, description="urgent | high | medium | low"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CommunicationIntelligenceService.list_conversations(
            db,
            client_id=client_id,
            channel=channel,
            classification=classification,
            urgency=urgency,
            skip=skip,
            limit=limit,
        ),
        label="communication_intelligence.conversations",
    )


@router.get("/conversations/{conversation_id}", response_model=CommunicationIntelligenceDetail)
async def communication_intelligence_detail(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CommunicationIntelligenceService.analyze_conversation(db, conversation_id),
        label="communication_intelligence.detail",
    )


@router.post("/analyze", response_model=CommunicationAnalyzeResponse)
async def communication_intelligence_analyze(
    body: CommunicationAnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or CommunicationAnalyzeRequest()
    return await run_guarded(
        CommunicationIntelligenceService.analyze_batch(
            db,
            conversation_ids=req.conversation_ids or None,
            client_id=req.client_id,
        ),
        label="communication_intelligence.analyze",
    )


@router.post("/recalculate", response_model=CommunicationRecalculateResponse)
async def communication_intelligence_recalculate(
    body: CommunicationRecalculateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or CommunicationRecalculateRequest()
    return await run_guarded(
        CommunicationIntelligenceService.recalculate(
            db,
            client_id=req.client_id,
            limit=req.limit,
        ),
        label="communication_intelligence.recalculate",
    )
