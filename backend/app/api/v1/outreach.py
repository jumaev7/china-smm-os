from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.outreach import (
    OutreachCreateFollowUpRequest,
    OutreachGenerateRequest,
    OutreachLinkThreadRequest,
    OutreachListResponse,
    OutreachMarkSentRequest,
    OutreachMessageResponse,
    OutreachRegenerateRequest,
    OutreachUpdate,
    OutreachWorkflowResponse,
)
from app.services.buyer_outreach_service import BuyerOutreachService
from app.services.outreach_workflow_service import OutreachWorkflowService

router = APIRouter(prefix="/outreach", tags=["outreach"])


@router.post("/generate", response_model=OutreachMessageResponse, status_code=201)
async def generate_outreach(
    body: OutreachGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerOutreachService.generate(db, body),
        label="outreach.generate",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("", response_model=OutreachListResponse)
async def list_outreach(
    client_id: UUID | None = None,
    lead_id: UUID | None = None,
    product_id: UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await BuyerOutreachService.list_messages(
        db,
        client_id=client_id,
        lead_id=lead_id,
        product_id=product_id,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.get("/{outreach_id}", response_model=OutreachMessageResponse)
async def get_outreach(
    outreach_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await BuyerOutreachService.get_message(db, outreach_id)


@router.patch("/{outreach_id}", response_model=OutreachMessageResponse)
async def update_outreach(
    outreach_id: UUID,
    body: OutreachUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await BuyerOutreachService.update_message(db, outreach_id, body)


@router.post("/{outreach_id}/regenerate", response_model=OutreachMessageResponse)
async def regenerate_outreach(
    outreach_id: UUID,
    body: OutreachRegenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerOutreachService.regenerate(db, outreach_id, body),
        label="outreach.regenerate",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/{outreach_id}/approve", response_model=OutreachWorkflowResponse)
async def approve_outreach(
    outreach_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await OutreachWorkflowService.approve(db, outreach_id)


@router.post("/{outreach_id}/mark-copied", response_model=OutreachWorkflowResponse)
async def mark_outreach_copied(
    outreach_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await OutreachWorkflowService.mark_copied(db, outreach_id)


@router.post("/{outreach_id}/mark-sent", response_model=OutreachWorkflowResponse)
async def mark_outreach_sent(
    outreach_id: UUID,
    body: OutreachMarkSentRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await OutreachWorkflowService.mark_sent(db, outreach_id, body)


@router.post("/{outreach_id}/create-follow-up", response_model=OutreachWorkflowResponse)
async def create_outreach_follow_up(
    outreach_id: UUID,
    body: OutreachCreateFollowUpRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await OutreachWorkflowService.create_follow_up(db, outreach_id, body)


@router.post("/{outreach_id}/link-thread", response_model=OutreachWorkflowResponse)
async def link_outreach_thread(
    outreach_id: UUID,
    body: OutreachLinkThreadRequest,
    db: AsyncSession = Depends(get_db),
):
    return await OutreachWorkflowService.link_thread(db, outreach_id, body)
