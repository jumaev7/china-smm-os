from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

CommissionStatus = Literal["pending", "approved", "paid"]
RevenueEventType = Literal["won", "commission_approved", "commission_paid"]


class CrmDealMarkWonRequest(BaseModel):
    deal_amount: Decimal = Field(..., gt=0)
    commission_percent: Decimal = Field(..., ge=0, le=100)
    currency: str = Field(default="UZS", max_length=10)
    partner_commission_percent: Optional[Decimal] = Field(
        None, ge=0, le=100,
        description="Partner share of total agency fee (%). Auto-set when lead has partner.",
    )


class AttributionBreakdownItem(BaseModel):
    source: str
    label: str
    deal_count: int
    revenue: Decimal
    commission: Decimal


class RevenueDealRow(BaseModel):
    deal_id: UUID
    title: str
    client_name: Optional[str] = None
    lead_name: Optional[str] = None
    attribution_source: Optional[str] = None
    deal_amount: Optional[Decimal] = None
    currency: str = "UZS"
    commission_percent: Optional[Decimal] = None
    commission_amount: Optional[Decimal] = None
    commission_status: Optional[CommissionStatus] = None
    partner_commission_percent: Optional[Decimal] = None
    partner_commission_amount: Optional[Decimal] = None
    status: str
    updated_at: datetime


class AttributionLinkStatsItem(BaseModel):
    link_id: UUID
    title: str
    code: str
    channel: str
    clicks_count: int
    leads_count: int
    won_deals_count: int
    revenue: Decimal
    commission: Decimal
    click_to_lead_rate: float
    lead_to_won_rate: float


class RevenueOverviewResponse(BaseModel):
    total_pipeline_value: Decimal
    total_closed_revenue: Decimal
    total_commission_earned: Decimal
    pending_commission: Decimal
    paid_commission: Decimal
    our_commission: Decimal = Decimal("0")
    partner_commission: Decimal = Decimal("0")
    deals_won: int
    deals_lost: int
    attribution_breakdown: List[AttributionBreakdownItem]
    attribution_links: List[AttributionLinkStatsItem] = Field(default_factory=list)
    deals: List[RevenueDealRow] = Field(default_factory=list)
    deals_total: int = 0
    errors: List[str] = Field(default_factory=list)


class RevenueAiInsightsResponse(BaseModel):
    summary: str
    risks: List[str]
    opportunities: List[str]
    recommendations: List[str]
    source: str = "fallback"
