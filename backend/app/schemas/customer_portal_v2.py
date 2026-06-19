"""Customer Portal v2 — tenant-scoped partner workspace schemas (read-only)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.deal_risk import DealRiskLevel

OpportunitySource = Literal["buyer_acquisition", "marketplace", "buyer_network"]
PortalV2SubscriptionStatus = Literal["trial", "active", "suspended", "cancelled", "expired"] | None


class CustomerPortalV2TenantRef(BaseModel):
    tenant_id: UUID
    company_id: UUID
    company_name: str
    tenant_status: str


class CustomerPortalV2RevenueSummary(BaseModel):
    total_revenue: Decimal = Decimal("0")
    deals_won: int = 0
    avg_deal_size: Decimal = Decimal("0")
    conversion_rate: float = 0.0
    currency: str = "UZS"


class CustomerPortalV2DashboardResponse(BaseModel):
    tenant: CustomerPortalV2TenantRef
    subscription_status: Optional[str] = None
    current_plan: Optional[str] = None
    active_buyers: int = 0
    active_opportunities: int = 0
    open_deals: int = 0
    proposals: int = 0
    revenue_summary: CustomerPortalV2RevenueSummary
    profile_completeness: int = 0
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = (
        "Read-only partner workspace — tenant-scoped only. No messaging, CRM writes, or autonomous actions."
    )


class CustomerPortalV2OpportunityItem(BaseModel):
    opportunity_id: str
    title: str
    source: OpportunitySource
    buyer_company: Optional[str] = None
    opportunity_score: int = 0
    country: Optional[str] = None
    industry: Optional[str] = None
    recommended_action: str


class CustomerPortalV2OpportunitiesResponse(BaseModel):
    tenant: CustomerPortalV2TenantRef
    buyer_acquisition: List[CustomerPortalV2OpportunityItem] = Field(default_factory=list)
    marketplace: List[CustomerPortalV2OpportunityItem] = Field(default_factory=list)
    buyer_network: List[CustomerPortalV2OpportunityItem] = Field(default_factory=list)
    total: int = 0
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class CustomerPortalV2DealItem(BaseModel):
    deal_id: UUID
    deal_name: str
    buyer: Optional[str] = None
    stage: str
    risk_level: DealRiskLevel
    close_probability: float
    estimated_value: Decimal = Decimal("0")
    currency: str = "UZS"


class CustomerPortalV2DealsResponse(BaseModel):
    tenant: CustomerPortalV2TenantRef
    items: List[CustomerPortalV2DealItem]
    total: int
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class CustomerPortalV2ProposalItem(BaseModel):
    proposal_id: UUID
    proposal_title: str
    buyer: Optional[str] = None
    status: str
    estimated_value: Decimal = Decimal("0")
    last_updated: datetime


class CustomerPortalV2ProposalsResponse(BaseModel):
    tenant: CustomerPortalV2TenantRef
    items: List[CustomerPortalV2ProposalItem]
    total: int
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class CustomerPortalV2ForecastPeriod(BaseModel):
    period: Optional[str] = None
    best_case: Decimal = Decimal("0")
    expected_case: Decimal = Decimal("0")
    worst_case: Decimal = Decimal("0")
    currency: str = "UZS"


class CustomerPortalV2BuyerPerformance(BaseModel):
    buyer_id: Optional[UUID] = None
    name: str
    buyer_score: int = 0
    classification: Optional[str] = None
    annual_potential: Decimal = Decimal("0")


class CustomerPortalV2MarketplacePerformance(BaseModel):
    open_opportunities: int = 0
    total_opportunities: int = 0
    visibility_score: int = 0


class CustomerPortalV2ReportsResponse(BaseModel):
    tenant: CustomerPortalV2TenantRef
    revenue_forecast: List[CustomerPortalV2ForecastPeriod] = Field(default_factory=list)
    forecast_confidence: str = "medium"
    revenue_attribution: CustomerPortalV2RevenueSummary
    buyer_performance: List[CustomerPortalV2BuyerPerformance] = Field(default_factory=list)
    marketplace_performance: CustomerPortalV2MarketplacePerformance
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class CustomerPortalV2InvoiceSummaryItem(BaseModel):
    invoice_id: UUID
    invoice_number: Optional[str] = None
    status: str
    amount: Decimal = Decimal("0")
    currency: str = "UZS"
    invoice_date: Optional[datetime] = None


class CustomerPortalV2BillingResponse(BaseModel):
    tenant: CustomerPortalV2TenantRef
    current_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    usage_summary: dict[str, Any] = Field(default_factory=dict)
    invoice_summary: List[CustomerPortalV2InvoiceSummaryItem] = Field(default_factory=list)
    monthly_price: float = 0.0
    next_renewal: Optional[datetime] = None
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class CustomerPortalV2ExportMarketItem(BaseModel):
    country: str
    market_score: int = 0
    active_buyers: int = 0
    opportunities: int = 0


class CustomerPortalV2FactorySnapshotResponse(BaseModel):
    tenant: CustomerPortalV2TenantRef
    company_profile: dict[str, Any] = Field(default_factory=dict)
    products_count: int = 0
    certificates_count: int = 0
    export_markets: List[CustomerPortalV2ExportMarketItem] = Field(default_factory=list)
    verification_status: str = "unverified"
    profile_score: int = 0
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class CustomerPortalV2SummaryWidget(BaseModel):
    active_buyers: int = 0
    open_deals: int = 0
    active_opportunities: int = 0
    profile_completeness: int = 0
    subscription_status: Optional[str] = None
    company_name: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class CustomerPortalV2HealthOverview(BaseModel):
    active_buyers: int = 0
    open_deals: int = 0
    active_opportunities: int = 0
    profile_completeness: int = 0
    subscription_status: Optional[str] = None
    company_name: Optional[str] = None
    readiness: str = "needs_attention"
    errors: List[str] = Field(default_factory=list)
    safety_notice: str
