from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

CommunicationChannel = Literal["telegram", "whatsapp", "wechat", "wecom", "email", "manual"]
ThreadStatus = Literal["open", "waiting", "closed"]
MessageDirection = Literal["inbound", "outbound", "draft", "internal_note"]

COMMUNICATION_CHANNELS = ("telegram", "whatsapp", "wechat", "wecom", "email", "manual")
THREAD_STATUSES = ("open", "waiting", "closed")
MESSAGE_DIRECTIONS = ("inbound", "outbound", "draft", "internal_note")
WECHAT_CHANNELS = ("wechat", "wecom")


class CommunicationContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    client_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    partner_id: Optional[UUID] = None
    company: Optional[str] = Field(None, max_length=255)
    role: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)
    telegram: Optional[str] = Field(None, max_length=100)
    whatsapp: Optional[str] = Field(None, max_length=100)
    wechat: Optional[str] = Field(None, max_length=100)
    wechat_id: Optional[str] = Field(None, max_length=100)
    wecom_id: Optional[str] = Field(None, max_length=100)
    qr_code_url: Optional[str] = Field(None, max_length=500)
    email: Optional[str] = Field(None, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, max_length=20)
    preferred_language: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None


class CommunicationContactResponse(BaseModel):
    id: UUID
    client_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    partner_id: Optional[UUID] = None
    name: str
    company: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    telegram: Optional[str] = None
    whatsapp: Optional[str] = None
    wechat: Optional[str] = None
    wechat_id: Optional[str] = None
    wecom_id: Optional[str] = None
    qr_code_url: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    preferred_language: Optional[str] = None
    notes: Optional[str] = None
    client_name: Optional[str] = None
    lead_name: Optional[str] = None
    partner_name: Optional[str] = None
    thread_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommunicationContactListResponse(BaseModel):
    items: list[CommunicationContactResponse]
    total: int


class CommunicationThreadCreate(BaseModel):
    contact_id: UUID
    channel: CommunicationChannel
    title: str = Field(..., min_length=1, max_length=255)
    client_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    partner_id: Optional[UUID] = None
    external_thread_id: Optional[str] = Field(None, max_length=100)
    status: ThreadStatus = "open"


class CommunicationThreadResponse(BaseModel):
    id: UUID
    contact_id: UUID
    client_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    partner_id: Optional[UUID] = None
    channel: str
    external_thread_id: Optional[str] = None
    external_contact_id: Optional[str] = None
    last_manual_sync_at: Optional[datetime] = None
    title: str
    status: str
    last_message_at: Optional[datetime] = None
    contact_name: Optional[str] = None
    client_name: Optional[str] = None
    lead_name: Optional[str] = None
    deal_title: Optional[str] = None
    message_count: int = 0
    last_message_preview: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommunicationThreadDetailResponse(CommunicationThreadResponse):
    messages: list["CommunicationMessageResponse"] = Field(default_factory=list)
    contact: Optional[CommunicationContactResponse] = None
    linked_outreach: list[dict] = Field(default_factory=list)


class CommunicationThreadListResponse(BaseModel):
    items: list[CommunicationThreadResponse]
    total: int


class CommunicationMessageCreate(BaseModel):
    direction: MessageDirection
    sender_name: str = Field(..., min_length=1, max_length=255)
    message_text: str = Field(..., min_length=1)
    attachments_json: Optional[list] = None


class CommunicationMessageResponse(BaseModel):
    id: UUID
    thread_id: UUID
    direction: str
    sender_name: str
    message_text: str
    attachments_json: Optional[list] = None
    original_language: Optional[str] = None
    translated_text: Optional[str] = None
    ai_summary: Optional[str] = None
    copied_at: Optional[datetime] = None
    manual_sent_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CommunicationAiSummaryResponse(BaseModel):
    summary: str
    next_action: str
    sentiment: str
    possible_lead_interest: str
    demo_mode: bool = False


class CommunicationLinkLeadRequest(BaseModel):
    lead_id: UUID


class CommunicationCreateLeadResponse(BaseModel):
    lead_id: UUID
    lead_name: str
    thread_id: UUID
    created: bool = True
    updated: bool = False


class CommunicationCrmExtractResponse(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    telegram: Optional[str] = None
    whatsapp: Optional[str] = None
    wechat: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    interest: Optional[str] = None
    urgency: Optional[str] = None
    budget: Optional[str] = None
    next_follow_up_at: Optional[str] = None
    suggested_status: str = "new"
    suggested_priority: str = "medium"
    demo_mode: bool = False


class CommunicationCrmCreateLeadRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    company: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    telegram: Optional[str] = Field(None, max_length=100)
    whatsapp: Optional[str] = Field(None, max_length=100)
    wechat: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, max_length=20)
    interest: Optional[str] = None
    urgency: Optional[str] = None
    budget: Optional[str] = None
    next_follow_up_at: Optional[str] = None
    suggested_status: Optional[str] = None
    suggested_priority: Optional[str] = None
    notes: Optional[str] = None
    attribution_link_id: Optional[UUID] = None


CommCrmTaskType = Literal[
    "follow_up",
    "send_catalog",
    "send_proposal",
    "request_details",
    "schedule_call",
]


class CommunicationCrmCreateTaskRequest(BaseModel):
    task_type: CommCrmTaskType
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    priority: Optional[Literal["high", "medium", "low"]] = None
    due_at: Optional[datetime] = None


class CommunicationCrmCreateTaskResponse(BaseModel):
    task_id: UUID
    title: str
    thread_id: UUID
    task_type: str


class CommunicationCrmSuggestReplyResponse(BaseModel):
    reply_text: str
    demo_mode: bool = False


class CommunicationMessageStoredResponse(CommunicationMessageResponse):
    activity_synced: bool = False
