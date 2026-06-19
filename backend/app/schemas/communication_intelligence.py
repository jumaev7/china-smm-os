"""Communication Intelligence v1 — read-only conversation analysis schemas."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

ConversationClassification = Literal[
    "inquiry", "qualification", "negotiation", "proposal", "closing", "inactive",
]
UrgencyLevel = Literal["urgent", "high", "medium", "low"]
ConversationSource = Literal["thread", "whatsapp"]


class CommunicationIntelligenceResult(BaseModel):
    health_score: int = Field(ge=0, le=100)
    classification: ConversationClassification
    urgency: UrgencyLevel = "medium"
    insights: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)


class CommunicationIntelligenceOverview(BaseModel):
    active_buyers: int = 0
    hot_buyers: int = 0
    negotiations: int = 0
    follow_ups_required: int = 0
    inactive_conversations: int = 0
    total_analyzed: int = 0
    errors: List[str] = Field(default_factory=list)


class CommunicationIntelligenceListItem(BaseModel):
    conversation_id: str
    source: ConversationSource
    source_id: UUID
    contact_name: str
    channel: str
    health_score: int
    classification: ConversationClassification
    urgency: UrgencyLevel
    recommended_action: str = ""
    last_message_at: Optional[datetime] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    status: str = "open"


class CommunicationIntelligenceListResponse(BaseModel):
    items: List[CommunicationIntelligenceListItem]
    total: int


class CommunicationLinkedCrm(BaseModel):
    lead_id: Optional[UUID] = None
    lead_name: Optional[str] = None
    lead_status: Optional[str] = None
    deal_id: Optional[UUID] = None
    deal_title: Optional[str] = None
    client_id: Optional[UUID] = None


class CommunicationLinkedProposal(BaseModel):
    proposal_id: UUID
    title: str
    status: str
    updated_at: Optional[datetime] = None


class CommunicationIntelligenceDetail(BaseModel):
    conversation_id: str
    source: ConversationSource
    source_id: UUID
    contact_name: str
    channel: str
    status: str = "open"
    intelligence: CommunicationIntelligenceResult
    linked_crm: CommunicationLinkedCrm = Field(default_factory=CommunicationLinkedCrm)
    linked_deal_room: Optional[dict] = None
    linked_proposals: List[CommunicationLinkedProposal] = Field(default_factory=list)
    last_message_at: Optional[datetime] = None
    message_count: int = 0


class CommunicationAnalyzeRequest(BaseModel):
    conversation_ids: List[str] = Field(default_factory=list)
    client_id: Optional[UUID] = None


class CommunicationAnalyzeResponse(BaseModel):
    items: List[CommunicationIntelligenceDetail]
    analyzed: int = 0


class CommunicationRecalculateRequest(BaseModel):
    client_id: Optional[UUID] = None
    limit: int = Field(200, ge=1, le=500)


class CommunicationRecalculateResponse(BaseModel):
    analyzed: int = 0
    overview: CommunicationIntelligenceOverview
    message: str = "Communication intelligence recalculated — no messages sent or CRM changes made."
