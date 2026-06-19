"""Communication Hub MVP — dashboard, records, follow-ups, templates."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.communication import FOLLOW_UP_STATUSES, MESSAGE_STATUSES, TEMPLATE_CATEGORIES

CommunicationRecordStatus = Literal["sent", "delivered", "read", "unanswered", "draft"]
FollowUpStatus = Literal["pending", "completed", "cancelled"]
TemplateCategory = Literal[
    "first_contact",
    "follow_up",
    "proposal_follow_up",
    "negotiation",
    "re_engagement",
    "customer_support",
]


class CommunicationRecordResponse(BaseModel):
    """Unified communication record (message + thread context)."""

    id: UUID
    tenant_id: Optional[UUID] = None
    channel: str
    customer_id: Optional[UUID] = None
    buyer_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    thread_id: UUID
    subject: str
    content: str
    direction: str
    status: str
    contact_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommunicationRecordListResponse(BaseModel):
    items: list[CommunicationRecordResponse]
    total: int


class CommunicationRecordCreate(BaseModel):
    channel: str = Field(..., max_length=20)
    subject: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    direction: str = Field(default="outbound", max_length=20)
    status: CommunicationRecordStatus = "sent"
    customer_id: Optional[UUID] = None
    buyer_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    contact_name: Optional[str] = Field(None, max_length=255)


class CommunicationDashboardKpis(BaseModel):
    total_communications: int = 0
    communications_this_week: int = 0
    unanswered_conversations: int = 0
    follow_ups_due_today: int = 0
    active_buyers: int = 0
    active_negotiations: int = 0


class CommunicationActivityItem(BaseModel):
    id: str
    type: str
    title: str
    subtitle: Optional[str] = None
    channel: Optional[str] = None
    occurred_at: datetime
    href: Optional[str] = None


class CommunicationConversationPreview(BaseModel):
    id: str
    thread_id: UUID
    title: str
    contact_name: Optional[str] = None
    channel: str
    last_message_preview: Optional[str] = None
    last_message_at: Optional[datetime] = None
    status: str
    unread_count: int = 0


class CommunicationDashboardResponse(BaseModel):
    kpis: CommunicationDashboardKpis
    recent_conversations: list[CommunicationConversationPreview]
    recent_activity: list[CommunicationActivityItem]
    follow_ups_due: list["FollowUpResponse"]
    unanswered: list[CommunicationConversationPreview]
    statistics: dict[str, int] = Field(default_factory=dict)


class FollowUpCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    due_date: datetime
    communication_id: Optional[UUID] = None
    thread_id: Optional[UUID] = None
    assigned_user: Optional[str] = Field(None, max_length=255)


class FollowUpUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    status: Optional[FollowUpStatus] = None
    assigned_user: Optional[str] = Field(None, max_length=255)


class FollowUpResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    communication_id: Optional[UUID] = None
    thread_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    due_date: datetime
    status: str
    assigned_user: Optional[str] = None
    is_overdue: bool = False
    thread_title: Optional[str] = None
    channel: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FollowUpListResponse(BaseModel):
    items: list[FollowUpResponse]
    total: int
    overdue_count: int = 0
    today_count: int = 0
    upcoming_count: int = 0


class MessageTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category: TemplateCategory
    content: str = Field(..., min_length=1)
    language: str = Field(default="en", max_length=10)


class MessageTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[TemplateCategory] = None
    content: Optional[str] = Field(None, min_length=1)
    language: Optional[str] = Field(None, max_length=10)


class MessageTemplateResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    category: str
    content: str
    language: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageTemplateListResponse(BaseModel):
    items: list[MessageTemplateResponse]
    total: int


class CommunicationAiCapabilitiesResponse(BaseModel):
    """Extensible AI integration surface — stubs for future assistant hooks."""

    analyze_conversations: bool = True
    recommend_responses: bool = True
    detect_inactive_leads: bool = True
    detect_high_potential_buyers: bool = True
    suggest_follow_up_actions: bool = True
    implementation_status: str = "architecture_ready"
    notes: list[str] = Field(default_factory=list)


# Re-export constants for API validation
MESSAGE_STATUSES_SET = MESSAGE_STATUSES
FOLLOW_UP_STATUSES_SET = FOLLOW_UP_STATUSES
TEMPLATE_CATEGORIES_SET = TEMPLATE_CATEGORIES
