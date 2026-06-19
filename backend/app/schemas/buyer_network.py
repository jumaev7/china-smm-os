"""Export Buyer Network v1 — global buyer network schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

BuyerNetworkClassification = Literal[
    "strategic",
    "high_potential",
    "active",
    "growing",
    "watchlist",
    "underutilized",
]

BuyerNetworkStatus = Literal[
    "strategic",
    "active",
    "growing",
    "watchlist",
    "underutilized",
]

BuyerRelationshipType = Literal[
    "discovered",
    "contacted",
    "active",
    "customer",
    "strategic",
]


class BuyerNetworkOverview(BaseModel):
    total_profiles: int = 0
    total_relationships: int = 0
    strategic_buyers: int = 0
    high_potential: int = 0
    active_buyers: int = 0
    underutilized: int = 0
    average_opportunity_score: int = 0
    average_network_strength: int = 0
    tenants_connected: int = 0
    integration_checks: List[dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = (
        "Intelligence and relationship mapping only — no automatic outreach, messaging, "
        "CRM writes, or relationship creation."
    )


class BuyerNetworkProfileItem(BaseModel):
    id: UUID
    company_name: str
    country: Optional[str] = None
    city: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    classification: BuyerNetworkClassification
    opportunity_score: int = Field(ge=0, le=100)
    network_strength: int = Field(ge=0, le=100)
    buyer_status: BuyerNetworkStatus
    relationship_count: int = 0
    created_at: datetime
    updated_at: datetime


class BuyerNetworkProfilesResponse(BaseModel):
    items: List[BuyerNetworkProfileItem]
    total: int


class BuyerRelationshipItem(BaseModel):
    id: UUID
    buyer_id: UUID
    tenant_id: UUID
    tenant_name: Optional[str] = None
    company_name: str
    relationship_type: BuyerRelationshipType
    relationship_strength: int = Field(ge=0, le=100)
    country: Optional[str] = None
    industry: Optional[str] = None
    opportunity_score: int = 0
    created_at: datetime


class BuyerNetworkRelationshipsResponse(BaseModel):
    items: List[BuyerRelationshipItem]
    total: int


class BuyerGraphNode(BaseModel):
    buyer_id: UUID
    company_name: str
    country: Optional[str] = None
    industry: Optional[str] = None
    opportunity_score: int = 0
    network_strength: int = 0
    link_reason: str = ""


class BuyerGraphSegment(BaseModel):
    label: str
    count: int
    share_pct: float = 0.0


class BuyerNetworkGraphResponse(BaseModel):
    focus_buyer_id: Optional[UUID] = None
    related_buyers: List[BuyerGraphNode] = Field(default_factory=list)
    related_industries: List[BuyerGraphSegment] = Field(default_factory=list)
    related_countries: List[BuyerGraphSegment] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class BuyerNetworkInsightItem(BaseModel):
    rank: int
    buyer_id: UUID
    company_name: str
    country: Optional[str] = None
    industry: Optional[str] = None
    opportunity_score: int
    network_strength: int
    buyer_status: BuyerNetworkStatus
    metric_label: str = ""


class BuyerNetworkInsightsResponse(BaseModel):
    strongest_buyers: List[BuyerNetworkInsightItem] = Field(default_factory=list)
    fastest_growing: List[BuyerNetworkInsightItem] = Field(default_factory=list)
    strategic_buyers: List[BuyerNetworkInsightItem] = Field(default_factory=list)
    underutilized_buyers: List[BuyerNetworkInsightItem] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class BuyerNetworkTopBuyersResponse(BaseModel):
    top_buyers: List[BuyerNetworkInsightItem] = Field(default_factory=list)
    by_network_strength: List[BuyerNetworkInsightItem] = Field(default_factory=list)
    by_opportunity: List[BuyerNetworkInsightItem] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class BuyerNetworkRecalculateRequest(BaseModel):
    tenant_id: Optional[UUID] = None
    limit: int = Field(default=500, ge=1, le=2000)


class BuyerNetworkRecalculateResponse(BaseModel):
    profiles_synced: int
    profiles_recalculated: int
    relationships_recalculated: int
    overview: BuyerNetworkOverview
    message: str
    errors: List[str] = Field(default_factory=list)


class BuyerNetworkSummaryWidget(BaseModel):
    total_profiles: int = 0
    strategic_buyers: int = 0
    active_buyers: int = 0
    underutilized: int = 0
    average_network_strength: int = 0
    top_buyer_name: Optional[str] = None
    top_buyer_score: int = 0
    errors: List[str] = Field(default_factory=list)


class BuyerNetworkExecutiveSummary(BaseModel):
    overview: BuyerNetworkOverview
    strongest_buyers: List[BuyerNetworkInsightItem] = Field(default_factory=list)
    strategic_buyers: List[BuyerNetworkInsightItem] = Field(default_factory=list)
    top_countries: List[BuyerGraphSegment] = Field(default_factory=list)
    safety_notice: str = (
        "Intelligence and relationship mapping only — no automatic outreach, messaging, "
        "CRM writes, or relationship creation."
    )
