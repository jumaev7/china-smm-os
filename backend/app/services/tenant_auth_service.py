"""Tenant Authentication & Access Control v1 — login, session, user management."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.core.tenant_permissions import (
    TENANT_USER_ROLES,
    can_assign_role,
    permissions_for_role,
    role_has_permission,
)
from app.models.customer_portal_account import CustomerPortalAccount
from app.models.tenant import TENANT_USER_STATUSES, Tenant, TenantUser
from app.services.auth_service import (
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    create_refresh_token_value,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[TenantAuth]"

DEMO_TENANT_NAME = "Demo Factory Co."
DEMO_USER_EMAIL = "demo@factory.local"
DEMO_USER_PASSWORD = "demo1234"


@dataclass
class CurrentTenantUser:
    id: UUID
    tenant_id: UUID
    email: str
    role: str
    status: str
    permissions: list[str]

    def has_permission(self, permission: str) -> bool:
        return role_has_permission(self.role, permission)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_user(u: TenantUser, *, include_permissions: bool = True) -> dict[str, Any]:
    data = {
        "id": u.id,
        "tenant_id": u.tenant_id,
        "email": u.email,
        "role": u.role,
        "status": u.status,
        "created_at": u.created_at,
        "updated_at": u.updated_at,
        "last_login_at": u.last_login_at,
        "has_password": bool(u.password_hash),
    }
    if include_permissions:
        data["permissions"] = permissions_for_role(u.role)
    return data


class TenantAuthService:
    """Tenant user authentication and RBAC — no cross-tenant access."""

    @staticmethod
    async def load_user_by_id(db: AsyncSession, user_id: UUID) -> TenantUser | None:
        return await db.get(TenantUser, user_id)

    @staticmethod
    async def load_user_by_email(db: AsyncSession, email: str) -> TenantUser | None:
        email_norm = email.strip().lower()
        result = await db.execute(
            select(TenantUser).where(func.lower(TenantUser.email) == email_norm),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def resolve_current_user(db: AsyncSession, user_id: UUID) -> CurrentTenantUser:
        user = await TenantAuthService.load_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if user.status != "active":
            raise HTTPException(status_code=403, detail=f"User account is {user.status}")
        await TenantService.validate_tenant_active(db, user.tenant_id)
        return CurrentTenantUser(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=user.role,
            status=user.status,
            permissions=permissions_for_role(user.role),
        )

    @staticmethod
    def assert_tenant_access(user: CurrentTenantUser, tenant_id: UUID) -> None:
        if user.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Cross-tenant access denied — tenant isolation enforced",
            )

    @staticmethod
    def assert_role(user: CurrentTenantUser, *roles: str) -> None:
        if user.role not in roles and not user.has_permission("tenant.full"):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user.role}' is not allowed for this action",
            )

    @staticmethod
    def assert_permission(user: CurrentTenantUser, permission: str) -> None:
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=403,
                detail=f"Missing permission: {permission}",
            )

    @staticmethod
    async def validate_portal_account_access(
        db: AsyncSession,
        user: CurrentTenantUser,
        portal_account_id: UUID,
    ) -> CustomerPortalAccount:
        TenantAuthService.assert_permission(user, "tenant.read")
        result = await db.execute(
            select(CustomerPortalAccount).where(CustomerPortalAccount.id == portal_account_id),
        )
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=404, detail="Portal account not found")
        if account.tenant_id and account.tenant_id != user.tenant_id:
            raise HTTPException(status_code=403, detail="Portal account belongs to another tenant")
        if not account.tenant_id:
            client_ids = await TenantService.get_client_ids_for_tenant(db, user.tenant_id)
            if account.company_id not in client_ids:
                raise HTTPException(status_code=403, detail="Portal account not in your tenant scope")
        return account

    @staticmethod
    async def login(
        db: AsyncSession,
        *,
        email: str,
        password: str,
    ) -> dict[str, Any]:
        email_norm = email.strip().lower()
        user = await TenantAuthService.load_user_by_email(db, email)
        if not user:
            logger.warning(
                "%s login failed: email=%s user_exists=false",
                MARKER,
                email_norm,
            )
            raise HTTPException(status_code=401, detail="Invalid email or password")

        tenant = await TenantService.get_tenant(db, user.tenant_id, required=False)
        tenant_status = tenant.status if tenant else "missing"

        if not verify_password(password, user.password_hash):
            logger.warning(
                "%s login failed: email=%s user_exists=true status=%s tenant_status=%s password_hash_present=%s",
                MARKER,
                email_norm,
                user.status,
                tenant_status,
                bool(user.password_hash),
            )
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if user.status != "active":
            logger.warning(
                "%s login failed: email=%s user_exists=true status=%s tenant_status=%s password_hash_present=%s reason=inactive_user",
                MARKER,
                email_norm,
                user.status,
                tenant_status,
                bool(user.password_hash),
            )
            raise HTTPException(status_code=403, detail=f"User account is {user.status}")

        await TenantService.validate_tenant_active(db, user.tenant_id)

        access_token = create_access_token(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=user.role,
        )
        refresh_value = create_refresh_token_value()
        user.refresh_token_hash = hash_refresh_token(refresh_value)
        user.last_login_at = _utc_now()
        user.updated_at = _utc_now()
        await db.commit()

        tenant = await TenantService.get_tenant(db, user.tenant_id)
        logger.info("%s login: user=%s tenant=%s", MARKER, user.email, user.tenant_id)
        try:
            from app.services.platform_audit_service import PlatformAuditService
            await PlatformAuditService.record(
                db,
                actor_type="tenant",
                actor_id=user.id,
                tenant_id=user.tenant_id,
                event_type="login",
                resource_type="tenant_user",
                resource_id=str(user.id),
                details={"email": user.email},
            )
        except Exception:
            logger.warning("%s audit log failed on login", MARKER, exc_info=True)
        return {
            "access_token": access_token,
            "refresh_token": refresh_value,
            "token_type": "bearer",
            "user": _serialize_user(user),
            "tenant": {
                "id": tenant.id if tenant else user.tenant_id,
                "company_name": tenant.company_name if tenant else "",
                "status": tenant.status if tenant else "active",
            },
        }

    @staticmethod
    async def logout(db: AsyncSession, user: CurrentTenantUser) -> dict[str, str]:
        row = await TenantAuthService.load_user_by_id(db, user.id)
        if row:
            row.refresh_token_hash = None
            row.updated_at = _utc_now()
            await db.commit()
        try:
            from app.services.platform_audit_service import PlatformAuditService
            await PlatformAuditService.record(
                db,
                actor_type="tenant",
                actor_id=user.id,
                tenant_id=user.tenant_id,
                event_type="logout",
                resource_type="tenant_user",
                resource_id=str(user.id),
            )
        except Exception:
            logger.warning("%s audit log failed on logout", MARKER, exc_info=True)
        return {"message": "Logged out"}

    @staticmethod
    async def refresh_session(db: AsyncSession, refresh_token: str) -> dict[str, Any]:
        payload = decode_token(refresh_token, expected_type=TOKEN_TYPE_REFRESH)
        user_id = UUID(payload["sub"])
        user = await TenantAuthService.load_user_by_id(db, user_id)
        if not user or user.status != "active":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        if not user.refresh_token_hash:
            raise HTTPException(status_code=401, detail="Refresh token revoked")
        if user.refresh_token_hash != hash_refresh_token(refresh_token):
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        await TenantService.validate_tenant_active(db, user.tenant_id)

        access_token = create_access_token(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=user.role,
        )
        new_refresh = create_refresh_token_value()
        user.refresh_token_hash = hash_refresh_token(new_refresh)
        user.updated_at = _utc_now()
        await db.commit()

        return {
            "access_token": access_token,
            "refresh_token": new_refresh,
            "token_type": "bearer",
        }

    @staticmethod
    async def me(db: AsyncSession, user: CurrentTenantUser) -> dict[str, Any]:
        tenant = await TenantService.get_tenant(db, user.tenant_id)
        row = await TenantAuthService.load_user_by_id(db, user.id)
        return {
            "user": _serialize_user(row) if row else {
                "id": user.id,
                "tenant_id": user.tenant_id,
                "email": user.email,
                "role": user.role,
                "status": user.status,
                "permissions": user.permissions,
            },
            "tenant": {
                "id": tenant.id if tenant else user.tenant_id,
                "company_name": tenant.company_name if tenant else "",
                "status": tenant.status if tenant else "active",
                "plan": tenant.plan if tenant else "starter",
            },
            "permissions": user.permissions,
            "roles_available": sorted(TENANT_USER_ROLES),
        }

    @staticmethod
    async def create_demo_user(db: AsyncSession) -> dict[str, Any]:
        if settings.APP_ENV not in ("development", "test"):
            raise HTTPException(status_code=403, detail="Demo user creation is disabled outside development")

        existing = await TenantAuthService.load_user_by_email(db, DEMO_USER_EMAIL)
        if existing:
            existing.password_hash = hash_password(DEMO_USER_PASSWORD)
            existing.status = "active"
            existing.role = "owner"
            existing.updated_at = _utc_now()
            tenant = await TenantService.get_tenant(db, existing.tenant_id, required=False)
            if tenant:
                tenant.status = "active"
                tenant.updated_at = _utc_now()
            await db.commit()
            logger.info("%s demo user reset: %s", MARKER, DEMO_USER_EMAIL)
            from app.services.demo_tenant_seed_service import ensure_demo_tenant_data
            await ensure_demo_tenant_data(db, existing.tenant_id)
            return {
                "message": "Demo user reset",
                "email": DEMO_USER_EMAIL,
                "password": DEMO_USER_PASSWORD,
                "tenant_id": str(existing.tenant_id),
                "company_name": tenant.company_name if tenant else DEMO_TENANT_NAME,
                "user_id": str(existing.id),
            }

        result = await TenantService.create_tenant(
            db,
            company_name=DEMO_TENANT_NAME,
            status="active",
            plan="trial",
            owner_email=DEMO_USER_EMAIL,
        )
        owner = result.get("owner_user")
        if not owner:
            raise HTTPException(status_code=500, detail="Failed to create demo owner user")

        user = await TenantAuthService.load_user_by_id(db, owner["id"])
        if not user:
            raise HTTPException(status_code=500, detail="Demo user record missing")
        user.password_hash = hash_password(DEMO_USER_PASSWORD)
        user.status = "active"
        user.updated_at = _utc_now()
        await db.commit()

        logger.info("%s demo user created: %s", MARKER, DEMO_USER_EMAIL)
        from app.services.demo_tenant_seed_service import ensure_demo_tenant_data
        await ensure_demo_tenant_data(db, user.tenant_id)
        return {
            "message": "Demo tenant user created",
            "email": DEMO_USER_EMAIL,
            "password": DEMO_USER_PASSWORD,
            "tenant_id": str(user.tenant_id),
            "company_name": DEMO_TENANT_NAME,
            "user_id": str(user.id),
        }

    @staticmethod
    async def list_users(
        db: AsyncSession,
        user: CurrentTenantUser,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        TenantAuthService.assert_permission(user, "users.manage")
        result = await TenantService.list_users(db, user.tenant_id, skip=skip, limit=limit)
        return {
            **result,
            "roles_available": sorted(TENANT_USER_ROLES),
            "role_permissions": {
                role: permissions_for_role(role) for role in sorted(TENANT_USER_ROLES)
            },
        }

    @staticmethod
    async def create_user(
        db: AsyncSession,
        actor: CurrentTenantUser,
        *,
        email: str,
        role: str,
        password: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        TenantAuthService.assert_permission(actor, "users.manage")
        if not can_assign_role(actor.role, role):
            raise HTTPException(status_code=403, detail="Cannot assign role — no permission escalation")
        if role == "owner":
            raise HTTPException(status_code=400, detail="Cannot create additional owner via API")

        created = await TenantService.add_tenant_user(
            db,
            actor.tenant_id,
            email=email,
            role=role,
            status=status,
        )
        if password:
            row = await TenantAuthService.load_user_by_id(db, created["id"])
            if row:
                row.password_hash = hash_password(password)
                row.updated_at = _utc_now()
                await db.commit()
                created = _serialize_user(row)
        try:
            from app.services.platform_audit_service import PlatformAuditService
            await PlatformAuditService.record(
                db,
                actor_type="tenant",
                actor_id=actor.id,
                tenant_id=actor.tenant_id,
                event_type="user_creation",
                resource_type="tenant_user",
                resource_id=str(created["id"]),
                details={"email": email, "role": role},
            )
        except Exception:
            logger.warning("%s audit log failed on user creation", MARKER, exc_info=True)
        return created

    @staticmethod
    async def update_user(
        db: AsyncSession,
        actor: CurrentTenantUser,
        user_id: UUID,
        *,
        role: str | None = None,
        email: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        TenantAuthService.assert_permission(actor, "users.manage")
        row = await TenantAuthService.load_user_by_id(db, user_id)
        if not row or row.tenant_id != actor.tenant_id:
            raise HTTPException(status_code=404, detail="User not found")

        if role is not None:
            if role == "owner" and row.role != "owner":
                raise HTTPException(status_code=403, detail="Cannot promote user to owner")
            if not can_assign_role(actor.role, role):
                raise HTTPException(status_code=403, detail="Cannot assign role — no permission escalation")
            if role not in TENANT_USER_ROLES:
                raise HTTPException(status_code=400, detail="Invalid role")
            row.role = role

        if email is not None:
            email_norm = email.strip().lower()
            dup = await db.execute(
                select(TenantUser).where(
                    TenantUser.tenant_id == actor.tenant_id,
                    func.lower(TenantUser.email) == email_norm,
                    TenantUser.id != user_id,
                ),
            )
            if dup.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email already in use")
            row.email = email_norm

        if password:
            row.password_hash = hash_password(password)

        row.updated_at = _utc_now()
        await db.commit()
        await db.refresh(row)
        return _serialize_user(row)

    @staticmethod
    async def set_user_status(
        db: AsyncSession,
        actor: CurrentTenantUser,
        user_id: UUID,
        *,
        status: str,
    ) -> dict[str, Any]:
        TenantAuthService.assert_permission(actor, "users.manage")
        if status not in TENANT_USER_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        row = await TenantAuthService.load_user_by_id(db, user_id)
        if not row or row.tenant_id != actor.tenant_id:
            raise HTTPException(status_code=404, detail="User not found")
        if row.role == "owner" and status != "active":
            raise HTTPException(status_code=400, detail="Cannot disable tenant owner")
        if row.id == actor.id and status != "active":
            raise HTTPException(status_code=400, detail="Cannot disable your own account")

        row.status = status
        if status != "active":
            row.refresh_token_hash = None
        row.updated_at = _utc_now()
        await db.commit()
        await db.refresh(row)
        return _serialize_user(row)
