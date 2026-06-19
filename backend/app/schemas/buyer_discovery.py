"""Export Buyer Discovery Engine v1 — read-only buyer discovery schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

BuyerDiscoveryCategory = Literal[
    "high_potential",
    "strategic",
    "active",
    "new",
    "watchlist",
]

BuyerDiscoveryPipelineStage = Literal[
    "discovered",
    "researched",
    "qualified",
    "contacted",
    "opportunity",
    "customer",
]

BuyerDiscoveryContactStatus = Literal[
    "unknown",
    "not_contacted",
    "contacted",
    "engaged",
    "qualified",
    "inactive",
]


class BuyerDiscoveryOverview(BaseModel):
    total_buyers: int = 0
    high_potential: int = 0
    strategic: int = 0
    active: int = 0
    new_buyers: int = 0
    watchlist: int = 0
    average_opportunity_score: int = 0
    pipeline_discovered: int = 0
    pipeline_researched: int = 0
    pipeline_qualified: int = 0
    pipeline_contacted: int = 0
    pipeline_opportunity: int = 0
    pipeline_customer: int = 0
    integration_checks: List[dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = (
        "Read-only intelligence — no automatic outreach, messaging, or CRM writes."
    )


class BuyerRegistryItem(BaseModel):
    id: UUID
    company_name: str
    country: Optional[str] = None
    city: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    contact_status: str = "unknown"
    source: str = "crm_sync"
    discovered_at: datetime
    opportunity_score: int = Field(ge=0, le=100)
    category: BuyerDiscoveryCategory
    pipeline_stage: BuyerDiscoveryPipelineStage
    crm_lead_id: Optional[UUID] = None
    client_id: UUID


class BuyerRegistryResponse(BaseModel):
    items: List[BuyerRegistryItem]
    total: int


class BuyerOpportunityRankingItem(BaseModel):
    rank: int
    buyer_id: UUID
    company_name: str
    country: Optional[str] = None
    industry: Optional[str] = None
    opportunity_score: int
    category: BuyerDiscoveryCategory
    pipeline_stage: BuyerDiscoveryPipelineStage
    metric_label: str = ""


class BuyerTopOpportunitiesResponse(BaseModel):
    top_buyers: List[BuyerOpportunityRankingItem] = Field(default_factory=list)
    fastest_growing: List[BuyerOpportunityRankingItem] = Field(default_factory=list)
    highest_opportunity: List[BuyerOpportunityRankingItem] = Field(default_factory=list)
    strategic_buyers: List[BuyerOpportunityRankingItem] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class MarketInsightSegment(BaseModel):
    label: str
    count: int
    share_pct: float = 0.0


class BuyerMarketInsightsResponse(BaseModel):
    top_countries: List[MarketInsightSegment] = Field(default_factory=list)
    top_industries: List[MarketInsightSegment] = Field(default_factory=list)
    top_buyer_segments: List[MarketInsightSegment] = Field(default_factory=list)
    total_buyers: int = 0
    errors: List[str] = Field(default_factory=list)


class PipelineStageCount(BaseModel):
    stage: BuyerDiscoveryPipelineStage
    count: int
    label: str


class BuyerPipelineResponse(BaseModel):
    stages: List[PipelineStageCount] = Field(default_factory=list)
    total: int = 0
    errors: List[str] = Field(default_factory=list)


class BuyerDiscoveryRecalculateRequest(BaseModel):
    client_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    limit: int = Field(default=500, ge=1, le=2000)


class BuyerDiscoveryRecalculateResponse(BaseModel):
    synced: int
    recalculated: int
    overview: BuyerDiscoveryOverview
    message: str
    errors: List[str] = Field(default_factory=list)


class BuyerDiscoverySummaryWidget(BaseModel):
    total_buyers: int = 0
    high_potential: int = 0
    strategic: int = 0
    new_buyers: int = 0
    watchlist: int = 0
    average_opportunity_score: int = 0
    pipeline_opportunity: int = 0
    top_buyer_name: Optional[str] = None
    top_buyer_score: int = 0
    errors: List[str] = Field(default_factory=list)


class BuyerDiscoveryExecutiveInsights(BaseModel):
    overview: BuyerDiscoveryOverview
    best_markets: List[MarketInsightSegment] = Field(default_factory=list)
    top_industries: List[MarketInsightSegment] = Field(default_factory=list)
    highest_potential_buyers: List[BuyerOpportunityRankingItem] = Field(default_factory=list)
    acquisition_opportunities: List[BuyerOpportunityRankingItem] = Field(default_factory=list)
    strategic_buyers: List[BuyerOpportunityRankingItem] = Field(default_factory=list)
    safety_notice: str = (
        "Read-only intelligence — no automatic outreach, messaging, or CRM writes."
    )
