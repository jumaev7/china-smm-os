from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

SubscriptionStatus = Literal["trial", "active", "suspended", "expired", "cancelled"]
BillingCycle = Literal["monthly", "yearly"]
InvoiceStatus = Literal["draft", "unpaid", "paid", "cancelled"]


class PlanResponse(BaseModel):
    id: UUID
    name: str
    code: str
    monthly_price: float
    yearly_price: float
    max_users: Optional[int] = None
    max_leads: Optional[int] = None
    max_buyers: Optional[int] = None
    max_deals: Optional[int] = None
    features: Optional[list[str]] = None
    created_at: datetime


class PlanListResponse(BaseModel):
    items: list[PlanResponse]
    total: int


class SubscriptionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    plan_id: UUID
    plan_name: Optional[str] = None
    plan_code: Optional[str] = None
    status: SubscriptionStatus
    billing_cycle: BillingCycle
    starts_at: datetime
    expires_at: Optional[datetime] = None
    created_at: datetime


class SubscriptionListResponse(BaseModel):
    items: list[SubscriptionResponse]
    total: int


class InvoiceResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    subscription_id: UUID
    amount: float
    currency: str
    status: InvoiceStatus
    invoice_date: datetime
    due_date: datetime


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    total: int


class UsageMetric(BaseModel):
    current: int
    limit: Optional[int] = None
    utilization_pct: Optional[float] = None


class UsageSummaryResponse(BaseModel):
    tenant_id: UUID
    users: UsageMetric
    leads: UsageMetric
    buyers: UsageMetric
    deals: UsageMetric


class BillingSummaryResponse(BaseModel):
    plan: Optional[PlanResponse] = None
    status: Optional[SubscriptionStatus] = None
    next_renewal: Optional[datetime] = None
    monthly_price: Optional[float] = None
    usage_summary: UsageSummaryResponse


class CreateSubscriptionRequest(BaseModel):
    tenant_id: UUID
    plan_code: str = Field(..., min_length=1, max_length=50)
    billing_cycle: BillingCycle = "monthly"
    status: SubscriptionStatus = "trial"


class SubscriptionActionRequest(BaseModel):
    subscription_id: UUID


class SubscriptionSummaryWidget(BaseModel):
    mrr: float
    active_subscriptions: int
    trial_subscriptions: int
    plan_distribution: dict[str, int]
    tenants_near_limit: int


class ExecutiveBillingOverview(BaseModel):
    mrr: float
    active_subscriptions: int
    trial_subscriptions: int
    plan_distribution: dict[str, int]
