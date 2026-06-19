from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

RecommendationType = Literal[
    "reply_needed",
    "follow_up_needed",
    "proposal_needed",
    "lead_link_needed",
    "deal_update_needed",
    "hot_lead",
    "stalled_deal",
    "missing_task",
    "playbook_recommended",
]

RecommendationPriority = Literal["low", "medium", "high", "urgent"]
RecommendationStatus = Literal["open", "dismissed", "completed"]


class SalesAssistantRecommendationResponse(BaseModel):
    id: UUID
    client_id: Optional[UUID] = None
    client_name: Optional[str] = None
    lead_id: Optional[UUID] = None
    lead_name: Optional[str] = None
    deal_id: Optional[UUID] = None
    deal_title: Optional[str] = None
    conversation_id: Optional[str] = None
    channel: Optional[str] = None
    recommendation_type: RecommendationType
    priority: RecommendationPriority
    title: str
    summary: str
    recommended_action: str
    reason: str
    status: RecommendationStatus
    linked_task_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SalesAssistantSummary(BaseModel):
    open_count: int = 0
    urgent_count: int = 0
    follow_ups_needed: int = 0
    proposals_needed: int = 0


class SalesAssistantRecommendationListResponse(BaseModel):
    items: List[SalesAssistantRecommendationResponse]
    total: int
    summary: SalesAssistantSummary


class SalesAssistantScanRequest(BaseModel):
    use_ai: bool = False


class SalesAssistantScanResponse(BaseModel):
    scanned: int
    created: int
    skipped_duplicates: int


class SalesAssistantCreateTaskResponse(BaseModel):
    recommendation: SalesAssistantRecommendationResponse
    task_id: UUID
