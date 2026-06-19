from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

PipelineStage = Literal[
    "draft",
    "internal_review",
    "client_review",
    "approved",
    "scheduled",
    "published",
    "failed",
]

PIPELINE_STAGES: tuple[str, ...] = (
    "draft",
    "internal_review",
    "client_review",
    "approved",
    "scheduled",
    "published",
    "failed",
)


class PipelineBoardCard(BaseModel):
    id: UUID
    client_id: UUID
    client_name: str | None = None
    campaign_id: UUID | None = None
    campaign_name: str | None = None
    platforms: list[str]
    status: str
    pipeline_stage: str
    thumbnail_url: str | None = None
    media_url: str | None = None
    scheduled_for: datetime | None = None
    client_review_status: str | None = None
    approved_at: datetime | None = None
    published_at: datetime | None = None
    caption_preview: str | None = None
    has_failed_publish_attempt: bool = False
    allowed_transitions: list[str] = Field(default_factory=list)


class PipelineBoardResponse(BaseModel):
    stages: dict[str, list[PipelineBoardCard]]
    counts: dict[str, int]
    total: int


class PipelineStageTransitionRequest(BaseModel):
    stage: PipelineStage
    reason: str | None = Field(None, max_length=500)
    scheduled_for: datetime | None = None


class PipelineStageTransitionResponse(BaseModel):
    ok: bool
    content_id: UUID
    pipeline_stage: str
    status: str
    message: str | None = None
