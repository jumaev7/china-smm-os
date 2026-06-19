"""Factory Partner Platform v1 — tenant-scoped factory business workspace schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.buyer_intelligence import BuyerClassification, RiskLevel
from app.schemas.deal_risk import DealRiskLevel


class FactoryPlatformTenantRef(BaseModel):
    tenant_id: UUID
    company_id: UUID
    company_name: str
    tenant_status: str = "active"


class FactoryPlatformCompanyProfile(BaseModel):
    company_id: UUID
    company_name: str
    country: Optional[str] = None
    city: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    company_description: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    markets: List[str] = Field(default_factory=list)
    industries: List[str] = Field(default_factory=list)
    export_regions: List[str] = Field(default_factory=list)
    product_categories: List[str] = Field(default_factory=list)
    business_category: Optional[str] = None
    updated_at: Optional[datetime] = None


class FactoryPlatformRevenueSummary(BaseModel):
    total_revenue: Decimal = Decimal("0")
    deals_won: int = 0
    avg_deal_size: Decimal = Decimal("0")
    conversion_rate: float = 0.0
    currency: str = "UZS"


class FactoryPlatformProposalSummary(BaseModel):
    proposal_id: UUID
    title: str
    status: str
    buyer_name: Optional[str] = None
    created_at: Optional[datetime] = None


class FactoryPlatformDashboardResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    company_profile: FactoryPlatformCompanyProfile
    active_buyers: int = 0
    active_leads: int = 0
    active_deals: int = 0
    proposals_count: int = 0
    proposals: List[FactoryPlatformProposalSummary] = Field(default_factory=list)
    revenue_summary: FactoryPlatformRevenueSummary
    billing_summary: dict[str, Any] = Field(default_factory=dict)
    safety_notice: str = (
        "Factory workspace — tenant-scoped data only. No admin access, no cross-tenant access."
    )
    errors: List[str] = Field(default_factory=list)


class FactoryPlatformCompanyResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    profile: FactoryPlatformCompanyProfile
    errors: List[str] = Field(default_factory=list)


class FactoryPlatformProductItem(BaseModel):
    product_id: UUID
    name: str
    sku: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    moq: Optional[int] = None
    unit_price: Optional[Decimal] = None
    currency: str = "USD"
    active: bool = True


class FactoryPlatformCatalogRecord(BaseModel):
    job_id: UUID
    source_type: str
    status: str
    created_at: Optional[datetime] = None


class FactoryPlatformProductsResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    categories: List[str] = Field(default_factory=list)
    products: List[FactoryPlatformProductItem] = Field(default_factory=list)
    products_total: int = 0
    catalog_records: List[FactoryPlatformCatalogRecord] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class FactoryPlatformBuyerReport(BaseModel):
    buyer_id: UUID
    name: str
    buyer_score: int = 0
    classification: BuyerClassification = "active_buyer"
    risk_level: RiskLevel = "low"
    annual_potential: Decimal = Decimal("0")


class FactoryPlatformDealRiskReport(BaseModel):
    deal_id: UUID
    title: str
    risk_level: DealRiskLevel
    deal_health_score: int = 0
    close_probability: float = 0.0
    revenue: Decimal = Decimal("0")


class FactoryPlatformForecastPeriod(BaseModel):
    period: str
    best_case: Decimal = Decimal("0")
    expected_case: Decimal = Decimal("0")
    worst_case: Decimal = Decimal("0")
    currency: str = "UZS"


class FactoryPlatformReportsResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    buyer_intelligence: dict[str, Any] = Field(default_factory=dict)
    top_buyers: List[FactoryPlatformBuyerReport] = Field(default_factory=list)
    deal_risk: dict[str, Any] = Field(default_factory=dict)
    high_risk_deals: List[FactoryPlatformDealRiskReport] = Field(default_factory=list)
    revenue_forecast: List[FactoryPlatformForecastPeriod] = Field(default_factory=list)
    forecast_confidence: str = "medium"
    revenue_attribution: FactoryPlatformRevenueSummary
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = "Read-only reports — no automatic CRM updates or messaging."


class FactoryPlatformInsightOpportunity(BaseModel):
    buyer_id: UUID
    name: str
    classification: str
    buyer_score: int = 0
    reason: str = ""


class FactoryPlatformInsightDealRisk(BaseModel):
    deal_id: UUID
    title: str
    risk_level: DealRiskLevel
    reason: str = ""


class FactoryPlatformRecommendedAction(BaseModel):
    action: str
    priority: str = "medium"
    source: str = "factory_platform"


class FactoryPlatformInsightsResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    buyer_opportunities: List[FactoryPlatformInsightOpportunity] = Field(default_factory=list)
    deal_risks: List[FactoryPlatformInsightDealRisk] = Field(default_factory=list)
    recommended_actions: List[FactoryPlatformRecommendedAction] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = "AI insights are read-only — no automatic actions."
