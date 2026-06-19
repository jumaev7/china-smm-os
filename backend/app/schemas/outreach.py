from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

OutreachChannel = Literal["email", "whatsapp", "wechat", "linkedin"]
OutreachType = Literal["first_contact", "follow_up", "proposal_follow_up", "re_engagement"]
OutreachStatus = Literal["draft", "approved", "sent", "archived"]
OutreachStyle = Literal["formal", "friendly", "executive", "distributor"]


class OutreachGenerateRequest(BaseModel):
    product_id: UUID
    proposal_id: UUID | None = None
    lead_id: UUID | None = None
    buyer_name: str | None = Field(None, max_length=255)
    buyer_company: str | None = Field(None, max_length=255)
    country: str = Field(..., min_length=1, max_length=100)
    language: str = "en"
    channel: OutreachChannel
    outreach_type: OutreachType
    style: OutreachStyle = "formal"


class OutreachUpdate(BaseModel):
    subject: str | None = Field(None, max_length=500)
    message_text: str | None = Field(None, min_length=1)
    status: OutreachStatus | None = None
    buyer_name: str | None = Field(None, max_length=255)
    buyer_company: str | None = Field(None, max_length=255)


class OutreachRegenerateRequest(BaseModel):
    style: OutreachStyle | None = None


OutreachEventType = Literal[
    "generated", "approved", "copied", "sent", "follow_up_created", "thread_linked",
]


class OutreachEventResponse(BaseModel):
    id: UUID
    event_type: OutreachEventType
    payload_json: dict | None = None
    created_at: datetime


class OutreachMarkSentRequest(BaseModel):
    create_follow_up_task: bool = True


class OutreachCreateFollowUpRequest(BaseModel):
    due_at: datetime | None = None


class OutreachLinkThreadRequest(BaseModel):
    communication_thread_id: UUID


class OutreachWorkflowResponse(BaseModel):
    outreach: "OutreachMessageResponse"
    follow_up_task_id: UUID | None = None
    communication_thread_id: UUID | None = None
    message: str | None = None


class OutreachMessageResponse(BaseModel):
    id: UUID
    client_id: UUID
    client_name: str | None = None
    lead_id: UUID | None = None
    lead_name: str | None = None
    product_id: UUID | None = None
    product_name: str | None = None
    proposal_id: UUID | None = None
    proposal_title: str | None = None
    buyer_name: str | None = None
    buyer_company: str | None = None
    country: str | None = None
    channel: OutreachChannel
    language: str
    outreach_type: OutreachType
    subject: str | None = None
    message_text: str
    status: OutreachStatus
    demo_mode: bool = False
    style: OutreachStyle | None = None
    sent_at: datetime | None = None
    approved_at: datetime | None = None
    copied_at: datetime | None = None
    last_action_at: datetime | None = None
    communication_thread_id: UUID | None = None
    communication_thread_title: str | None = None
    follow_up_task_id: UUID | None = None
    follow_up_task_title: str | None = None
    sales_playbook_id: UUID | None = None
    sales_playbook_name: str | None = None
    sales_playbook_step_id: UUID | None = None
    events: list[OutreachEventResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class OutreachListResponse(BaseModel):
    items: list[OutreachMessageResponse]
    total: int
