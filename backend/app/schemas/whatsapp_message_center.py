from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.communication import (
    CommunicationContactResponse,
    CommunicationMessageResponse,
    CommunicationThreadResponse,
)

WhatsAppChannel = Literal["whatsapp"]


class WhatsAppContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=3, max_length=50)
    client_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    company: Optional[str] = Field(None, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    industry: Optional[str] = Field(None, max_length=100)
    preferred_language: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class WhatsAppContactListResponse(BaseModel):
    items: list[CommunicationContactResponse]
    total: int


class WhatsAppThreadCreate(BaseModel):
    contact_id: UUID
    title: Optional[str] = Field(None, max_length=255)
    client_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    external_contact_id: Optional[str] = Field(None, max_length=100)


class WhatsAppThreadListResponse(BaseModel):
    items: list[CommunicationThreadResponse]
    total: int


class WhatsAppThreadDetailResponse(CommunicationThreadResponse):
    messages: list[CommunicationMessageResponse] = Field(default_factory=list)
    contact: Optional[CommunicationContactResponse] = None
    ai_panel: Optional["WhatsAppAiPanelState"] = None


class WhatsAppPasteInboundRequest(BaseModel):
    message_text: str = Field(..., min_length=1)
    sender_name: Optional[str] = Field(None, max_length=255)
    original_language: Optional[str] = Field(None, max_length=20)
    translated_text: Optional[str] = None


class WhatsAppGenerateReplyRequest(BaseModel):
    operator_notes: Optional[str] = Field(None, max_length=2000)


class WhatsAppGenerateReplyResponse(BaseModel):
    message_id: UUID
    language: str
    reply_text: str
    tone: str
    recommended_next_action: str
    risk_flags: list[str] = Field(default_factory=list)
    demo_mode: bool = False


class WhatsAppMarkCopiedResponse(BaseModel):
    message_id: UUID
    copied_at: datetime


class WhatsAppMarkManuallySentResponse(BaseModel):
    message_id: UUID
    manual_sent_at: datetime
    direction: str


class WhatsAppCreateLeadRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    company: Optional[str] = Field(None, max_length=255)
    interest: Optional[str] = None
    notes: Optional[str] = None


class WhatsAppCreateLeadResponse(BaseModel):
    lead_id: UUID
    lead_name: str
    thread_id: UUID
    created: bool
    updated: bool


class WhatsAppLinkResponse(BaseModel):
    thread_id: UUID
    lead_id: Optional[UUID] = None
    lead_name: Optional[str] = None
    deal_id: Optional[UUID] = None
    deal_title: Optional[str] = None


class WhatsAppAiPanelState(BaseModel):
    summary: str
    recommended_next_action: str
    sentiment: str = "neutral"
    has_linked_lead: bool = False
    has_linked_deal: bool = False
    proposal_count: int = 0
    playbook_name: Optional[str] = None
