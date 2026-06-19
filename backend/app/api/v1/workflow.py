import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.workflow import (
    WorkflowPrepareRequest,
    WorkflowProgressResponse,
    WorkflowRetryRequest,
)
from app.services.content_service import ContentService
from app.services.workflow_service import get_progress, retry_workflow, start_workflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["workflow"])


@router.post("/{content_id}/workflow/prepare", response_model=WorkflowProgressResponse)
async def prepare_content_workflow(
    content_id: UUID,
    data: WorkflowPrepareRequest,
    db: AsyncSession = Depends(get_db),
):
    await ContentService.get(db, content_id)
    try:
        return await start_workflow(content_id, data)
    except Exception as exc:
        logger.error("Workflow start failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{content_id}/workflow/progress", response_model=WorkflowProgressResponse)
async def workflow_progress(content_id: UUID, db: AsyncSession = Depends(get_db)):
    await ContentService.get(db, content_id)
    return get_progress(content_id)


@router.post("/{content_id}/workflow/retry", response_model=WorkflowProgressResponse)
async def retry_content_workflow(
    content_id: UUID,
    data: WorkflowRetryRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    await ContentService.get(db, content_id)
    try:
        return await retry_workflow(content_id, data.step if data else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Workflow retry failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
