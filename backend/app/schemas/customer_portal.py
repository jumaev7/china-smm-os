"""Customer Portal v1 — factory partner read-only portal schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.buyer_intelligence import BuyerClassification, RiskLevel
from app.schemas.deal_risk import DealRiskLevel

PortalStatus = Literal["pending", "active", "suspended"]


class CustomerPortalAccountResponse(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    portal_status: PortalStatus
    owner_user: Optional[str] = None
    factory_partner_application_id: Optional[UUID] = None
    created_at: datetime


class CustomerPortalAccountListResponse(BaseModel):
    items: List[CustomerPortalAccountResponse]
    total: int


class CustomerPortalCreateAccountResponse(BaseModel):
    account: CustomerPortalAccountResponse
    message: str


class CustomerPortalRevenueSummary(BaseModel):
    total_revenue: Decimal = Decimal("0")
    deals_won: int = 0
    avg_deal_size: Decimal = Decimal("0")
    conversion_rate: float = 0.0
    currency: str = "UZS"


class CustomerPortalDashboardResponse(BaseModel):
    account: CustomerPortalAccountResponse
    active_leads: int = 0
    active_buyers: int = 0
    proposals: int = 0
    opportunities: int = 0
    revenue_summary: CustomerPortalRevenueSummary
    safety_notice: str = (
        "Read-only portal — company-scoped data only. No CRM admin, system-wide access, or automatic actions."
    )
    errors: List[str] = Field(default_factory=list)


class CustomerPortalBuyerItem(BaseModel):
    buyer_id: UUID
    name: str
    company: Optional[str] = None
    buyer_score: int
    classification: BuyerClassification
    risk_level: RiskLevel = "low"
    opportunities: int = 0
    annual_potential: Decimal = Decimal("0")
    status: str = "new"


class CustomerPortalBuyersResponse(BaseModel):
    account: CustomerPortalAccountResponse
    items: List[CustomerPortalBuyerItem]
    total: int
    errors: List[str] = Field(default_factory=list)


class CustomerPortalDealItem(BaseModel):
    deal_id: UUID
    title: str
    buyer_name: Optional[str] = None
    status: str
    deal_health_score: int
    risk_level: DealRiskLevel
    close_probability: float
    expected_close_date: Optional[datetime] = None
    revenue: Decimal = Decimal("0")
    currency: str = "UZS"


class CustomerPortalDealsResponse(BaseModel):
    account: CustomerPortalAccountResponse
    items: List[CustomerPortalDealItem]
    total: int
    errors: List[str] = Field(default_factory=list)


class CustomerPortalProposalItem(BaseModel):
    proposal_id: UUID
    title: str
    status: str
    buyer_name: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class CustomerPortalProposalsResponse(BaseModel):
    account: CustomerPortalAccountResponse
    items: List[CustomerPortalProposalItem]
    total: int
    errors: List[str] = Field(default_factory=list)


class CustomerPortalForecastPeriod(BaseModel):
    period: str
    best_case: Decimal = Decimal("0")
    expected_case: Decimal = Decimal("0")
    worst_case: Decimal = Decimal("0")
    currency: str = "UZS"


class CustomerPortalTopBuyer(BaseModel):
    buyer_id: UUID
    name: str
    buyer_score: int
    classification: str
    annual_potential: Decimal = Decimal("0")


class CustomerPortalReportsResponse(BaseModel):
    account: CustomerPortalAccountResponse
    revenue_attribution: CustomerPortalRevenueSummary
    revenue_forecast: List[CustomerPortalForecastPeriod] = Field(default_factory=list)
    forecast_confidence: str = "medium"
    top_buyers: List[CustomerPortalTopBuyer] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = (
        "Read-only reports — no automatic CRM updates, messaging, or task execution."
    )


class CustomerPortalSummaryWidget(BaseModel):
    active_accounts: int = 0
    pending_accounts: int = 0
    suspended_accounts: int = 0
    total_accounts: int = 0
    latest_company_name: Optional[str] = None


class CustomerPortalPartnerOverview(BaseModel):
    active_accounts: int = 0
    accounts: List[dict[str, Any]] = Field(default_factory=list)


class CustomerPortalBillingResponse(BaseModel):
    account: CustomerPortalAccountResponse
    billing_summary: dict[str, Any] = Field(default_factory=dict)
    safety_notice: str = (
        "Architecture only — no payment processing, card storage, or automatic charges."
    )
    errors: List[str] = Field(default_factory=list)
