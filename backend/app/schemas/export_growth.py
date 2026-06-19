"""Pydantic schemas for AI Export Growth Engine executive dashboard."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.buyer_crm import DistributionItem

RecommendationPriority = Literal["urgent", "high", "medium", "low"]
OpportunityCategory = Literal[
    "deal", "buyer", "proposal", "matching", "market", "content", "communication",
]
MarketOpportunityType = Literal["country", "industry", "product"]
BuyerRecommendationType = Literal[
    "follow_up", "high_potential", "inactive", "new_target",
]
SalesRecommendationType = Literal[
    "at_risk", "fast_close", "high_value", "stalled",
]
ContentRecommendationType = Literal["publish", "create", "localize", "promote"]


class ExportGrowthScoreFactor(BaseModel):
    factor: str
    weight_pct: int = Field(ge=0, le=100)
    score: int = Field(ge=0, le=100)
    weighted_contribution: float
    summary: str


class ExportGrowthScore(BaseModel):
    score: int = Field(ge=0, le=100)
    label: str
    summary: str
    factors: list[ExportGrowthScoreFactor] = Field(default_factory=list)


class ExportGrowthKpis(BaseModel):
    pipeline_value: Decimal = Decimal("0")
    expected_revenue: Decimal = Decimal("0")
    opportunity_value: Decimal = Decimal("0")
    active_buyers: int = 0
    buyer_growth_pct: float = 0.0
    proposal_acceptance_rate: float = 0.0
    communication_health: int = Field(default=0, ge=0, le=100)
    export_growth_score: int = Field(default=0, ge=0, le=100)


class ExportGrowthDailyAction(BaseModel):
    id: str
    priority: RecommendationPriority
    title: str
    expected_impact: str
    reason: str
    recommended_action: str
    href: str | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None


class ExportGrowthOpportunity(BaseModel):
    id: str
    category: OpportunityCategory
    title: str
    country: str | None = None
    industry: str | None = None
    product: str | None = None
    opportunity_score: int = Field(ge=0, le=100)
    estimated_value: Decimal = Decimal("0")
    currency: str = "USD"
    recommended_action: str
    confidence_score: int = Field(ge=0, le=100)
    href: str | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None


class ExportGrowthMarketOpportunity(BaseModel):
    id: str
    type: MarketOpportunityType
    name: str
    growth_score: int = Field(ge=0, le=100)
    demand_index: int = Field(ge=0, le=100)
    buyer_count: int = 0
    estimated_value: Decimal = Decimal("0")
    currency: str = "USD"
    recommended_action: str
    data_source: str = "tenant_data"


class ExportGrowthBuyerRecommendation(BaseModel):
    id: str
    type: BuyerRecommendationType
    company_name: str
    country: str | None = None
    match_score: int = Field(ge=0, le=100)
    reason: str
    recommended_action: str
    href: str | None = None
    buyer_id: UUID | None = None


class ExportGrowthContentRecommendation(BaseModel):
    id: str
    type: ContentRecommendationType
    title: str
    language: str
    platform: str
    products: list[str] = Field(default_factory=list)
    reason: str
    recommended_action: str
    href: str | None = None


class ExportGrowthSalesRecommendation(BaseModel):
    id: str
    type: SalesRecommendationType
    deal_title: str
    buyer: str | None = None
    value: Decimal = Decimal("0")
    currency: str = "USD"
    stage: str
    probability: int = 0
    reason: str
    recommended_action: str
    href: str | None = None
    deal_id: UUID | None = None


class ExportGrowthStrategicInsight(BaseModel):
    id: str
    category: str
    title: str
    insight: str
    confidence: int = Field(ge=0, le=100)
    recommended_action: str | None = None


class ExportGrowthDashboardResponse(BaseModel):
    kpis: ExportGrowthKpis
    export_growth_score: ExportGrowthScore
    daily_actions: list[ExportGrowthDailyAction] = Field(default_factory=list)
    opportunities: list[ExportGrowthOpportunity] = Field(default_factory=list)
    market_opportunities: list[ExportGrowthMarketOpportunity] = Field(default_factory=list)
    buyer_recommendations: list[ExportGrowthBuyerRecommendation] = Field(default_factory=list)
    content_recommendations: list[ExportGrowthContentRecommendation] = Field(default_factory=list)
    sales_recommendations: list[ExportGrowthSalesRecommendation] = Field(default_factory=list)
    strategic_insights: list[ExportGrowthStrategicInsight] = Field(default_factory=list)
    growing_markets: list[DistributionItem] = Field(default_factory=list)
    demo_mode: bool = False
    generated_at: datetime


class ExportGrowthSummaryResponse(BaseModel):
    export_growth_score: ExportGrowthScore
    active_opportunities: int = 0
    high_value_opportunities: int = 0
    expected_revenue: Decimal = Decimal("0")
    buyers_to_contact: int = 0
    deals_at_risk: int = 0
    top_actions: list[ExportGrowthDailyAction] = Field(default_factory=list)
    demo_mode: bool = False
    generated_at: datetime
