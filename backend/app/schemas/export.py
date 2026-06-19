from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.buyer_finder import BuyerOpportunitySummary

DemandLevel = Literal["low", "medium", "high", "very_high"]


class ExportOpportunityResponse(BaseModel):
    id: UUID
    client_id: UUID
    product_id: UUID
    country: str
    score: float
    market_summary: str | None
    demand_level: str | None
    recommended_partner_types_json: list[str] | None
    recommended_channels_json: list[str] | None
    created_at: datetime
    product_name: str | None = None
    product_category: str | None = None
    company_name: str | None = None

    model_config = {"from_attributes": True}


class ExportOpportunityDetailResponse(ExportOpportunityResponse):
    insights: list["ExportInsightResponse"] = Field(default_factory=list)
    score_factors: dict[str, Any] | None = None


class ExportInsightResponse(BaseModel):
    id: UUID
    product_id: UUID
    insight_type: str
    title: str
    description: str
    confidence: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExportOpportunityListResponse(BaseModel):
    items: list[ExportOpportunityResponse]
    total: int


class ExportCountryRanking(BaseModel):
    country: str
    opportunity_count: int
    avg_score: float
    max_score: float


class ExportDashboardResponse(BaseModel):
    top_opportunities: list[ExportOpportunityResponse]
    country_rankings: list[ExportCountryRanking]
    total_opportunities: int
    avg_score: float
    products_analyzed: int
    top_buyer_opportunities: list[BuyerOpportunitySummary] = Field(default_factory=list)


class ExportAnalyzeProductResponse(BaseModel):
    product_id: UUID
    product_name: str
    overall_score: float
    market_summary: str
    top_countries: list[str]
    top_partner_types: list[str]
    top_channels: list[str]
    opportunities: list[ExportOpportunityResponse]
    insights: list[ExportInsightResponse]
    demo_mode: bool = False
