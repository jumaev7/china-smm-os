from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.unified_inbox import (
    UnifiedConversationDetailResponse,
    UnifiedConversationListResponse,
    UnifiedInboxCreateTaskRequest,
    UnifiedInboxCreateTaskResponse,
    UnifiedInboxLinkDealRequest,
    UnifiedInboxLinkLeadRequest,
    UnifiedInboxLinkResponse,
)
from app.services.unified_inbox_service import UnifiedInboxService

router = APIRouter(prefix="/unified-inbox", tags=["unified-inbox"])


@router.get("", response_model=UnifiedConversationListResponse)
async def list_conversations(
    channel: str | None = None,
    country: str | None = None,
    company: str | None = None,
    linked: str | None = None,
    unread: bool | None = None,
    priority: str | None = None,
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await UnifiedInboxService.list_conversations(
        db,
        channel=channel,
        country=country,
        company=company,
        linked=linked,
        unread=unread,
        priority=priority,
        search=search,
        skip=skip,
        limit=limit,
    )


@router.get("/{conversation_id}", response_model=UnifiedConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    return await UnifiedInboxService.get_conversation(db, conversation_id)


@router.post("/{conversation_id}/link-lead", response_model=UnifiedInboxLinkResponse)
async def link_lead(
    conversation_id: str,
    body: UnifiedInboxLinkLeadRequest,
    db: AsyncSession = Depends(get_db),
):
    return await UnifiedInboxService.link_lead(db, conversation_id, body.lead_id)


@router.post("/{conversation_id}/link-deal", response_model=UnifiedInboxLinkResponse)
async def link_deal(
    conversation_id: str,
    body: UnifiedInboxLinkDealRequest,
    db: AsyncSession = Depends(get_db),
):
    return await UnifiedInboxService.link_deal(db, conversation_id, body.deal_id)


@router.post("/{conversation_id}/create-task", response_model=UnifiedInboxCreateTaskResponse, status_code=201)
async def create_task(
    conversation_id: str,
    body: UnifiedInboxCreateTaskRequest,
    db: AsyncSession = Depends(get_db),
):
    return await UnifiedInboxService.create_task(db, conversation_id, body)
