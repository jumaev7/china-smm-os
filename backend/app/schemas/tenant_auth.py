"""Tenant Authentication v1 — tenant user management schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import AuthUserResponse, TenantUserRole, TenantUserStatus


class TenantAuthUserCreateRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: TenantUserRole = "viewer"
    password: Optional[str] = Field(None, min_length=4, max_length=128)
    status: TenantUserStatus = "active"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class TenantAuthUserUpdateRequest(BaseModel):
    email: Optional[str] = Field(None, min_length=3, max_length=255)
    role: Optional[TenantUserRole] = None
    password: Optional[str] = Field(None, min_length=4, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip().lower()


class TenantAuthUserListResponse(BaseModel):
    tenant_id: UUID
    items: List[AuthUserResponse]
    total: int
    roles_available: List[TenantUserRole]
    role_permissions: Dict[str, List[str]]


class TenantAuthUserActionResponse(BaseModel):
    user: AuthUserResponse
    message: str = "OK"
