from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.ai_command import (
    AiCommandDetailResponse,
    AiCommandExecuteResponse,
    AiCommandHistoryResponse,
    AiCommandPlanRequest,
    AiCommandPlanResponse,
    AiCommandSuggestionsRequest,
    AiCommandSuggestionsResponse,
)
from app.services.ai_command_center_service import AiCommandCenterService
from app.services.ai_command_context_service import AiCommandContextService

router = APIRouter(prefix="/ai-command", tags=["ai-command"])


@router.post("/plan", response_model=AiCommandPlanResponse)
async def plan_ai_command(
    body: AiCommandPlanRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        AiCommandCenterService.plan(
            db,
            body.command,
            current_page=body.current_page,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            selected_items=body.selected_items,
            user_context_json=body.user_context_json,
        ),
        label="ai_command.plan",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/suggestions", response_model=AiCommandSuggestionsResponse)
async def ai_command_suggestions(
    body: AiCommandSuggestionsRequest,
    db: AsyncSession = Depends(get_db),
):
    return await AiCommandContextService.suggestions(
        db,
        current_page=body.current_page,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        selected_items=body.selected_items,
        user_context_json=body.user_context_json,
    )


@router.post("/{command_id}/execute", response_model=AiCommandExecuteResponse)
async def execute_ai_command(
    command_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        AiCommandCenterService.execute(db, command_id),
        label="ai_command.execute",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/history", response_model=AiCommandHistoryResponse)
async def ai_command_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await AiCommandCenterService.history(db, skip=skip, limit=limit)


@router.get("/{command_id}", response_model=AiCommandDetailResponse)
async def get_ai_command(
    command_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AiCommandCenterService.get_command(db, command_id)
