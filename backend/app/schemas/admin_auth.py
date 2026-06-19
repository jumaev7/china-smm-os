"""Admin Authentication & RBAC v1 — auth API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

AdminRole = Literal["super_admin", "platform_admin", "support_admin", "auditor"]
AdminUserStatus = Literal["invited", "active", "suspended", "removed"]
AdminSessionStatus = Literal["active", "revoked", "expired"]


class AdminAuthLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=4, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class AdminAuthRefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class AdminUserResponse(BaseModel):
    id: UUID
    email: str
    role: AdminRole
    status: AdminUserStatus
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    has_password: bool = False
    permissions: List[str] = Field(default_factory=list)


class AdminAuthLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AdminUserResponse
    session_id: UUID


class AdminAuthRefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    session_id: UUID


class AdminAuthMeResponse(BaseModel):
    user: AdminUserResponse
    permissions: List[str]
    roles_available: List[AdminRole]
    role_permissions: dict[str, List[str]]


class AdminAuthLogoutResponse(BaseModel):
    message: str


class AdminBootstrapResponse(BaseModel):
    message: str
    email: str
    user_id: str
    created: bool
    reset: bool = False
