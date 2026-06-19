from datetime import datetime
from decimal import Decimal
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

PartnerStatus = Literal["active", "inactive"]
PartnerType = Literal[
    "distributor", "dealer", "importer", "agent",
    "retail_chain", "construction_company", "other",
]
PartnerActivityType = Literal["call", "email", "meeting", "note", "match", "other"]


class ReferralLinkResponse(BaseModel):
    id: UUID
    partner_id: UUID
    code: str
    description: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PartnerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company: Optional[str] = Field(None, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    partner_type: Optional[PartnerType] = None
    industries_json: Optional[List[str]] = None
    website: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=50)
    telegram: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    status: PartnerStatus = "active"
    notes: Optional[str] = None
    referral_code: Optional[str] = Field(None, min_length=2, max_length=50)
    referral_description: Optional[str] = Field(None, max_length=255)


class PartnerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    company: Optional[str] = Field(None, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    partner_type: Optional[PartnerType] = None
    industries_json: Optional[List[str]] = None
    website: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=50)
    telegram: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    status: Optional[PartnerStatus] = None
    notes: Optional[str] = None


class PartnerResponse(BaseModel):
    id: UUID
    name: str
    company: Optional[str] = None
    company_name: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    partner_type: Optional[str] = None
    industries_json: List[str] = Field(default_factory=list)
    website: Optional[str] = None
    phone: Optional[str] = None
    telegram: Optional[str] = None
    email: Optional[str] = None
    status: PartnerStatus
    notes: Optional[str] = None
    referral_links: List[ReferralLinkResponse] = Field(default_factory=list)
    leads_count: int = 0
    won_deals: int = 0
    revenue: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PartnerListResponse(BaseModel):
    items: List[PartnerResponse]
    total: int


class PartnerFiltersResponse(BaseModel):
    countries: List[str]
    partner_types: List[str]
    industries: List[str]


class PartnerActivityCreate(BaseModel):
    activity_type: PartnerActivityType
    description: str = Field(..., min_length=1)


class PartnerActivityResponse(BaseModel):
    id: UUID
    partner_id: UUID
    activity_type: str
    description: str
    created_at: datetime


class PartnerHubProductItem(BaseModel):
    interest_id: UUID
    product_id: UUID
    name: str
    category: Optional[str] = None
    unit_price: Optional[Decimal] = None
    currency: str = "USD"
    interest_score: Optional[float] = None
    notes: Optional[str] = None


class PartnerHubLeadItem(BaseModel):
    id: UUID
    name: str
    company: Optional[str] = None
    status: str
    interest: Optional[str] = None
    referral_code: Optional[str] = None
    created_at: Optional[datetime] = None
    match_hits: Optional[int] = None


class PartnerHubResponse(BaseModel):
    id: UUID
    name: str
    company_name: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    partner_type: Optional[str] = None
    industries_json: List[str] = Field(default_factory=list)
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    status: PartnerStatus
    notes: Optional[str] = None
    leads_count: int = 0
    won_deals: int = 0
    revenue: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    activities: List[PartnerActivityResponse] = Field(default_factory=list)
    related_products: List[PartnerHubProductItem] = Field(default_factory=list)
    related_leads: List[PartnerHubLeadItem] = Field(default_factory=list)
    matched_leads: List[PartnerHubLeadItem] = Field(default_factory=list)


class PartnerMatchItem(BaseModel):
    partner_id: UUID
    name: str
    company_name: Optional[str] = None
    partner_type: Optional[str] = None
    country: Optional[str] = None
    score: float = Field(..., ge=0, le=1)
    reason: str


class PartnerMatchProductResponse(BaseModel):
    product_id: UUID
    product_name: str
    query_context: str
    matches: List[PartnerMatchItem]
    demo_mode: bool = False


class PartnerMatchLeadResponse(BaseModel):
    lead_id: UUID
    lead_name: str
    query_context: str
    matches: List[PartnerMatchItem]
    demo_mode: bool = False


class PartnerPerformanceLeadItem(BaseModel):
    id: UUID
    name: str
    company: Optional[str] = None
    status: str
    estimated_value: Optional[Decimal] = None
    referral_code: Optional[str] = None
    created_at: datetime


class PartnerPerformanceDealItem(BaseModel):
    id: UUID
    title: str
    status: str
    deal_amount: Optional[Decimal] = None
    currency: str = "UZS"
    partner_commission_amount: Optional[Decimal] = None
    commission_amount: Optional[Decimal] = None
    updated_at: datetime


class PartnerTimelineItem(BaseModel):
    id: UUID
    deal_id: UUID
    deal_title: str
    event_type: str
    title: str
    created_at: datetime


class PartnerPerformanceResponse(BaseModel):
    partner_id: UUID
    leads: int
    won_deals: int
    revenue: Decimal
    commission: Decimal
    our_commission: Decimal = Decimal("0")
    lead_items: List[PartnerPerformanceLeadItem] = Field(default_factory=list)
    deal_items: List[PartnerPerformanceDealItem] = Field(default_factory=list)
    timeline: List[PartnerTimelineItem] = Field(default_factory=list)


class PartnerAiInsightsResponse(BaseModel):
    best_opportunities: List[str]
    inactive_leads: List[str]
    revenue_forecast: str
    recommended_actions: List[str]
    source: str = "fallback"
