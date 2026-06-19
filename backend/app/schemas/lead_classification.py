"""Lead Auto Classification v1 — read-only sales intelligence schemas."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

LeadClassification = Literal["hot", "qualified", "nurturing", "cold", "inactive"]
UrgencyLevel = Literal["urgent", "high", "medium", "low"]
ActivityFilter = Literal["active", "stale", "inactive", "all"]


class LeadClassificationResult(BaseModel):
    classification: LeadClassification
    score: int = Field(ge=0, le=100)
    reasons: List[str] = Field(default_factory=list)


class LeadIntelligenceRecommendations(BaseModel):
    next_recommended_action: str = ""
    follow_up_recommendation: Optional[str] = None
    proposal_recommendation: Optional[str] = None
    urgency_level: UrgencyLevel = "medium"


class LeadClassificationOverview(BaseModel):
    hot_leads: int = 0
    qualified_leads: int = 0
    nurturing_leads: int = 0
    cold_leads: int = 0
    inactive_leads: int = 0
    total_classified: int = 0
    errors: List[str] = Field(default_factory=list)


class LeadClassificationListItem(BaseModel):
    lead_id: UUID
    name: str
    company: Optional[str] = None
    score: int
    classification: LeadClassification
    last_activity_at: Optional[datetime] = None
    recommended_action: str = ""
    status: str = "new"
    client_id: UUID


class LeadClassificationListResponse(BaseModel):
    items: List[LeadClassificationListItem]
    total: int


class LeadLinkedThread(BaseModel):
    thread_id: UUID
    channel: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    message_count: int = 0


class LeadLinkedProposal(BaseModel):
    proposal_id: UUID
    title: str
    status: str
    updated_at: Optional[datetime] = None


class LeadClassificationDetail(BaseModel):
    lead_id: UUID
    name: str
    company: Optional[str] = None
    status: str
    client_id: UUID
    classification: LeadClassification
    score: int
    reasons: List[str] = Field(default_factory=list)
    recommendations: LeadIntelligenceRecommendations
    linked_crm: dict = Field(default_factory=dict)
    linked_threads: List[LeadLinkedThread] = Field(default_factory=list)
    linked_proposals: List[LeadLinkedProposal] = Field(default_factory=list)
    last_activity_at: Optional[datetime] = None


class LeadClassifyRequest(BaseModel):
    lead_ids: List[UUID] = Field(default_factory=list)
    client_id: Optional[UUID] = None


class LeadClassifyResponse(BaseModel):
    items: List[LeadClassificationDetail]
    classified: int = 0


class LeadRecalculateRequest(BaseModel):
    client_id: Optional[UUID] = None
    limit: int = Field(200, ge=1, le=500)


class LeadRecalculateResponse(BaseModel):
    classified: int = 0
    overview: LeadClassificationOverview
    message: str = "Classification recalculated — no CRM changes were made."
