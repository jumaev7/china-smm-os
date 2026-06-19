from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

PlaybookStatus = Literal["draft", "active", "archived"]
PlaybookStepType = Literal["outreach", "follow_up", "proposal", "call", "internal_task"]
PlaybookChannel = Literal["email", "whatsapp", "wechat", "linkedin"]


class SalesPlaybookStepCreate(BaseModel):
    step_order: int = Field(..., ge=1)
    step_type: PlaybookStepType
    title: str = Field(..., min_length=1, max_length=255)
    instructions: str | None = None
    template_text: str | None = None
    delay_days: int | None = Field(None, ge=0)


class SalesPlaybookStepUpdate(BaseModel):
    step_order: int | None = Field(None, ge=1)
    step_type: PlaybookStepType | None = None
    title: str | None = Field(None, min_length=1, max_length=255)
    instructions: str | None = None
    template_text: str | None = None
    delay_days: int | None = Field(None, ge=0)


class SalesPlaybookStepResponse(BaseModel):
    id: UUID
    playbook_id: UUID
    step_order: int
    step_type: PlaybookStepType
    title: str
    instructions: str | None = None
    template_text: str | None = None
    delay_days: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SalesPlaybookCreate(BaseModel):
    client_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    product_category: str | None = Field(None, max_length=100)
    buyer_type: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    language: str = "en"
    channel: PlaybookChannel
    status: PlaybookStatus = "draft"
    steps: list[SalesPlaybookStepCreate] = Field(default_factory=list)


class SalesPlaybookUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    product_category: str | None = Field(None, max_length=100)
    buyer_type: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    language: str | None = None
    channel: PlaybookChannel | None = None
    status: PlaybookStatus | None = None


class SalesPlaybookResponse(BaseModel):
    id: UUID
    client_id: UUID | None = None
    client_name: str | None = None
    name: str
    description: str | None = None
    product_category: str | None = None
    buyer_type: str | None = None
    country: str | None = None
    language: str
    channel: PlaybookChannel
    status: PlaybookStatus
    step_count: int = 0
    steps: list[SalesPlaybookStepResponse] = Field(default_factory=list)
    demo_mode: bool = False
    created_at: datetime
    updated_at: datetime


class SalesPlaybookListResponse(BaseModel):
    items: list[SalesPlaybookResponse]
    total: int


class SalesPlaybookGenerateRequest(BaseModel):
    client_id: UUID | None = None
    product_category: str = Field(..., min_length=1, max_length=100)
    buyer_type: str = Field(..., min_length=1, max_length=100)
    country: str = Field(..., min_length=1, max_length=100)
    language: str = "en"
    channel: PlaybookChannel
    name: str | None = Field(None, max_length=255)


class SalesPlaybookRecommendRequest(BaseModel):
    client_id: UUID | None = None
    product_id: UUID | None = None
    lead_id: UUID | None = None
    product_category: str | None = None
    buyer_type: str | None = None
    country: str | None = None
    language: str | None = None
    channel: str | None = None


class SalesPlaybookRecommendResponse(BaseModel):
    items: list[SalesPlaybookResponse]
    match_reasons: dict[str, list[str]] = Field(default_factory=dict)


class SalesPlaybookApplyRequest(BaseModel):
    product_id: UUID | None = None


class SalesPlaybookApplyResult(BaseModel):
    playbook_id: UUID
    lead_id: UUID
    outreach_ids: list[UUID] = Field(default_factory=list)
    proposal_ids: list[UUID] = Field(default_factory=list)
    task_ids: list[UUID] = Field(default_factory=list)
    message: str
