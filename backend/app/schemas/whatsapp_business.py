"""WhatsApp Business Integration — dashboard, accounts, CRM links (maps to communication hub)."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

WhatsAppAccountType = Literal["whatsapp_business_api", "whatsapp_cloud_api", "third_party_connector", "manual_import"]
WhatsAppAccountStatus = Literal["not_connected", "connected", "sync_error", "disabled"]


class WhatsAppAccountResponse(BaseModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    account_name: str
    phone_number: Optional[str] = None
    business_display_name: Optional[str] = None
    account_type: WhatsAppAccountType
    status: WhatsAppAccountStatus
    provider: Optional[str] = None
    external_account_id: Optional[str] = None
    connected_at: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WhatsAppAccountCreate(BaseModel):
    account_name: str = Field(..., min_length=1, max_length=255)
    account_type: WhatsAppAccountType = "whatsapp_cloud_api"
    phone_number: Optional[str] = Field(None, max_length=50)
    business_display_name: Optional[str] = Field(None, max_length=255)
    provider: Optional[str] = Field(None, max_length=50)


class WhatsAppAccountUpdate(BaseModel):
    account_name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone_number: Optional[str] = Field(None, max_length=50)
    business_display_name: Optional[str] = Field(None, max_length=255)
    status: Optional[WhatsAppAccountStatus] = None
    provider: Optional[str] = Field(None, max_length=50)


class WhatsAppAccountListResponse(BaseModel):
    items: list[WhatsAppAccountResponse]
    total: int


class WhatsAppContactExtended(BaseModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    phone_number: Optional[str] = None
    display_name: str
    company: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    industry: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    linked_lead_id: Optional[UUID] = None
    linked_sales_lead_id: Optional[UUID] = None
    linked_buyer_id: Optional[UUID] = None
    linked_customer_id: Optional[UUID] = None
    linked_lead_name: Optional[str] = None
    linked_buyer_name: Optional[str] = None
    linked_customer_name: Optional[str] = None
    last_interaction_at: Optional[datetime] = None
    thread_count: int = 0
    created_at: datetime
    updated_at: datetime


class WhatsAppContactListExtendedResponse(BaseModel):
    items: list[WhatsAppContactExtended]
    total: int


class WhatsAppLinkBuyerRequest(BaseModel):
    buyer_id: UUID


class WhatsAppLinkCustomerRequest(BaseModel):
    customer_id: UUID


class WhatsAppLinkLeadRequest(BaseModel):
    lead_id: UUID


class WhatsAppLinkProposalRequest(BaseModel):
    proposal_id: UUID


class WhatsAppLinkDealRequest(BaseModel):
    deal_id: UUID


class WhatsAppCrmLinkResponse(BaseModel):
    contact_id: Optional[UUID] = None
    thread_id: Optional[UUID] = None
    buyer_id: Optional[UUID] = None
    buyer_name: Optional[str] = None
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    lead_id: Optional[UUID] = None
    lead_name: Optional[str] = None
    proposal_id: Optional[UUID] = None
    proposal_title: Optional[str] = None
    deal_id: Optional[UUID] = None
    deal_title: Optional[str] = None


class WhatsAppDashboardKpis(BaseModel):
    total_contacts: int = 0
    active_conversations: int = 0
    new_conversations_this_week: int = 0
    opportunities_discovered: int = 0
    follow_ups_required: int = 0
    messages_total: int = 0
    accounts_connected: int = 0


class WhatsAppActivityItem(BaseModel):
    id: UUID
    activity_type: str
    title: str
    subtitle: Optional[str] = None
    channel: str = "whatsapp"
    occurred_at: datetime
    thread_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None


class WhatsAppConnectionStatus(BaseModel):
    overall_status: WhatsAppAccountStatus
    accounts_total: int = 0
    accounts_connected: int = 0
    demo_mode: bool = False
    provider_ready: bool = False
    webhook_configured: bool = False
    last_sync_at: Optional[datetime] = None


class WhatsAppDashboardResponse(BaseModel):
    connection: WhatsAppConnectionStatus
    kpis: WhatsAppDashboardKpis
    linked_accounts: list[WhatsAppAccountResponse] = Field(default_factory=list)
    recent_activity: list[WhatsAppActivityItem] = Field(default_factory=list)
    communication_hub_channel: str = "whatsapp"


class WhatsAppDemoSeedResponse(BaseModel):
    seeded: bool
    accounts_created: int = 0
    contacts_created: int = 0
    conversations_created: int = 0
    message: str


class WhatsAppAiCapability(BaseModel):
    id: str
    label: str
    description: str
    status: Literal["ready", "planned"] = "planned"


class WhatsAppAiCapabilitiesResponse(BaseModel):
    capabilities: list[WhatsAppAiCapability]
    uses_communication_ai_hub: bool = True
    demo_mode: bool = False
