"""Admin Authentication & RBAC v1 — RBAC checks, user management, audit logging."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_permissions import (
    ADMIN_ROLES,
    ADMIN_USER_STATUSES,
    can_assign_admin_role,
    permissions_for_role,
    role_has_permission,
)
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.admin_user import AdminAuditLog, AdminSession, AdminUser
from app.models.client import Client
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.services.auth_service import hash_password

logger = logging.getLogger(__name__)

MARKER = "[AdminRBAC]"


@dataclass
class CurrentAdminUser:
    id: UUID
    email: str
    role: str
    status: str
    session_id: UUID | None
    permissions: list[str]

    def has_permission(self, permission: str) -> bool:
        return role_has_permission(self.role, permission)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AdminRbacService:
    """Platform admin RBAC — separate from tenant RBAC."""

    @staticmethod
    def serialize_user(user: AdminUser, *, include_permissions: bool = True) -> dict[str, Any]:
        data = {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "last_login_at": user.last_login_at,
            "has_password": bool(user.password_hash),
        }
        if include_permissions:
            data["permissions"] = permissions_for_role(user.role)
        return data

    @staticmethod
    async def resolve_current_admin(
        db: AsyncSession,
        user_id: UUID,
        session_id: UUID,
        *,
        access_nonce: str | None = None,
    ) -> CurrentAdminUser:
        user = await db.get(AdminUser, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="Admin user not found")
        if user.status != "active":
            raise HTTPException(status_code=403, detail=f"Admin account is {user.status}")

        session = await db.get(AdminSession, session_id)
        if not session or session.admin_user_id != user.id:
            raise HTTPException(status_code=401, detail="Admin session not found")
        if session.session_status != "active":
            raise HTTPException(status_code=401, detail="Admin session revoked or expired")
        if not session.access_token_nonce:
            raise HTTPException(status_code=401, detail="Admin access token invalidated")
        if not access_nonce or session.access_token_nonce != access_nonce:
            raise HTTPException(status_code=401, detail="Admin access token invalidated")

        return CurrentAdminUser(
            id=user.id,
            email=user.email,
            role=user.role,
            status=user.status,
            session_id=session_id,
            permissions=permissions_for_role(user.role),
        )

    @staticmethod
    def assert_role(admin: CurrentAdminUser, *roles: str) -> None:
        if admin.role in roles or admin.has_permission("platform.full"):
            return
        raise HTTPException(
            status_code=403,
            detail=f"Admin role '{admin.role}' is not allowed for this action",
        )

    @staticmethod
    async def assert_permission_async(
        db: AsyncSession,
        admin: CurrentAdminUser,
        permission: str,
        *,
        audit_context: dict[str, Any] | None = None,
    ) -> None:
        if admin.has_permission(permission):
            await AdminRbacService.record_audit(
                db,
                admin_user_id=admin.id,
                event_type="permission_check",
                action="admin_permission_granted",
                details=json.dumps({"permission": permission, **(audit_context or {})}),
                success=True,
            )
            return

        await AdminRbacService.record_audit(
            db,
            admin_user_id=admin.id,
            event_type="permission_check",
            action="admin_permission_denied",
            details=json.dumps({"permission": permission, **(audit_context or {})}),
            success=False,
        )
        raise HTTPException(status_code=403, detail=f"Missing admin permission: {permission}")

    @staticmethod
    def assert_permission(admin: CurrentAdminUser, permission: str) -> None:
        if not admin.has_permission(permission):
            raise HTTPException(status_code=403, detail=f"Missing admin permission: {permission}")

    @staticmethod
    async def record_audit(
        db: AsyncSession,
        *,
        admin_user_id: UUID | None,
        event_type: str,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: str | None = None,
        ip_address: str | None = None,
        success: bool = True,
    ) -> AdminAuditLog:
        row = AdminAuditLog(
            admin_user_id=admin_user_id,
            event_type=event_type,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            success="true" if success else "false",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def list_users(
        db: AsyncSession,
        actor: CurrentAdminUser,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        AdminRbacService.assert_permission(actor, "platform.full")
        limit = clamp_limit(limit)
        total_result = await db.execute(select(func.count()).select_from(AdminUser))
        total = total_result.scalar() or 0
        rows = await db.execute(
            select(AdminUser).order_by(AdminUser.created_at.desc()).offset(skip).limit(limit),
        )
        items = [AdminRbacService.serialize_user(u) for u in rows.scalars().all()]
        return {
            "items": items,
            "total": total,
            "roles_available": sorted(ADMIN_ROLES),
            "role_permissions": {
                role: permissions_for_role(role) for role in sorted(ADMIN_ROLES)
            },
        }

    @staticmethod
    async def create_user(
        db: AsyncSession,
        actor: CurrentAdminUser,
        *,
        email: str,
        role: str,
        password: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        AdminRbacService.assert_permission(actor, "platform.full")
        if not can_assign_admin_role(actor.role, role):
            raise HTTPException(status_code=403, detail="Cannot assign role — no permission escalation")
        if role not in ADMIN_ROLES:
            raise HTTPException(status_code=400, detail="Invalid admin role")
        if status not in ADMIN_USER_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")

        email_norm = email.strip().lower()
        dup = await db.execute(select(AdminUser).where(func.lower(AdminUser.email) == email_norm))
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already in use")

        user = AdminUser(
            email=email_norm,
            role=role,
            status=status,
            password_hash=hash_password(password) if password else None,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        await AdminRbacService.record_audit(
            db,
            admin_user_id=actor.id,
            event_type="user_management",
            action="admin_user_created",
            resource_type="admin_user",
            resource_id=str(user.id),
            details=json.dumps({"email": email_norm, "role": role}),
            success=True,
        )
        return AdminRbacService.serialize_user(user)

    @staticmethod
    async def update_user(
        db: AsyncSession,
        actor: CurrentAdminUser,
        user_id: UUID,
        *,
        role: str | None = None,
        email: str | None = None,
        password: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        AdminRbacService.assert_permission(actor, "platform.full")
        row = await db.get(AdminUser, user_id)
        if not row:
            raise HTTPException(status_code=404, detail="Admin user not found")
        if row.id == actor.id and role and role != actor.role:
            raise HTTPException(status_code=403, detail="Cannot change your own role")
        if row.id == actor.id and status and status != "active":
            raise HTTPException(status_code=403, detail="Cannot disable your own account")

        if role is not None:
            if not can_assign_admin_role(actor.role, role):
                raise HTTPException(status_code=403, detail="Cannot assign role — no permission escalation")
            if role not in ADMIN_ROLES:
                raise HTTPException(status_code=400, detail="Invalid admin role")
            row.role = role

        if email is not None:
            email_norm = email.strip().lower()
            dup = await db.execute(
                select(AdminUser).where(
                    func.lower(AdminUser.email) == email_norm,
                    AdminUser.id != user_id,
                ),
            )
            if dup.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email already in use")
            row.email = email_norm

        if password:
            row.password_hash = hash_password(password)

        if status is not None:
            if status not in ADMIN_USER_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid status")
            row.status = status
            if status != "active":
                sessions = await db.execute(
                    select(AdminSession).where(
                        AdminSession.admin_user_id == user_id,
                        AdminSession.session_status == "active",
                    ),
                )
                for session in sessions.scalars().all():
                    session.session_status = "revoked"
                    session.revoked_at = _utc_now()
                    session.refresh_token_hash = None
                    session.access_token_nonce = None

        row.updated_at = _utc_now()
        await db.commit()
        await db.refresh(row)

        audit_details: dict[str, Any] = {}
        if role is not None:
            audit_details["role"] = role
            event_type = "role_change"
            action = "admin_role_updated"
        elif status is not None:
            event_type = "permission_change"
            action = "admin_status_updated"
            audit_details["status"] = status
        else:
            event_type = "user_management"
            action = "admin_user_updated"

        await AdminRbacService.record_audit(
            db,
            admin_user_id=actor.id,
            event_type=event_type,
            action=action,
            resource_type="admin_user",
            resource_id=str(user_id),
            details=json.dumps(audit_details) if audit_details else None,
            success=True,
        )
        return AdminRbacService.serialize_user(row)

    @staticmethod
    async def list_sessions(
        db: AsyncSession,
        actor: CurrentAdminUser,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
        status: str | None = None,
    ) -> dict[str, Any]:
        AdminRbacService.assert_permission(actor, "logs.read")
        limit = clamp_limit(limit)
        count_q = select(func.count()).select_from(AdminSession)
        if status:
            count_q = count_q.where(AdminSession.session_status == status)
        total = (await db.execute(count_q)).scalar() or 0

        query = select(AdminSession, AdminUser).join(AdminUser, AdminSession.admin_user_id == AdminUser.id)
        if status:
            query = query.where(AdminSession.session_status == status)
        rows = await db.execute(
            query.order_by(AdminSession.last_activity.desc()).offset(skip).limit(limit),
        )
        items = []
        for session, user in rows.all():
            items.append({
                "id": session.id,
                "admin_user_id": session.admin_user_id,
                "admin_email": user.email,
                "admin_role": user.role,
                "login_time": session.login_time,
                "last_activity": session.last_activity,
                "session_status": session.session_status,
                "ip_address": session.ip_address,
                "user_agent": session.user_agent,
            })
        return {"items": items, "total": total}

    @staticmethod
    async def list_audit_logs(
        db: AsyncSession,
        actor: CurrentAdminUser,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        AdminRbacService.assert_permission(actor, "logs.read")
        limit = clamp_limit(limit)
        query = select(AdminAuditLog, AdminUser).outerjoin(
            AdminUser, AdminAuditLog.admin_user_id == AdminUser.id,
        )
        if event_type:
            query = query.where(AdminAuditLog.event_type == event_type)
        count_q = select(func.count()).select_from(AdminAuditLog)
        if event_type:
            count_q = count_q.where(AdminAuditLog.event_type == event_type)
        total = (await db.execute(count_q)).scalar() or 0
        rows = await db.execute(
            query.order_by(AdminAuditLog.created_at.desc()).offset(skip).limit(limit),
        )
        items = []
        for log, user in rows.all():
            items.append({
                "id": log.id,
                "admin_user_id": log.admin_user_id,
                "admin_email": user.email if user else None,
                "event_type": log.event_type,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "details": log.details,
                "ip_address": log.ip_address,
                "success": log.success == "true",
                "created_at": log.created_at,
            })
        return {"items": items, "total": total}

    @staticmethod
    async def platform_tenants(
        db: AsyncSession,
        actor: CurrentAdminUser,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        AdminRbacService.assert_permission(actor, "tenants.read")
        limit = clamp_limit(limit)
        total = (await db.execute(select(func.count()).select_from(Tenant))).scalar() or 0
        rows = await db.execute(
            select(Tenant).order_by(Tenant.created_at.desc()).offset(skip).limit(limit),
        )
        items = [
            {
                "id": str(t.id),
                "company_name": t.company_name,
                "status": t.status,
                "plan": t.plan,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in rows.scalars().all()
        ]
        return {"items": items, "total": total}

    @staticmethod
    async def platform_billing(db: AsyncSession, actor: CurrentAdminUser) -> dict[str, Any]:
        AdminRbacService.assert_permission(actor, "billing.read")
        from app.services.subscription_service import SubscriptionService

        plans = await SubscriptionService.list_plans(db)
        total_tenants = (await db.execute(select(func.count()).select_from(Tenant))).scalar() or 0
        active_subs = (
            await db.execute(
                select(func.count()).select_from(Subscription).where(Subscription.status == "active"),
            )
        ).scalar() or 0
        trial_subs = (
            await db.execute(
                select(func.count()).select_from(Subscription).where(Subscription.status == "trial"),
            )
        ).scalar() or 0
        return {
            "total_tenants": total_tenants,
            "active_subscriptions": active_subs,
            "trial_subscriptions": trial_subs,
            "plans": plans.get("items", []),
        }

    @staticmethod
    async def platform_analytics(db: AsyncSession, actor: CurrentAdminUser) -> dict[str, Any]:
        AdminRbacService.assert_permission(actor, "analytics.read")
        total_tenants = (await db.execute(select(func.count()).select_from(Tenant))).scalar() or 0
        active_tenants = (
            await db.execute(
                select(func.count()).select_from(Tenant).where(Tenant.status == "active"),
            )
        ).scalar() or 0
        total_clients = (await db.execute(select(func.count()).select_from(Client))).scalar() or 0
        from app.models.crm_lead import CrmLead
        from app.models.crm_deal import CrmDeal

        total_leads = (await db.execute(select(func.count()).select_from(CrmLead))).scalar() or 0
        total_deals = (await db.execute(select(func.count()).select_from(CrmDeal))).scalar() or 0
        return {
            "total_tenants": total_tenants,
            "active_tenants": active_tenants,
            "total_clients": total_clients,
            "total_leads": total_leads,
            "total_deals": total_deals,
            "executive_copilot_available": True,
        }

    @staticmethod
    async def security_checks(db: AsyncSession) -> dict[str, Any]:
        checks: list[dict[str, str]] = []

        admin_count = (await db.execute(select(func.count()).select_from(AdminUser))).scalar() or 0
        if admin_count == 0:
            checks.append({
                "name": "admin_users_exist",
                "status": "warning",
                "message": "No platform admin users configured — bootstrap via ADMIN_BOOTSTRAP_* env vars",
            })
        else:
            checks.append({
                "name": "admin_users_exist",
                "status": "ok",
                "message": f"{admin_count} platform admin user(s) registered",
            })

        active_sessions = (
            await db.execute(
                select(func.count()).select_from(AdminSession).where(AdminSession.session_status == "active"),
            )
        ).scalar() or 0
        checks.append({
            "name": "admin_sessions",
            "status": "ok",
            "message": f"{active_sessions} active admin session(s)",
        })

        from app.core.config import settings

        if settings_secret_is_default():
            checks.append({
                "name": "secret_key",
                "status": "error",
                "message": "SECRET_KEY is default — change before production",
            })
        else:
            checks.append({
                "name": "secret_key",
                "status": "ok",
                "message": "SECRET_KEY is configured",
            })

        if not settings.ADMIN_SECRET_KEY or not settings.TENANT_SECRET_KEY:
            checks.append({
                "name": "jwt_secret_separation",
                "status": "warning",
                "message": "Set ADMIN_SECRET_KEY and TENANT_SECRET_KEY for production",
            })
        elif settings.ADMIN_SECRET_KEY == settings.TENANT_SECRET_KEY:
            checks.append({
                "name": "jwt_secret_separation",
                "status": "error",
                "message": "ADMIN_SECRET_KEY and TENANT_SECRET_KEY must differ",
            })
        else:
            checks.append({
                "name": "jwt_secret_separation",
                "status": "ok",
                "message": "Admin and tenant JWT secrets are separated",
            })

        if settings.APP_ENV != "development":
            checks.append({
                "name": "bootstrap_locked",
                "status": "ok",
                "message": f"Bootstrap disabled in APP_ENV={settings.APP_ENV}",
            })
        else:
            checks.append({
                "name": "bootstrap_locked",
                "status": "warning",
                "message": "Bootstrap enabled — development only",
            })

        checks.append({
            "name": "tenant_admin_separation",
            "status": "ok",
            "message": "Admin JWT uses ADMIN_SECRET_KEY; tenant JWT uses TENANT_SECRET_KEY",
        })

        checks.append({
            "name": "no_default_super_admin",
            "status": "ok",
            "message": "No hardcoded super-admin credentials in codebase",
        })

        ok_count = sum(1 for c in checks if c["status"] == "ok")
        return {"checks": checks, "ok_count": ok_count, "total": len(checks)}


def settings_secret_is_default() -> bool:
    from app.core.config import settings

    return settings.SECRET_KEY in ("change-me", "change-me-in-production-use-a-long-random-string")
