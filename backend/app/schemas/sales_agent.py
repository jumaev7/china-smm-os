from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

RecommendationType = Literal[
    "follow_up",
    "proposal",
    "contract",
    "invoice",
    "payment_reminder",
    "partner_follow_up",
    "risk_warning",
    "opportunity",
]

RecommendationPriority = Literal["high", "medium", "low"]
RecommendationStatus = Literal["new", "accepted", "dismissed", "done"]


class SalesAgentRecommendationResponse(BaseModel):
    id: UUID
    client_id: UUID
    client_name: Optional[str] = None
    lead_id: Optional[UUID] = None
    lead_name: Optional[str] = None
    deal_id: Optional[UUID] = None
    deal_title: Optional[str] = None
    partner_id: Optional[UUID] = None
    partner_name: Optional[str] = None
    recommendation_type: RecommendationType
    title: str
    description: str
    priority: RecommendationPriority
    suggested_message: Optional[str] = None
    suggested_action: Optional[str] = None
    status: RecommendationStatus
    linked_task_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SalesAgentRecommendationListResponse(BaseModel):
    items: List[SalesAgentRecommendationResponse]
    total: int


class SalesAgentScanResponse(BaseModel):
    scanned: int
    created: int
    skipped_duplicates: int


class SalesAgentAcceptResponse(BaseModel):
    recommendation: SalesAgentRecommendationResponse
    task_id: UUID


class SalesAgentSummaryResponse(BaseModel):
    high_priority_count: int
    overdue_followups: int
    unpaid_invoices: int
    risky_deals: int
    new_recommendations: int
