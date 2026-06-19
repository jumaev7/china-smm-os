"""Multi-Tenant SaaS Foundation v1 — tenant API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

TenantStatus = Literal["pending", "active", "suspended", "archived"]
TenantPlan = Literal["starter", "growth", "enterprise", "trial"]
TenantUserRole = Literal["owner", "manager", "sales", "operator", "viewer"]
TenantUserStatus = Literal["invited", "active", "suspended", "removed"]


class TenantUserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    role: TenantUserRole
    status: TenantUserStatus
    created_at: datetime
    permissions: List[str] = Field(default_factory=list)


class TenantResponse(BaseModel):
    id: UUID
    company_name: str
    status: TenantStatus
    plan: TenantPlan
    factory_partner_application_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class TenantListResponse(BaseModel):
    items: List[TenantResponse]
    total: int


class TenantCreateRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    status: TenantStatus = "active"
    plan: TenantPlan = "starter"
    factory_partner_application_id: Optional[UUID] = None
    owner_email: Optional[str] = Field(
        None,
        description="Optional initial owner user email",
    )


class TenantUpdateRequest(BaseModel):
    company_name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[TenantStatus] = None
    plan: Optional[TenantPlan] = None


class TenantPortalStatus(BaseModel):
    has_portal_account: bool = False
    portal_account_id: Optional[UUID] = None
    portal_status: Optional[str] = None
    company_id: Optional[UUID] = None


class TenantUsageSummary(BaseModel):
    client_count: int = 0
    active_users: int = 0
    crm_leads: int = 0
    crm_deals: int = 0
    portal_accounts: int = 0


class TenantDashboardResponse(BaseModel):
    tenant: TenantResponse
    users: List[TenantUserResponse]
    portal_status: TenantPortalStatus
    usage_summary: TenantUsageSummary
    subscription_overview: Optional[dict[str, Any]] = None
    roles_available: List[TenantUserRole]
    safety_notice: str = (
        "Strict tenant isolation — each company accesses only its own data. "
        "No cross-company access or automatic permission escalation."
    )


class TenantUserCreateRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: TenantUserRole = "viewer"
    status: TenantUserStatus = "active"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class TenantUserListResponse(BaseModel):
    tenant_id: UUID
    items: List[TenantUserResponse]
    total: int


class TenantCreateResponse(BaseModel):
    tenant: TenantResponse
    owner_user: Optional[TenantUserResponse] = None
    message: str


class TenantIsolationCheckResponse(BaseModel):
    tenant_id: UUID
    isolated: bool
    client_ids: List[UUID]
    cross_tenant_leak: bool = False
    message: str
