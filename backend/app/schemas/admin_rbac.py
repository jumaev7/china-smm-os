"""Admin Authentication & RBAC v1 — RBAC management schemas."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.admin_auth import AdminRole, AdminSessionStatus, AdminUserResponse, AdminUserStatus


class AdminUserCreateRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: AdminRole = "auditor"
    password: str | None = Field(None, min_length=8, max_length=128)
    status: AdminUserStatus = "active"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class AdminUserUpdateRequest(BaseModel):
    email: str | None = Field(None, min_length=3, max_length=255)
    role: AdminRole | None = None
    password: str | None = Field(None, min_length=8, max_length=128)
    status: AdminUserStatus | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip().lower()


class AdminUserListResponse(BaseModel):
    items: List[AdminUserResponse]
    total: int
    roles_available: List[AdminRole]
    role_permissions: dict[str, List[str]]


class AdminRolesResponse(BaseModel):
    roles: List[AdminRole]
    role_permissions: dict[str, List[str]]


class AdminPermissionsResponse(BaseModel):
    permissions: List[str]
    role_permissions: dict[str, List[str]]


class AdminSessionResponse(BaseModel):
    id: UUID
    admin_user_id: UUID
    admin_email: str
    admin_role: AdminRole
    login_time: datetime
    last_activity: datetime
    session_status: AdminSessionStatus
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AdminSessionListResponse(BaseModel):
    items: List[AdminSessionResponse]
    total: int


class AdminAuditLogResponse(BaseModel):
    id: UUID
    admin_user_id: Optional[UUID] = None
    admin_email: Optional[str] = None
    event_type: str
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None
    success: bool
    created_at: datetime


class AdminAuditLogListResponse(BaseModel):
    items: List[AdminAuditLogResponse]
    total: int


class AdminPlatformTenantsResponse(BaseModel):
    items: list[dict]
    total: int


class AdminPlatformBillingResponse(BaseModel):
    total_tenants: int
    active_subscriptions: int
    trial_subscriptions: int
    plans: list[dict]


class AdminPlatformAnalyticsResponse(BaseModel):
    total_tenants: int
    active_tenants: int
    total_clients: int
    total_leads: int
    total_deals: int
    executive_copilot_available: bool


class AdminSecurityCheck(BaseModel):
    name: str
    status: Literal["ok", "warning", "error"]
    message: str


class AdminSecurityChecksResponse(BaseModel):
    checks: List[AdminSecurityCheck]
    ok_count: int
    total: int


class AdminSecurityStatusResponse(BaseModel):
    protected_routes: List[str]
    protected_route_count: int
    open_routes: List[str]
    open_route_count: int
    permission_route_matrix: dict[str, List[str]]
    permission_coverage_percent: float
    unmapped_permissions: List[str]
    session_invalidation: dict
    jwt_separation: dict
    bootstrap: dict
    login_protection: dict
    security_checks: AdminSecurityChecksResponse
    readiness_score: int
    implementation_complete: bool
