from datetime import date, datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

PlanStatus = Literal["draft", "approved"]
PlanItemStatus = Literal["planned", "draft_created"]
ContentPlanType = Literal["image", "video", "carousel", "story"]


class ContentPlanGenerateRequest(BaseModel):
    client_id: UUID
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2020, le=2100)
    posts_per_month: int = Field(default=8, ge=1, le=60)


class ContentPlanItemResponse(BaseModel):
    id: UUID
    planned_date: date
    theme: str
    goal: str
    platform_suggestions: List[str] = Field(default_factory=list)
    content_type: ContentPlanType
    status: PlanItemStatus
    linked_content_id: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContentPlanItemUpdate(BaseModel):
    id: UUID
    planned_date: Optional[date] = None
    theme: Optional[str] = Field(None, max_length=500)
    goal: Optional[str] = None
    platform_suggestions: Optional[List[str]] = None
    content_type: Optional[ContentPlanType] = None
    status: Optional[PlanItemStatus] = None


class ContentPlanResponse(BaseModel):
    id: UUID
    client_id: UUID
    company_name: Optional[str] = None
    month: int
    year: int
    title: str
    status: PlanStatus
    posts_per_month: int
    items: List[ContentPlanItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ContentPlanUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    items: Optional[List[ContentPlanItemUpdate]] = None


class ContentPlanCreateDraftRequest(BaseModel):
    generate_ai: bool = True


class ContentPlanDraftResponse(BaseModel):
    ok: bool
    created: bool
    message: str
    plan_item_id: UUID
    content_id: UUID
    ai_generated: bool = False
    ai_error: Optional[str] = None
