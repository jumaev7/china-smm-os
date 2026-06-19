"""Tenant Authentication v1 — auth API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

TenantUserRole = Literal["owner", "manager", "sales", "operator", "viewer"]
TenantUserStatus = Literal["invited", "active", "suspended", "removed"]


class AuthLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=4, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class AuthRefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class AuthTenantSummary(BaseModel):
    id: UUID
    company_name: str
    status: str
    plan: Optional[str] = None


class AuthUserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    role: TenantUserRole
    status: TenantUserStatus
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    has_password: bool = False
    permissions: List[str] = Field(default_factory=list)


class AuthLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AuthUserResponse
    tenant: AuthTenantSummary


class AuthRefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthMeResponse(BaseModel):
    user: AuthUserResponse
    tenant: AuthTenantSummary
    permissions: List[str]
    roles_available: List[TenantUserRole]


class AuthLogoutResponse(BaseModel):
    message: str


class AuthDemoUserResponse(BaseModel):
    message: str
    email: str
    password: str
    tenant_id: str
    company_name: str
    user_id: str
