from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.operator_task import (
    OperatorTaskCreate,
    OperatorTaskListResponse,
    OperatorTaskResponse,
    OperatorTaskUpdate,
    TaskExecuteResponse,
    TaskSendReplyRequest,
    TaskSendReplyResponse,
)
from app.services.operator_task_service import OperatorTaskService
from app.services.task_executor_service import TaskExecutorService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=OperatorTaskListResponse)
async def list_tasks(
    status: str | None = Query(None, description="todo | in_progress | waiting_client | done | canceled"),
    client_id: UUID | None = None,
    priority: str | None = Query(None, description="high | medium | low"),
    source_type: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        OperatorTaskService.list_tasks(
            db,
            status=status,
            client_id=client_id,
            priority=priority,
            source_type=source_type,
            skip=skip,
            limit=limit,
        ),
        label="tasks.list",
    )


@router.post("", response_model=OperatorTaskResponse, status_code=201)
async def create_task(
    body: OperatorTaskCreate,
    db: AsyncSession = Depends(get_db),
):
    return await OperatorTaskService.create_task(db, body)


@router.patch("/{task_id}", response_model=OperatorTaskResponse)
async def update_task(
    task_id: UUID,
    body: OperatorTaskUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await OperatorTaskService.update_task(db, task_id, body)


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await OperatorTaskService.delete_task(db, task_id)


@router.post("/{task_id}/mark-done", response_model=OperatorTaskResponse)
async def mark_task_done(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await OperatorTaskService.set_status(db, task_id, "done")


@router.post("/{task_id}/start", response_model=OperatorTaskResponse)
async def start_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await OperatorTaskService.set_status(db, task_id, "in_progress")


@router.post("/{task_id}/wait-client", response_model=OperatorTaskResponse)
async def wait_client_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await OperatorTaskService.set_status(db, task_id, "waiting_client")


@router.post("/{task_id}/cancel", response_model=OperatorTaskResponse)
async def cancel_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await OperatorTaskService.set_status(db, task_id, "canceled")


@router.post("/{task_id}/execute", response_model=TaskExecuteResponse)
async def execute_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await TaskExecutorService.execute(db, task_id)


@router.post("/{task_id}/send-reply", response_model=TaskSendReplyResponse)
async def send_task_reply(
    task_id: UUID,
    body: TaskSendReplyRequest = TaskSendReplyRequest(),
    db: AsyncSession = Depends(get_db),
):
    return await TaskExecutorService.send_reply(db, task_id, reply_text=body.reply_text)
