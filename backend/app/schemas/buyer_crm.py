"""Pydantic schemas for tenant Buyer Network CRM."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

BuyerStatus = Literal[
    "prospect", "contacted", "interested", "negotiating", "active_buyer", "inactive",
]
BuyerActivityType = Literal["call", "email", "meeting", "note", "status_change", "link", "other"]
BuyerEntityType = Literal["lead", "deal", "customer", "proposal"]

BUYER_STATUSES: list[BuyerStatus] = [
    "prospect", "contacted", "interested", "negotiating", "active_buyer", "inactive",
]
CENTRAL_ASIA_COUNTRIES = [
    "Uzbekistan", "Kazakhstan", "Kyrgyzstan", "Tajikistan", "Turkmenistan",
]


class BuyerBase(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    contact_person: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    industry: str | None = Field(None, max_length=100)
    website: str | None = Field(None, max_length=500)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    telegram: str | None = Field(None, max_length=100)
    whatsapp: str | None = Field(None, max_length=100)
    wechat: str | None = Field(None, max_length=100)
    annual_purchase_volume: str | None = Field(None, max_length=100)
    product_categories: list[str] | None = None
    notes: str | None = None
    tags: list[str] | None = None
    status: BuyerStatus = "prospect"

    @field_validator("product_categories", "tags", mode="before")
    @classmethod
    def normalize_string_lists(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [str(item).strip() for item in v if str(item).strip()]


class BuyerCreate(BuyerBase):
    pass


class BuyerUpdate(BaseModel):
    company_name: str | None = Field(None, min_length=1, max_length=255)
    contact_person: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    industry: str | None = Field(None, max_length=100)
    website: str | None = Field(None, max_length=500)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    telegram: str | None = Field(None, max_length=100)
    whatsapp: str | None = Field(None, max_length=100)
    wechat: str | None = Field(None, max_length=100)
    annual_purchase_volume: str | None = Field(None, max_length=100)
    product_categories: list[str] | None = None
    notes: str | None = None
    tags: list[str] | None = None
    status: BuyerStatus | None = None

    @field_validator("product_categories", "tags", mode="before")
    @classmethod
    def normalize_string_lists(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [str(item).strip() for item in v if str(item).strip()]


class BuyerResponse(BuyerBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime
    link_count: int = 0


class BuyerDetailResponse(BuyerResponse):
    linked_leads: list["BuyerLinkedEntity"] = []
    linked_deals: list["BuyerLinkedEntity"] = []
    linked_customers: list["BuyerLinkedEntity"] = []
    linked_proposals: list["BuyerLinkedEntity"] = []


class BuyerListResponse(BaseModel):
    items: list[BuyerResponse]
    total: int


class DistributionItem(BaseModel):
    label: str
    count: int


class BuyerDashboardResponse(BaseModel):
    total_buyers: int
    active_buyers: int
    new_buyers_this_month: int
    top_industries: list[DistributionItem]
    top_countries: list[DistributionItem]
    geographic_distribution: list[DistributionItem]
    industry_distribution: list[DistributionItem]
    by_status: dict[str, int]


class BuyerActivityCreate(BaseModel):
    type: BuyerActivityType
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    activity_date: datetime | None = None


class BuyerActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    buyer_id: UUID
    type: str
    title: str
    description: str | None
    metadata_json: dict | None = None
    activity_date: datetime
    created_by: str | None
    created_at: datetime


class BuyerActivityListResponse(BaseModel):
    items: list[BuyerActivityResponse]
    total: int


class BuyerNoteCreate(BaseModel):
    content: str = Field(..., min_length=1)


class BuyerNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    buyer_id: UUID
    content: str
    created_by: str | None
    created_at: datetime


class BuyerNoteListResponse(BaseModel):
    items: list[BuyerNoteResponse]
    total: int


class BuyerStatusHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    buyer_id: UUID
    from_status: str | None
    to_status: str
    note: str | None
    changed_by: str | None
    changed_at: datetime


class BuyerStatusHistoryListResponse(BaseModel):
    items: list[BuyerStatusHistoryResponse]
    total: int


class BuyerLinkedEntity(BaseModel):
    link_id: UUID
    entity_type: BuyerEntityType
    entity_id: UUID
    label: str
    created_at: datetime


class BuyerEntityLinkCreate(BaseModel):
    entity_type: BuyerEntityType
    entity_id: UUID


class BuyerEntityLinkListResponse(BaseModel):
    items: list[BuyerLinkedEntity]
    total: int


class BuyerTimelineItem(BaseModel):
    id: UUID
    kind: Literal["activity", "note", "status_change"]
    title: str
    description: str | None
    occurred_at: datetime
    meta: dict | None = None


class BuyerTimelineResponse(BaseModel):
    items: list[BuyerTimelineItem]
    total: int
