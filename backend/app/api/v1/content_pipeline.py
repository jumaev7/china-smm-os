from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.content_pipeline import (
    PipelineBoardResponse,
    PipelineStageTransitionRequest,
    PipelineStageTransitionResponse,
)
from app.services.content_pipeline_service import ContentPipelineService

router = APIRouter(prefix="/content-pipeline", tags=["content-pipeline"])


@router.get("/board", response_model=PipelineBoardResponse)
async def pipeline_board(
    client_id: UUID | None = None,
    campaign_id: UUID | None = None,
    platform: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await ContentPipelineService.board(
        db,
        client_id=client_id,
        campaign_id=campaign_id,
        platform=platform,
        status=status,
    )


@router.patch("/items/{content_id}/stage", response_model=PipelineStageTransitionResponse)
async def pipeline_transition(
    content_id: UUID,
    body: PipelineStageTransitionRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ContentPipelineService.transition_stage(db, content_id, body)


@router.post("/items/{content_id}/retry-publish")
async def pipeline_retry_publish(
    content_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ContentPipelineService.retry_publish(db, content_id)
