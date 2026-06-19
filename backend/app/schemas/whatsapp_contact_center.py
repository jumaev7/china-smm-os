from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

WhatsAppDirection = Literal["incoming", "outgoing"]
WhatsAppMessageStatus = Literal["sent", "delivered", "read", "draft", "failed"]


class WhatsAppContactResponse(BaseModel):
    id: UUID
    phone: str
    display_name: str
    company: Optional[str] = None
    country: Optional[str] = None
    crm_client_id: Optional[UUID] = None
    crm_client_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WhatsAppContactListResponse(BaseModel):
    items: list[WhatsAppContactResponse]
    total: int


class WhatsAppThreadResponse(BaseModel):
    id: UUID
    contact_id: UUID
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    company: Optional[str] = None
    country: Optional[str] = None
    crm_client_id: Optional[UUID] = None
    last_message_at: Optional[datetime] = None
    unread_count: int = 0
    last_message_preview: Optional[str] = None
    created_at: datetime


class WhatsAppThreadListResponse(BaseModel):
    items: list[WhatsAppThreadResponse]
    total: int


class WhatsAppMessageResponse(BaseModel):
    id: UUID
    thread_id: UUID
    direction: WhatsAppDirection
    content: str
    status: WhatsAppMessageStatus
    created_at: datetime


class WhatsAppMessageListResponse(BaseModel):
    items: list[WhatsAppMessageResponse]
    total: int


class WhatsAppDraftRequest(BaseModel):
    thread_id: UUID
    operator_notes: Optional[str] = Field(None, max_length=2000)


class WhatsAppDraftResponse(BaseModel):
    message_id: UUID
    thread_id: UUID
    content: str
    language: str = "en"
    tone: str = "professional"
    recommended_next_action: str
    demo_mode: bool = True


class WhatsAppLinkCrmRequest(BaseModel):
    contact_id: UUID
    crm_client_id: UUID


class WhatsAppLinkCrmResponse(BaseModel):
    contact_id: UUID
    crm_client_id: UUID
    crm_client_name: str
    message: str
