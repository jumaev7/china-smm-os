"""WeChat Business Integration — dashboard, accounts, CRM links (maps to communication hub)."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

WeChatAccountType = Literal["personal_wechat", "wecom", "official_account"]
WeChatAccountStatus = Literal["not_connected", "connected", "sync_error", "disabled"]


class WeChatAccountResponse(BaseModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    account_name: str
    account_type: WeChatAccountType
    status: WeChatAccountStatus
    provider: Optional[str] = None
    external_account_id: Optional[str] = None
    connected_at: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WeChatAccountCreate(BaseModel):
    account_name: str = Field(..., min_length=1, max_length=255)
    account_type: WeChatAccountType = "personal_wechat"
    provider: Optional[str] = Field(None, max_length=50)


class WeChatAccountUpdate(BaseModel):
    account_name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[WeChatAccountStatus] = None
    provider: Optional[str] = Field(None, max_length=50)


class WeChatAccountListResponse(BaseModel):
    items: list[WeChatAccountResponse]
    total: int


class WeChatContactExtended(BaseModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    wechat_id: Optional[str] = None
    wecom_id: Optional[str] = None
    display_name: str
    company: Optional[str] = None
    country: Optional[str] = None
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


class WeChatContactListExtendedResponse(BaseModel):
    items: list[WeChatContactExtended]
    total: int


class WeChatLinkBuyerRequest(BaseModel):
    buyer_id: UUID


class WeChatLinkCustomerRequest(BaseModel):
    customer_id: UUID


class WeChatLinkProposalRequest(BaseModel):
    proposal_id: UUID


class WeChatCrmLinkResponse(BaseModel):
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


class WeChatDashboardKpis(BaseModel):
    total_contacts: int = 0
    active_conversations: int = 0
    new_conversations_this_week: int = 0
    opportunities_discovered: int = 0
    follow_ups_required: int = 0
    messages_total: int = 0
    accounts_connected: int = 0


class WeChatActivityItem(BaseModel):
    id: UUID
    activity_type: str
    title: str
    subtitle: Optional[str] = None
    channel: str = "wechat"
    occurred_at: datetime
    thread_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None


class WeChatConnectionStatus(BaseModel):
    overall_status: WeChatAccountStatus
    accounts_total: int = 0
    accounts_connected: int = 0
    demo_mode: bool = False
    provider_ready: bool = False
    last_sync_at: Optional[datetime] = None


class WeChatDashboardResponse(BaseModel):
    connection: WeChatConnectionStatus
    kpis: WeChatDashboardKpis
    linked_accounts: list[WeChatAccountResponse] = Field(default_factory=list)
    recent_activity: list[WeChatActivityItem] = Field(default_factory=list)
    communication_hub_channel: str = "wechat"


class WeChatDemoSeedResponse(BaseModel):
    seeded: bool
    accounts_created: int = 0
    contacts_created: int = 0
    conversations_created: int = 0
    message: str


class WeChatAiCapability(BaseModel):
    id: str
    label: str
    description: str
    status: Literal["ready", "planned"] = "planned"


class WeChatAiCapabilitiesResponse(BaseModel):
    capabilities: list[WeChatAiCapability]
    uses_communication_ai_hub: bool = True
    demo_mode: bool = False
