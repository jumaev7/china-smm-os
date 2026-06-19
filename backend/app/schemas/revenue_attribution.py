"""Revenue Attribution Automation v1 — read-only analytics schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

RevenueSourceKey = Literal["wechat", "whatsapp", "website", "referral", "manual", "unknown"]


class RevenueAttributionObject(BaseModel):
    source: str
    label: str = ""
    revenue: Decimal = Decimal("0")
    deals: int = 0
    conversion_rate: float = 0.0
    avg_deal_size: Decimal = Decimal("0")


class RevenueAttributionChannelObject(BaseModel):
    channel: str
    label: str = ""
    revenue: Decimal = Decimal("0")
    deals: int = 0
    conversion_rate: float = 0.0
    avg_deal_size: Decimal = Decimal("0")


class RevenueAttributionOverviewResponse(BaseModel):
    total_revenue: Decimal = Decimal("0")
    deals_won: int = 0
    avg_deal_size: Decimal = Decimal("0")
    conversion_rate: float = 0.0
    proposal_conversion_rate: float = 0.0
    total_leads: int = 0
    currency: str = "UZS"
    recalculated_at: Optional[datetime] = None
    errors: List[str] = Field(default_factory=list)


class RevenueAttributionSourcesResponse(BaseModel):
    items: List[RevenueAttributionObject] = Field(default_factory=list)
    total: int = 0
    errors: List[str] = Field(default_factory=list)


class RevenueAttributionChannelsResponse(BaseModel):
    items: List[RevenueAttributionChannelObject] = Field(default_factory=list)
    total: int = 0
    errors: List[str] = Field(default_factory=list)


class RevenueAttributionConversionRow(BaseModel):
    metric: str
    label: str
    numerator: int = 0
    denominator: int = 0
    rate: float = 0.0


class RevenueAttributionConversionsResponse(BaseModel):
    items: List[RevenueAttributionConversionRow] = Field(default_factory=list)
    proposal_conversion_rate: float = 0.0
    errors: List[str] = Field(default_factory=list)


class RevenueAttributionInsightItem(BaseModel):
    key: str
    label: str
    value: str = ""
    metric: Optional[str] = None
    revenue: Optional[Decimal] = None
    conversion_rate: Optional[float] = None


class RevenueAttributionInsightsResponse(BaseModel):
    best_source: Optional[RevenueAttributionInsightItem] = None
    best_channel: Optional[RevenueAttributionInsightItem] = None
    best_proposal_source: Optional[RevenueAttributionInsightItem] = None
    weakest_source: Optional[RevenueAttributionInsightItem] = None
    summary: str = ""
    errors: List[str] = Field(default_factory=list)


class RevenueAttributionRecalculateRequest(BaseModel):
    client_id: Optional[UUID] = None


class RevenueAttributionRecalculateResponse(BaseModel):
    overview: RevenueAttributionOverviewResponse
    sources_count: int = 0
    channels_count: int = 0
    message: str = "Revenue attribution recalculated — analytics only, no CRM changes"


class RevenueAttributionLeadSummary(BaseModel):
    lead_id: UUID
    source: str
    source_label: str
    channel: str
    channel_label: str
    campaign: Optional[str] = None
    attribution_link_id: Optional[UUID] = None
    won_revenue: Optional[Decimal] = None
    deal_count: int = 0


class RevenueAttributionSummaryWidget(BaseModel):
    total_revenue: Decimal = Decimal("0")
    deals_won: int = 0
    conversion_rate: float = 0.0
    best_source: Optional[str] = None
    best_source_label: Optional[str] = None
    best_channel: Optional[str] = None
    best_channel_label: Optional[str] = None
