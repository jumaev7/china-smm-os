"""Buyer Acquisition Platform Consolidation v1 — unified read-only aggregation schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

BuyerAcquisitionPipelineStage = Literal[
    "discovered",
    "researched",
    "qualified",
    "contacted",
    "opportunity",
    "customer",
]

BuyerAcquisitionOpportunitySource = Literal["marketplace", "discovery", "network"]

BuyerAcquisitionRelationshipStatus = Literal[
    "discovered",
    "contacted",
    "active",
    "customer",
    "strategic",
    "unknown",
]


class BuyerAcquisitionOverview(BaseModel):
    total_buyers: int = 0
    strategic_buyers: int = 0
    high_potential_buyers: int = 0
    marketplace_opportunities: int = 0
    network_opportunities: int = 0
    discovery_buyers: int = 0
    network_profiles: int = 0
    intelligence_buyers: int = 0
    average_opportunity_score: int = 0
    average_buyer_score: int = 0
    average_network_strength: int = 0
    integration_checks: List[dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = (
        "Read-only aggregation — no automatic outreach, messaging, or CRM writes."
    )


class UnifiedBuyerProfile(BaseModel):
    unified_key: str
    company_name: str
    country: Optional[str] = None
    city: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    opportunity_score: int = Field(default=0, ge=0, le=100)
    buyer_score: int = Field(default=0, ge=0, le=100)
    network_strength: int = Field(default=0, ge=0, le=100)
    relationship_status: BuyerAcquisitionRelationshipStatus = "unknown"
    pipeline_stage: BuyerAcquisitionPipelineStage = "discovered"
    classification: Optional[str] = None
    sources: List[str] = Field(default_factory=list)
    discovery_id: Optional[UUID] = None
    network_id: Optional[UUID] = None
    intelligence_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    discovered_at: Optional[datetime] = None


class UnifiedBuyersResponse(BaseModel):
    items: List[UnifiedBuyerProfile]
    total: int
    errors: List[str] = Field(default_factory=list)


class UnifiedOpportunityItem(BaseModel):
    opportunity_id: str
    title: str
    source: BuyerAcquisitionOpportunitySource
    buyer_company: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    score: int = Field(default=0, ge=0, le=100)
    opportunity_type: Optional[str] = None
    estimated_value: Optional[float] = None
    status: Optional[str] = None
    description: Optional[str] = None


class UnifiedOpportunitiesResponse(BaseModel):
    items: List[UnifiedOpportunityItem]
    total: int
    marketplace_count: int = 0
    discovery_count: int = 0
    network_count: int = 0
    errors: List[str] = Field(default_factory=list)


class PipelineStageCount(BaseModel):
    stage: BuyerAcquisitionPipelineStage
    count: int
    label: str


class UnifiedPipelineResponse(BaseModel):
    stages: List[PipelineStageCount]
    total: int
    errors: List[str] = Field(default_factory=list)


class BuyerAcquisitionInsightItem(BaseModel):
    rank: int
    company_name: str
    country: Optional[str] = None
    industry: Optional[str] = None
    score: int = 0
    buyer_score: int = 0
    network_strength: int = 0
    opportunity_score: int = 0
    relationship_status: Optional[str] = None
    source: Optional[str] = None
    buyer_id: Optional[str] = None


class MarketSegmentItem(BaseModel):
    label: str
    count: int
    share_pct: float = 0.0


class BuyerAcquisitionInsights(BaseModel):
    top_buyers: List[BuyerAcquisitionInsightItem] = Field(default_factory=list)
    strongest_relationships: List[BuyerAcquisitionInsightItem] = Field(default_factory=list)
    highest_opportunity_buyers: List[BuyerAcquisitionInsightItem] = Field(default_factory=list)
    best_countries: List[MarketSegmentItem] = Field(default_factory=list)
    best_industries: List[MarketSegmentItem] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = (
        "Read-only aggregation — no automatic outreach, messaging, or CRM writes."
    )


class BuyerAcquisitionSummaryWidget(BaseModel):
    total_buyers: int = 0
    strategic_buyers: int = 0
    high_potential_buyers: int = 0
    marketplace_opportunities: int = 0
    network_opportunities: int = 0
    top_buyer_name: Optional[str] = None
    top_buyer_score: int = 0
    errors: List[str] = Field(default_factory=list)
