"""AI Operator Task Engine v1 — structured sales operator tasks."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

OperatorActionType = Literal[
    "reply_to_message",
    "follow_up",
    "create_proposal",
    "review_proposal",
    "link_lead",
    "update_deal",
    "check_payment",
    "review_hot_lead",
    "manual_sales_action",
]

EngineTaskPriority = Literal["urgent", "high", "medium", "low"]


class OperatorTaskEngineSummary(BaseModel):
    open_count: int = 0
    urgent_count: int = 0
    overdue_count: int = 0
    due_today_count: int = 0


class OperatorTaskEngineItem(BaseModel):
    id: UUID
    client_id: UUID
    company_name: Optional[str] = None
    source_type: str
    source_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    priority: str
    status: str
    action_type: Optional[str] = None
    channel: Optional[str] = None
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    recommendation_id: Optional[UUID] = None
    conversation_id: Optional[str] = None
    lead_id: Optional[UUID] = None
    lead_name: Optional[str] = None
    lead_classification: Optional[str] = None
    lead_classification_score: Optional[int] = None
    lead_classification_urgency: Optional[str] = None
    deal_id: Optional[UUID] = None
    deal_title: Optional[str] = None
    proposal_id: Optional[UUID] = None
    proposal_title: Optional[str] = None
    recommended_action: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class OperatorTaskEngineListResponse(BaseModel):
    items: List[OperatorTaskEngineItem]
    total: int
    summary: OperatorTaskEngineSummary


class OperatorTaskEngineGenerateRequest(BaseModel):
    client_id: Optional[UUID] = None


class OperatorTaskEngineGenerateResponse(BaseModel):
    scanned: int
    created: int
    skipped_duplicates: int


class OperatorTaskEngineFromConversationRequest(BaseModel):
    task_type: Optional[str] = Field(None, description="follow_up | reply | proposal | link_lead")
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    due_at: Optional[datetime] = None


class OperatorTaskEngineFromProposalRequest(BaseModel):
    due_at: Optional[datetime] = None


class OperatorTaskEngineActionResponse(BaseModel):
    task: OperatorTaskEngineItem
    message: str = ""
