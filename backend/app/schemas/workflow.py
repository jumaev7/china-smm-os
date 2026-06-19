from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

WorkflowStepId = Literal[
    "subtitles",
    "translations",
    "captions",
    "hashtags",
    "post_time",
    "voice",
    "export",
    "status",
]

WorkflowStepStatus = Literal["pending", "running", "completed", "failed", "skipped"]
WorkflowRunStatus = Literal["idle", "running", "completed", "failed"]


class WorkflowStepProgress(BaseModel):
    id: WorkflowStepId
    label: str
    status: WorkflowStepStatus = "pending"
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class WorkflowPrepareRequest(BaseModel):
    voice_lang: Literal["ru", "uz", "en"] = "ru"
    subtitle_lang: Literal["cn", "ru", "uz", "en"] = "ru"
    voice_mode: Literal["fitted", "extended"] = "fitted"
    source_language: Optional[str] = None
    source_text: Optional[str] = None
    context_hint: Optional[str] = None


class WorkflowRetryRequest(BaseModel):
    step: Optional[WorkflowStepId] = None


class WorkflowProgressResponse(BaseModel):
    content_id: UUID
    status: WorkflowRunStatus = "idle"
    current_step: Optional[WorkflowStepId] = None
    steps: list[WorkflowStepProgress] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    message: str = ""
    can_retry: bool = False
