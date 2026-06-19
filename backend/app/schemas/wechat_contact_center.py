from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.communication import (
    CommunicationContactResponse,
    CommunicationMessageResponse,
    CommunicationThreadResponse,
    WECHAT_CHANNELS,
)

WeChatChannel = Literal["wechat", "wecom"]


class WeChatContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    channel: WeChatChannel = "wechat"
    client_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    company: Optional[str] = Field(None, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    wechat_id: Optional[str] = Field(None, max_length=100)
    wecom_id: Optional[str] = Field(None, max_length=100)
    qr_code_url: Optional[str] = Field(None, max_length=500)
    preferred_language: Optional[str] = Field(None, max_length=20)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class WeChatContactListResponse(BaseModel):
    items: list[CommunicationContactResponse]
    total: int


class WeChatThreadCreate(BaseModel):
    contact_id: UUID
    channel: WeChatChannel = "wechat"
    title: Optional[str] = Field(None, max_length=255)
    client_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    external_contact_id: Optional[str] = Field(None, max_length=100)


class WeChatThreadListResponse(BaseModel):
    items: list[CommunicationThreadResponse]
    total: int


class WeChatThreadDetailResponse(CommunicationThreadResponse):
    messages: list[CommunicationMessageResponse] = Field(default_factory=list)
    contact: Optional[CommunicationContactResponse] = None
    ai_panel: Optional["WeChatAiPanelState"] = None


class WeChatPasteInboundRequest(BaseModel):
    message_text: str = Field(..., min_length=1)
    sender_name: Optional[str] = Field(None, max_length=255)
    original_language: Optional[str] = Field(None, max_length=20)
    translated_text: Optional[str] = None


class WeChatGenerateReplyRequest(BaseModel):
    operator_notes: Optional[str] = Field(None, max_length=2000)


class WeChatGenerateReplyResponse(BaseModel):
    message_id: UUID
    language: str
    reply_text: str
    tone: str
    recommended_next_action: str
    risk_flags: list[str] = Field(default_factory=list)
    demo_mode: bool = False


class WeChatMarkCopiedResponse(BaseModel):
    message_id: UUID
    copied_at: datetime


class WeChatMarkManuallySentResponse(BaseModel):
    message_id: UUID
    manual_sent_at: datetime
    direction: str


class WeChatLinkLeadRequest(BaseModel):
    lead_id: UUID


class WeChatLinkDealRequest(BaseModel):
    deal_id: UUID


class WeChatCreateLeadRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    company: Optional[str] = Field(None, max_length=255)
    interest: Optional[str] = None
    notes: Optional[str] = None


class WeChatCreateLeadResponse(BaseModel):
    lead_id: UUID
    lead_name: str
    thread_id: UUID
    created: bool = True
    updated: bool = False


class WeChatAiPanelState(BaseModel):
    summary: str
    recommended_next_action: str
    sentiment: str = "neutral"
    has_linked_lead: bool = False
    has_linked_deal: bool = False
    proposal_count: int = 0
    playbook_name: Optional[str] = None


class WeChatLinkResponse(BaseModel):
    thread_id: UUID
    lead_id: Optional[UUID] = None
    lead_name: Optional[str] = None
    deal_id: Optional[UUID] = None
    deal_title: Optional[str] = None
