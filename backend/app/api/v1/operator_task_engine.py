from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.operator_task_engine import (
    OperatorTaskEngineActionResponse,
    OperatorTaskEngineFromConversationRequest,
    OperatorTaskEngineFromProposalRequest,
    OperatorTaskEngineGenerateRequest,
    OperatorTaskEngineGenerateResponse,
    OperatorTaskEngineListResponse,
)
from app.services.operator_task_engine_service import OperatorTaskEngineService

router = APIRouter(prefix="/operator-task-engine", tags=["operator-task-engine"])


@router.get("/tasks", response_model=OperatorTaskEngineListResponse)
async def list_engine_tasks(
    status: str | None = None,
    client_id: UUID | None = None,
    priority: str | None = None,
    action_type: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        OperatorTaskEngineService.list_tasks(
            db,
            status=status,
            client_id=client_id,
            priority=priority,
            action_type=action_type,
            skip=skip,
            limit=limit,
        ),
        label="operator-task-engine.list",
    )


@router.post("/generate", response_model=OperatorTaskEngineGenerateResponse)
async def generate_engine_tasks(
    body: OperatorTaskEngineGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    client_id = body.client_id if body else None
    return await run_guarded(
        OperatorTaskEngineService.generate(db, client_id=client_id),
        label="operator-task-engine.generate",
    )


@router.post(
    "/from-recommendation/{recommendation_id}",
    response_model=OperatorTaskEngineActionResponse,
)
async def create_from_recommendation(
    recommendation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await OperatorTaskEngineService.from_recommendation(db, recommendation_id)


@router.post(
    "/from-conversation/{conversation_id}",
    response_model=OperatorTaskEngineActionResponse,
)
async def create_from_conversation(
    conversation_id: str,
    body: OperatorTaskEngineFromConversationRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload = body or OperatorTaskEngineFromConversationRequest()
    return await OperatorTaskEngineService.from_conversation(
        db,
        conversation_id,
        task_type=payload.task_type,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        due_at=payload.due_at,
    )


@router.post(
    "/from-proposal/{proposal_id}",
    response_model=OperatorTaskEngineActionResponse,
)
async def create_from_proposal(
    proposal_id: UUID,
    body: OperatorTaskEngineFromProposalRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload = body or OperatorTaskEngineFromProposalRequest()
    return await OperatorTaskEngineService.from_proposal(
        db, proposal_id, due_at=payload.due_at,
    )


@router.post("/{task_id}/complete", response_model=OperatorTaskEngineActionResponse)
async def complete_engine_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await OperatorTaskEngineService.complete(db, task_id)


@router.post("/{task_id}/dismiss", response_model=OperatorTaskEngineActionResponse)
async def dismiss_engine_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await OperatorTaskEngineService.dismiss(db, task_id)
