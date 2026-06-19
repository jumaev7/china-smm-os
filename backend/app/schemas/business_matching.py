"""Business Matching Center — request/response schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.buyer_crm import DistributionItem

OpportunityStatus = Literal["new", "contacted", "qualified", "negotiation", "won", "lost"]
OpportunityType = Literal["import", "distribution", "government", "retail", "general"]
RecommendationPriority = Literal["urgent", "high", "medium", "low"]


class MatchScoreResult(BaseModel):
    match_score: int = Field(ge=0, le=100)
    confidence_score: int = Field(ge=0, le=100)
    reasoning: str
    match_factors: dict[str, int | float | str] = Field(default_factory=dict)


class BusinessMatchingKpis(BaseModel):
    total_opportunities: int = 0
    high_value_opportunities: int = 0
    active_matches: int = 0
    estimated_pipeline_value: Decimal = Decimal("0")
    average_match_score: int = 0


class BusinessMatchingOpportunityItem(BaseModel):
    id: UUID
    title: str
    opportunity_type: str
    buyer_id: UUID | None = None
    buyer_company: str | None = None
    supplier_tenant_id: UUID | None = None
    supplier_company: str | None = None
    score: int
    confidence_score: int
    estimated_value: Decimal | None = None
    status: str
    notes: str | None = None
    match_reasoning: str | None = None
    country: str | None = None
    industry: str | None = None
    created_at: datetime
    updated_at: datetime


class BusinessMatchingBuyerItem(BaseModel):
    id: UUID
    company_name: str
    country: str | None = None
    industry: str | None = None
    status: str
    match_score: int
    confidence_score: int
    recommended_actions: list[str] = Field(default_factory=list)
    similar_buyers: list[str] = Field(default_factory=list)
    product_categories: list[str] = Field(default_factory=list)


class BusinessMatchingSupplierItem(BaseModel):
    tenant_id: UUID
    company_name: str
    industry: str | None = None
    country: str | None = None
    product_categories: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    contact_email: str | None = None
    contact_phone: str | None = None
    match_score: int
    confidence_score: int
    match_reasoning: str | None = None


class BusinessMatchingRecommendation(BaseModel):
    id: str
    category: str
    priority: RecommendationPriority
    title: str
    reason: str
    recommended_action: str
    entity_id: str | None = None
    entity_type: str | None = None


class BusinessMatchingTrendPoint(BaseModel):
    period: str
    count: int


class BusinessMatchingDashboardResponse(BaseModel):
    kpis: BusinessMatchingKpis
    top_industries: list[DistributionItem] = Field(default_factory=list)
    top_countries: list[DistributionItem] = Field(default_factory=list)
    matching_opportunities: list[BusinessMatchingOpportunityItem] = Field(default_factory=list)
    recommended_buyers: list[BusinessMatchingBuyerItem] = Field(default_factory=list)
    recommended_suppliers: list[BusinessMatchingSupplierItem] = Field(default_factory=list)
    new_opportunities: list[BusinessMatchingOpportunityItem] = Field(default_factory=list)
    industry_trends: list[BusinessMatchingTrendPoint] = Field(default_factory=list)
    recommendations: list[BusinessMatchingRecommendation] = Field(default_factory=list)


class BusinessMatchingOpportunityListResponse(BaseModel):
    items: list[BusinessMatchingOpportunityItem]
    total: int


class BusinessMatchingBuyerListResponse(BaseModel):
    items: list[BusinessMatchingBuyerItem]
    total: int


class BusinessMatchingSupplierListResponse(BaseModel):
    items: list[BusinessMatchingSupplierItem]
    total: int


class BusinessMatchingOpportunityCreate(BaseModel):
    title: str
    opportunity_type: OpportunityType = "general"
    buyer_id: UUID | None = None
    supplier_tenant_id: UUID | None = None
    score: int = 0
    confidence_score: int = 0
    estimated_value: Decimal | None = None
    status: OpportunityStatus = "new"
    notes: str | None = None
    match_reasoning: str | None = None


class BusinessMatchingOpportunityUpdate(BaseModel):
    title: str | None = None
    opportunity_type: OpportunityType | None = None
    buyer_id: UUID | None = None
    supplier_tenant_id: UUID | None = None
    score: int | None = None
    confidence_score: int | None = None
    estimated_value: Decimal | None = None
    status: OpportunityStatus | None = None
    notes: str | None = None
    match_reasoning: str | None = None
