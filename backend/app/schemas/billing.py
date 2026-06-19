from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

BillingStatus = Literal["active", "unpaid", "paused"]


class ClientBillingUsage(BaseModel):
    posts_created_this_cycle: int = 0
    posts_published_this_cycle: int = 0
    posts_remaining: Optional[int] = None


class ClientBillingResponse(BaseModel):
    client_id: UUID
    company_name: str
    plan_name: Optional[str] = None
    monthly_fee: Optional[float] = None
    monthly_post_limit: Optional[int] = None
    billing_status: BillingStatus = "active"
    billing_cycle_start: Optional[datetime] = None
    billing_cycle_end: Optional[datetime] = None
    usage: ClientBillingUsage
    near_limit: bool = False


class ClientBillingUpdate(BaseModel):
    plan_name: Optional[str] = Field(None, max_length=100)
    monthly_fee: Optional[float] = Field(None, ge=0)
    monthly_post_limit: Optional[int] = Field(None, ge=0)
    billing_status: Optional[BillingStatus] = None
    billing_cycle_start: Optional[datetime] = None
    billing_cycle_end: Optional[datetime] = None


class BillingOverviewClientUsage(BaseModel):
    client_id: UUID
    company_name: str
    plan_name: Optional[str] = None
    billing_status: BillingStatus
    monthly_post_limit: Optional[int] = None
    posts_created_this_cycle: int
    posts_published_this_cycle: int
    posts_remaining: Optional[int] = None
    near_limit: bool = False


class BillingOverviewResponse(BaseModel):
    active_clients: int
    unpaid_clients: int
    monthly_recurring_revenue: float
    total_posts_used: int
    clients_near_limit: list[BillingOverviewClientUsage]
    usage_by_client: list[BillingOverviewClientUsage]
