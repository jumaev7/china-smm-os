from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.operator_inbox import (
    OperatorInboxActionResponse,
    OperatorInboxAiSuggestResponse,
    OperatorInboxAiSuggestion,
    OperatorInboxGroupRequest,
    OperatorInboxGroupResponse,
    OperatorInboxListResponse,
    OperatorInboxSmartAnalyzeResponse,
)
from app.services.operator_ai_service import OperatorAiService
from app.services.operator_inbox_service import OperatorInboxService
from app.services.operator_smart_inbox_service import OperatorSmartInboxService

router = APIRouter(prefix="/operator", tags=["operator"])


@router.get("/inbox", response_model=OperatorInboxListResponse)
async def list_operator_inbox(
    status: str | None = Query(None, description="new | used | ignored"),
    client_id: UUID | None = None,
    priority: str | None = Query(None, description="high | medium | low"),
    needs_action: bool | None = None,
    auto_drafted: bool | None = None,
    grouped: bool | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        OperatorInboxService.list_inbox(
            db,
            status=status,
            client_id=client_id,
            priority=priority,
            needs_action=needs_action,
            auto_drafted=auto_drafted,
            grouped=grouped,
            skip=skip,
            limit=limit,
        ),
        label="inbox.list",
    )


@router.post("/inbox/group", response_model=OperatorInboxGroupResponse)
async def inbox_group_items(
    body: OperatorInboxGroupRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await OperatorSmartInboxService.group_inbox_items(db, body.inbox_ids)
    return OperatorInboxGroupResponse(**result)


@router.post("/inbox/{inbox_id}/create-content", response_model=OperatorInboxActionResponse)
async def inbox_create_content(
    inbox_id: UUID,
    from_group: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    result = await OperatorInboxService.create_content_from_inbox(
        db, inbox_id, from_group=from_group,
    )
    return OperatorInboxActionResponse(**result)


@router.post("/inbox/{inbox_id}/ignore", response_model=OperatorInboxActionResponse)
async def inbox_ignore(
    inbox_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await OperatorInboxService.ignore_inbox_item(db, inbox_id)
    return OperatorInboxActionResponse(**result)


@router.post("/inbox/{inbox_id}/restore", response_model=OperatorInboxActionResponse)
async def inbox_restore(
    inbox_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await OperatorInboxService.restore_inbox_item(db, inbox_id)
    return OperatorInboxActionResponse(**result)


@router.post("/inbox/{inbox_id}/ai-suggest", response_model=OperatorInboxAiSuggestResponse)
async def inbox_ai_suggest(
    inbox_id: UUID,
    force_refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    data = await OperatorAiService.suggest_for_inbox(
        db, inbox_id, force_refresh=force_refresh,
    )
    return OperatorInboxAiSuggestResponse(suggestion=OperatorInboxAiSuggestion(**data))


@router.post("/inbox/{inbox_id}/smart-analyze", response_model=OperatorInboxSmartAnalyzeResponse)
async def inbox_smart_analyze(
    inbox_id: UUID,
    force_refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    data = await OperatorSmartInboxService.smart_analyze(
        db, inbox_id, force_refresh=force_refresh,
    )
    return OperatorInboxSmartAnalyzeResponse(**data)


@router.post("/inbox/{inbox_id}/apply-ai-suggestion", response_model=OperatorInboxActionResponse)
async def inbox_apply_ai_suggestion(
    inbox_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await OperatorInboxService.apply_ai_suggestion(db, inbox_id)
    return OperatorInboxActionResponse(**result)
