from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.communication import (
    CommCrmTaskType,
    CommunicationContactResponse,
    CommunicationMessageResponse,
    CommunicationThreadResponse,
)
from app.schemas.sales_assistant import SalesAssistantRecommendationResponse

UnifiedInboxChannel = Literal["wechat", "wecom", "whatsapp", "email", "manual", "outreach"]
UnifiedInboxPriority = Literal["high", "medium", "low"]
UnifiedInboxSource = Literal["thread", "outreach", "whatsapp"]

UNIFIED_INBOX_CHANNELS = ("wechat", "wecom", "whatsapp", "email", "manual", "outreach")
THREAD_INBOX_CHANNELS = ("wechat", "wecom", "email", "manual")


class UnifiedConversationResponse(BaseModel):
    id: str
    source: UnifiedInboxSource
    source_id: UUID
    channel: UnifiedInboxChannel
    contact_name: str
    company: Optional[str] = None
    country: Optional[str] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    last_message: Optional[str] = None
    last_message_at: Optional[datetime] = None
    unread_count: int = 0
    priority: UnifiedInboxPriority = "medium"
    status: str = "open"
    lead_name: Optional[str] = None
    deal_title: Optional[str] = None
    thread_id: Optional[UUID] = None
    outreach_id: Optional[UUID] = None
    whatsapp_thread_id: Optional[UUID] = None
    whatsapp_contact_id: Optional[UUID] = None
    communication_health_score: Optional[int] = None
    communication_classification: Optional[str] = None


class UnifiedConversationListResponse(BaseModel):
    items: list[UnifiedConversationResponse]
    total: int


class UnifiedInboxAiPanel(BaseModel):
    summary: str
    lead_status: Optional[str] = None
    proposal_status: Optional[str] = None
    recommended_action: str
    has_linked_lead: bool = False
    has_linked_deal: bool = False
    proposal_count: int = 0
    can_create_lead: bool = True
    can_create_proposal: bool = True
    can_create_task: bool = True


class UnifiedConversationDetailResponse(BaseModel):
    conversation: UnifiedConversationResponse
    thread: Optional[CommunicationThreadResponse] = None
    messages: list[CommunicationMessageResponse] = Field(default_factory=list)
    contact: Optional[CommunicationContactResponse] = None
    ai_panel: UnifiedInboxAiPanel
    linked_outreach: list[dict] = Field(default_factory=list)
    sales_assistant_recommendations: list[SalesAssistantRecommendationResponse] = Field(default_factory=list)
    communication_intelligence: Optional[dict] = None


class UnifiedInboxLinkLeadRequest(BaseModel):
    lead_id: UUID


class UnifiedInboxLinkDealRequest(BaseModel):
    deal_id: UUID


class UnifiedInboxCreateTaskRequest(BaseModel):
    task_type: CommCrmTaskType = "follow_up"
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    priority: Optional[Literal["high", "medium", "low"]] = None
    due_at: Optional[datetime] = None


class UnifiedInboxLinkResponse(BaseModel):
    id: str
    lead_id: Optional[UUID] = None
    lead_name: Optional[str] = None
    deal_id: Optional[UUID] = None
    deal_title: Optional[str] = None
    message: str


class UnifiedInboxCreateTaskResponse(BaseModel):
    id: str
    task_id: UUID
    title: str
    task_type: str
    message: str
