"""Marketplace & Lead Exchange v1 — opportunity exchange schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

MarketplaceOpportunityType = Literal[
    "distributor",
    "importer",
    "wholesaler",
    "retailer",
    "project",
    "partnership",
]

MarketplaceOpportunityStatus = Literal["open", "in_review", "claimed", "closed"]

MarketplaceVisibility = Literal["public", "private", "tenant_only"]


class MarketplaceOverview(BaseModel):
    total_opportunities: int = 0
    open_opportunities: int = 0
    in_review: int = 0
    claimed: int = 0
    closed: int = 0
    total_views: int = 0
    total_interests: int = 0
    total_claims: int = 0
    average_estimated_value: float = 0.0
    integration_checks: List[dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = (
        "Opportunity exchange only — no automatic messaging, CRM writes, or deal creation."
    )


class MarketplaceOpportunityItem(BaseModel):
    id: UUID
    title: str
    description: Optional[str] = None
    buyer_company: str
    country: Optional[str] = None
    industry: Optional[str] = None
    opportunity_type: MarketplaceOpportunityType
    estimated_value: Optional[Decimal] = None
    status: MarketplaceOpportunityStatus
    visibility: MarketplaceVisibility
    created_by_tenant: Optional[UUID] = None
    rank_score: int = 0
    view_count: int = 0
    interest_count: int = 0
    claim_count: int = 0
    created_at: datetime
    updated_at: datetime


class MarketplaceOpportunityListResponse(BaseModel):
    items: List[MarketplaceOpportunityItem]
    total: int


class MarketplaceRankingItem(BaseModel):
    rank: int
    opportunity_id: UUID
    title: str
    buyer_company: str
    country: Optional[str] = None
    industry: Optional[str] = None
    opportunity_type: MarketplaceOpportunityType
    estimated_value: Optional[Decimal] = None
    rank_score: int = 0
    metric_label: str = ""


class MarketplaceTopOpportunitiesResponse(BaseModel):
    best_opportunities: List[MarketplaceRankingItem] = Field(default_factory=list)
    newest_opportunities: List[MarketplaceRankingItem] = Field(default_factory=list)
    strategic_opportunities: List[MarketplaceRankingItem] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class MarketplaceInsightSegment(BaseModel):
    label: str
    count: int
    share_pct: float = 0.0


class MarketplaceInsightsResponse(BaseModel):
    top_industries: List[MarketplaceInsightSegment] = Field(default_factory=list)
    top_countries: List[MarketplaceInsightSegment] = Field(default_factory=list)
    most_active_tenants: List[dict[str, Any]] = Field(default_factory=list)
    most_valuable_opportunities: List[MarketplaceRankingItem] = Field(default_factory=list)
    total_opportunities: int = 0
    errors: List[str] = Field(default_factory=list)


class MarketplaceActivityItem(BaseModel):
    id: UUID
    activity_type: Literal["view", "interest", "claim", "created"]
    opportunity_id: UUID
    opportunity_title: str
    tenant_id: Optional[UUID] = None
    tenant_label: Optional[str] = None
    occurred_at: datetime
    detail: Optional[str] = None


class MarketplaceActivityResponse(BaseModel):
    items: List[MarketplaceActivityItem]
    total: int
    errors: List[str] = Field(default_factory=list)


class MarketplaceCreateOpportunityRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    buyer_company: str = Field(min_length=1, max_length=255)
    country: Optional[str] = None
    industry: Optional[str] = None
    opportunity_type: MarketplaceOpportunityType = "distributor"
    estimated_value: Optional[Decimal] = None
    visibility: MarketplaceVisibility = "public"
    created_by_tenant: Optional[UUID] = None


class MarketplaceCreateOpportunityResponse(BaseModel):
    opportunity: MarketplaceOpportunityItem
    message: str
    errors: List[str] = Field(default_factory=list)


class MarketplaceExpressInterestRequest(BaseModel):
    opportunity_id: UUID
    tenant_id: UUID
    note: Optional[str] = None


class MarketplaceExpressInterestResponse(BaseModel):
    recorded: bool
    message: str
    errors: List[str] = Field(default_factory=list)


class MarketplaceClaimOpportunityRequest(BaseModel):
    opportunity_id: UUID
    tenant_id: UUID


class MarketplaceClaimOpportunityResponse(BaseModel):
    claimed: bool
    opportunity: Optional[MarketplaceOpportunityItem] = None
    message: str
    errors: List[str] = Field(default_factory=list)


class MarketplaceSummaryWidget(BaseModel):
    total_opportunities: int = 0
    open_opportunities: int = 0
    total_interests: int = 0
    top_opportunity_title: Optional[str] = None
    top_opportunity_value: float = 0.0
    errors: List[str] = Field(default_factory=list)


class MarketplaceExecutiveSummary(BaseModel):
    overview: MarketplaceOverview
    best_opportunities: List[MarketplaceRankingItem] = Field(default_factory=list)
    strategic_opportunities: List[MarketplaceRankingItem] = Field(default_factory=list)
    top_industries: List[MarketplaceInsightSegment] = Field(default_factory=list)
    safety_notice: str = (
        "Opportunity exchange only — no automatic messaging, CRM writes, or deal creation."
    )
