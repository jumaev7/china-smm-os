"""Pydantic schemas for tenant Sales CRM."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

LeadStatus = Literal["new", "contacted", "qualified", "converted", "lost"]
LeadPriority = Literal["high", "medium", "low"]
LeadSource = Literal["manual", "website", "referral", "exhibition", "social", "other"]
DealStage = Literal[
    "lead",
    "qualified",
    "contacted",
    "meeting_scheduled",
    "proposal_sent",
    "negotiation",
    "contract_pending",
    "client_active",
    "publishing_active",
    "expansion_upsell",
    "closed_won",
    "closed_lost",
]
StageSource = Literal["manual", "auto", "proposal"]
ActivityType = Literal["call", "email", "meeting", "note", "task", "other"]

DEAL_STAGES: list[DealStage] = [
    "lead",
    "qualified",
    "contacted",
    "meeting_scheduled",
    "proposal_sent",
    "negotiation",
    "contract_pending",
    "client_active",
    "publishing_active",
    "expansion_upsell",
    "closed_won",
    "closed_lost",
]


class SalesCustomerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=255)
    telegram: str | None = Field(None, max_length=100)
    whatsapp: str | None = Field(None, max_length=100)
    wechat: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    notes: str | None = None
    client_id: UUID | None = None
    owner_id: UUID | None = None
    primary_publishing_account_id: UUID | None = None


class SalesCustomerCreate(SalesCustomerBase):
    pass


class SalesCustomerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    company: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=255)
    telegram: str | None = Field(None, max_length=100)
    whatsapp: str | None = Field(None, max_length=100)
    wechat: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    notes: str | None = None
    client_id: UUID | None = None
    owner_id: UUID | None = None
    primary_publishing_account_id: UUID | None = None


class SalesCustomerResponse(SalesCustomerBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime
    deal_count: int = 0
    lead_count: int = 0
    owner_email: str | None = None
    client_name: str | None = None


class SalesCustomerListResponse(BaseModel):
    items: list[SalesCustomerResponse]
    total: int


class SalesLeadBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=255)
    telegram: str | None = Field(None, max_length=100)
    whatsapp: str | None = Field(None, max_length=100)
    wechat: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    source: LeadSource = "manual"
    status: LeadStatus = "new"
    priority: LeadPriority = "medium"
    notes: str | None = None
    assigned_to: str | None = Field(None, max_length=255)
    customer_id: UUID | None = None


class SalesLeadCreate(SalesLeadBase):
    pass


class SalesLeadUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    company: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=255)
    telegram: str | None = Field(None, max_length=100)
    whatsapp: str | None = Field(None, max_length=100)
    wechat: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    source: LeadSource | None = None
    status: LeadStatus | None = None
    priority: LeadPriority | None = None
    notes: str | None = None
    assigned_to: str | None = Field(None, max_length=255)
    customer_id: UUID | None = None


class SalesLeadResponse(SalesLeadBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime


class SalesLeadListResponse(BaseModel):
    items: list[SalesLeadResponse]
    total: int


class SalesDealBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    customer_id: UUID | None = None
    lead_id: UUID | None = None
    value: Decimal | None = Field(None, ge=0)
    currency: str = Field("USD", max_length=10)
    stage: DealStage = "lead"
    probability: int = Field(5, ge=0, le=100)
    expected_close_date: datetime | None = None
    closed_at: datetime | None = None
    owner_id: UUID | None = None
    stage_source: StageSource = "manual"
    stage_override: bool = False
    notes: str | None = None


class SalesDealCreate(SalesDealBase):
    pass


class SalesDealUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    customer_id: UUID | None = None
    lead_id: UUID | None = None
    value: Decimal | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=10)
    stage: DealStage | None = None
    probability: int | None = Field(None, ge=0, le=100)
    expected_close_date: datetime | None = None
    closed_at: datetime | None = None
    owner_id: UUID | None = None
    stage_source: StageSource | None = None
    stage_override: bool | None = None
    notes: str | None = None


class SalesDealStageUpdate(BaseModel):
    stage: DealStage
    stage_override: bool = True
    probability: int | None = Field(None, ge=0, le=100)


class SalesDealResponse(SalesDealBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime
    customer_name: str | None = None
    lead_name: str | None = None
    owner_email: str | None = None


class SalesDealListResponse(BaseModel):
    items: list[SalesDealResponse]
    total: int


class SalesPipelineStageSummary(BaseModel):
    stage: DealStage
    count: int
    total_value: Decimal


class SalesActivityBase(BaseModel):
    type: ActivityType
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    lead_id: UUID | None = None
    customer_id: UUID | None = None
    deal_id: UUID | None = None
    activity_date: datetime | None = None


class SalesActivityCreate(SalesActivityBase):
    pass


class SalesActivityResponse(SalesActivityBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    created_by: str | None
    created_at: datetime


class SalesActivityListResponse(BaseModel):
    items: list[SalesActivityResponse]
    total: int


class SalesDashboardStats(BaseModel):
    total_leads: int
    new_leads: int
    qualified_leads: int
    total_deals: int
    pipeline_value: Decimal
    won_deals: int
    won_value: Decimal
    total_customers: int
    leads_by_status: dict[str, int]
    leads_by_source: dict[str, int]
    pipeline_by_stage: list[SalesPipelineStageSummary]


class SalesDashboardResponse(BaseModel):
    stats: SalesDashboardStats
    recent_activities: list[SalesActivityResponse]


# ─── Commercial Proposals ────────────────────────────────────────────────────

ProposalStatus = Literal["draft", "sent", "viewed", "accepted", "rejected", "expired"]

PROPOSAL_STATUSES: list[ProposalStatus] = [
    "draft", "sent", "viewed", "accepted", "rejected", "expired",
]


class SalesProposalItemBase(BaseModel):
    product_or_service_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    quantity: Decimal = Field(Decimal("1"), gt=0)
    unit_price: Decimal = Field(Decimal("0"), ge=0)
    discount: Decimal = Field(Decimal("0"), ge=0)


class SalesProposalItemCreate(SalesProposalItemBase):
    pass


class SalesProposalItemResponse(SalesProposalItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    proposal_id: UUID
    total: Decimal
    sort_order: int
    created_at: datetime


class SalesProposalStatusEvent(BaseModel):
    status: ProposalStatus
    at: datetime
    note: str | None = None


class SalesProposalBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    customer_id: UUID | None = None
    lead_id: UUID | None = None
    deal_id: UUID | None = None
    issue_date: datetime
    valid_until: datetime | None = None
    currency: str = Field("USD", max_length=10)
    discount: Decimal = Field(Decimal("0"), ge=0)
    tax: Decimal = Field(Decimal("0"), ge=0)
    notes: str | None = None
    terms: str | None = None


class SalesProposalCreate(SalesProposalBase):
    items: list[SalesProposalItemCreate] = Field(default_factory=list, min_length=1)

    @field_validator("items")
    @classmethod
    def validate_items(cls, v: list[SalesProposalItemCreate]) -> list[SalesProposalItemCreate]:
        if not v:
            raise ValueError("At least one line item is required")
        return v


class SalesProposalUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    customer_id: UUID | None = None
    lead_id: UUID | None = None
    deal_id: UUID | None = None
    issue_date: datetime | None = None
    valid_until: datetime | None = None
    currency: str | None = Field(None, max_length=10)
    discount: Decimal | None = Field(None, ge=0)
    tax: Decimal | None = Field(None, ge=0)
    notes: str | None = None
    terms: str | None = None
    items: list[SalesProposalItemCreate] | None = None


class SalesProposalStatusUpdate(BaseModel):
    status: ProposalStatus
    close_deal_on_reject: bool = False


class SalesProposalResponse(SalesProposalBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    proposal_number: str
    subtotal: Decimal
    total: Decimal
    status: ProposalStatus
    version: int = 1
    sent_at: datetime | None = None
    accepted_at: datetime | None = None
    attachment_url: str | None = None
    status_history: list[SalesProposalStatusEvent] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    items: list[SalesProposalItemResponse] = Field(default_factory=list)
    customer_name: str | None = None
    lead_name: str | None = None
    deal_title: str | None = None


class SalesProposalListResponse(BaseModel):
    items: list[SalesProposalResponse]
    total: int
