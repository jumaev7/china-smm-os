"""Pydantic schemas for Factory Growth Center executive dashboard."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.buyer_crm import DistributionItem

HealthStatus = Literal["healthy", "warning", "critical"]
RecommendationPriority = Literal["urgent", "high", "medium", "low"]
TimelineEventType = Literal[
    "lead", "buyer", "proposal", "communication", "deal_change", "activity",
]
ExportFormat = Literal["pdf", "excel"]


class GrowthCenterOverviewKpis(BaseModel):
    total_leads: int = 0
    total_buyers: int = 0
    active_buyers: int = 0
    active_leads: int = 0
    total_deals: int = 0
    deals_won: int = 0
    deals_lost: int = 0
    total_proposal_value: Decimal = Decimal("0")
    pipeline_value: Decimal = Decimal("0")
    expected_revenue: Decimal = Decimal("0")
    follow_ups_due: int = 0


class GrowthCenterTrendPoint(BaseModel):
    period: str
    count: int


class GrowthCenterMarketInsights(BaseModel):
    buyers_by_country: list[DistributionItem] = Field(default_factory=list)
    buyers_by_industry: list[DistributionItem] = Field(default_factory=list)
    leads_by_source: list[DistributionItem] = Field(default_factory=list)
    proposal_acceptance_rate: float = 0.0
    buyer_growth_trend: list[GrowthCenterTrendPoint] = Field(default_factory=list)


class GrowthCenterHealthIndicator(BaseModel):
    score: int = Field(ge=0, le=100)
    status: HealthStatus
    label: str
    summary: str


class GrowthCenterHealthScores(BaseModel):
    lead_health: GrowthCenterHealthIndicator
    buyer_health: GrowthCenterHealthIndicator
    deal_health: GrowthCenterHealthIndicator
    communication_health: GrowthCenterHealthIndicator


class GrowthCenterRecommendation(BaseModel):
    id: str
    priority: RecommendationPriority
    title: str
    expected_impact: str
    reason: str
    recommended_action: str
    href: str | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None


class GrowthCenterOpportunity(BaseModel):
    id: UUID
    buyer: str
    country: str | None
    potential_value: Decimal
    currency: str = "USD"
    deal_stage: str
    probability: int
    score: Decimal


class GrowthCenterTimelineItem(BaseModel):
    id: str
    type: TimelineEventType
    title: str
    subtitle: str | None = None
    occurred_at: datetime
    href: str | None = None


class GrowthCenterExportFormatInfo(BaseModel):
    format: ExportFormat
    label: str
    mime_type: str
    available: bool
    description: str


class GrowthCenterExportRequest(BaseModel):
    include_kpis: bool = True
    include_market_insights: bool = True
    include_opportunities: bool = True
    include_recommendations: bool = True
    include_timeline: bool = False
    locale: str = "en"


class GrowthCenterExportResponse(BaseModel):
    format: ExportFormat
    status: Literal["not_implemented", "ready"]
    message: str
    download_url: str | None = None
    filename: str | None = None


class GrowthCenterDashboardResponse(BaseModel):
    kpis: GrowthCenterOverviewKpis
    market_insights: GrowthCenterMarketInsights
    health_scores: GrowthCenterHealthScores
    recommendations: list[GrowthCenterRecommendation]
    opportunities: list[GrowthCenterOpportunity]
    timeline: list[GrowthCenterTimelineItem]
    export_formats: list[GrowthCenterExportFormatInfo]
    generated_at: datetime


class GrowthCenterSummaryResponse(BaseModel):
    total_leads: int = 0
    total_buyers: int = 0
    active_buyers: int = 0
    total_deals: int = 0
    pipeline_value: Decimal = Decimal("0")
    proposal_value: Decimal = Decimal("0")
    followups_due: int = 0
    growth_score: int = Field(default=0, ge=0, le=100)
    top_recommendations: list[GrowthCenterRecommendation] = Field(default_factory=list)
    generated_at: datetime
