"""Admin Authentication & RBAC v1 — JWT tokens, login, session management."""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_permissions import ADMIN_ROLES
from app.core.config import settings
from app.services.admin_login_security_service import AdminLoginSecurityService
from app.models.admin_user import AdminSession, AdminUser
from app.services.auth_service import (
    create_refresh_token_value,
    hash_password,
    hash_refresh_token,
    verify_password,
)

logger = logging.getLogger(__name__)

MARKER = "[AdminAuth]"

TOKEN_TYPE_ADMIN_ACCESS = "admin_access"
TOKEN_TYPE_ADMIN_REFRESH = "admin_refresh"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_admin_access_token(
    *,
    user_id: UUID,
    email: str,
    role: str,
    session_id: UUID,
    access_token_nonce: str,
) -> str:
    expire = _utc_now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "session_id": str(session_id),
        "access_nonce": access_token_nonce,
        "type": TOKEN_TYPE_ADMIN_ACCESS,
        "scope": "admin",
        "exp": expire,
    }
    return jwt.encode(payload, settings.admin_secret_key, algorithm=settings.JWT_ALGORITHM)


def create_admin_refresh_token(
    *,
    user_id: UUID,
    session_id: UUID,
) -> str:
    expire = _utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "session_id": str(session_id),
        "type": TOKEN_TYPE_ADMIN_REFRESH,
        "scope": "admin",
        "exp": expire,
    }
    return jwt.encode(payload, settings.admin_secret_key, algorithm=settings.JWT_ALGORITHM)


def decode_admin_token(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.admin_secret_key, algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired admin token") from exc

    if payload.get("scope") != "admin":
        raise HTTPException(status_code=401, detail="Invalid admin token scope")

    token_type = payload.get("type")
    if expected_type and token_type != expected_type:
        raise HTTPException(status_code=401, detail="Invalid admin token type")

    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid admin token payload")

    if expected_type == TOKEN_TYPE_ADMIN_ACCESS:
        if not payload.get("session_id"):
            raise HTTPException(status_code=401, detail="Admin session required in token")
        if not payload.get("access_nonce"):
            raise HTTPException(status_code=401, detail="Admin access token nonce required")

    return payload


def _client_meta(request: Request | None) -> tuple[str | None, str | None]:
    if not request:
        return None, None
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return ip, user_agent


class AdminAuthService:
    """Platform admin authentication — separate from tenant auth."""

    @staticmethod
    async def load_user_by_id(db: AsyncSession, user_id: UUID) -> AdminUser | None:
        return await db.get(AdminUser, user_id)

    @staticmethod
    async def load_user_by_email(db: AsyncSession, email: str) -> AdminUser | None:
        email_norm = email.strip().lower()
        result = await db.execute(
            select(AdminUser).where(func.lower(AdminUser.email) == email_norm),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def load_session(db: AsyncSession, session_id: UUID) -> AdminSession | None:
        return await db.get(AdminSession, session_id)

    @staticmethod
    async def touch_session(db: AsyncSession, session: AdminSession) -> None:
        session.last_activity = _utc_now()
        await db.commit()

    @staticmethod
    async def login(
        db: AsyncSession,
        *,
        email: str,
        password: str,
        request: Request | None = None,
    ) -> dict[str, Any]:
        from app.services.admin_rbac_service import AdminRbacService

        AdminLoginSecurityService.check_rate_limit(request)
        user = await AdminAuthService.load_user_by_email(db, email)
        ip, user_agent = _client_meta(request)
        AdminLoginSecurityService.assert_not_locked(user)

        if not user or not verify_password(password, user.password_hash):
            AdminLoginSecurityService.record_rate_limit_attempt(request)
            if user:
                await AdminLoginSecurityService.record_failed_login(db, user)
            await AdminRbacService.record_audit(
                db,
                admin_user_id=user.id if user else None,
                event_type="login",
                action="admin_login_failed",
                details=json.dumps({"email": email.strip().lower()}),
                ip_address=ip,
                success=False,
            )
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if user.status != "active":
            await AdminRbacService.record_audit(
                db,
                admin_user_id=user.id,
                event_type="login",
                action="admin_login_blocked",
                details=json.dumps({"status": user.status}),
                ip_address=ip,
                success=False,
            )
            raise HTTPException(status_code=403, detail=f"Admin account is {user.status}")

        await AdminLoginSecurityService.reset_failed_logins(db, user)

        now = _utc_now()
        access_nonce = secrets.token_urlsafe(32)
        session = AdminSession(
            admin_user_id=user.id,
            login_time=now,
            last_activity=now,
            session_status="active",
            ip_address=ip,
            user_agent=user_agent[:512] if user_agent else None,
            access_token_nonce=access_nonce,
        )
        db.add(session)
        await db.flush()

        refresh_value = create_refresh_token_value()
        session.refresh_token_hash = hash_refresh_token(refresh_value)
        user.last_login_at = now
        user.updated_at = now
        await db.commit()
        await db.refresh(session)

        access_token = create_admin_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            session_id=session.id,
            access_token_nonce=access_nonce,
        )

        await AdminRbacService.record_audit(
            db,
            admin_user_id=user.id,
            event_type="login",
            action="admin_login",
            resource_type="admin_session",
            resource_id=str(session.id),
            ip_address=ip,
            success=True,
        )

        logger.info("%s login: user=%s session=%s", MARKER, user.email, session.id)
        return {
            "access_token": access_token,
            "refresh_token": refresh_value,
            "token_type": "bearer",
            "user": AdminRbacService.serialize_user(user),
            "session_id": session.id,
        }

    @staticmethod
    async def logout(
        db: AsyncSession,
        *,
        user_id: UUID,
        session_id: UUID,
        request: Request | None = None,
    ) -> dict[str, str]:
        from app.services.admin_rbac_service import AdminRbacService

        ip, _ = _client_meta(request)
        if session_id:
            session = await AdminAuthService.load_session(db, session_id)
            if session and session.admin_user_id == user_id and session.session_status == "active":
                session.session_status = "revoked"
                session.revoked_at = _utc_now()
                session.refresh_token_hash = None
                session.access_token_nonce = None
                await db.commit()
        else:
            from sqlalchemy import update

            await db.execute(
                update(AdminSession)
                .where(
                    AdminSession.admin_user_id == user_id,
                    AdminSession.session_status == "active",
                )
                .values(
                    session_status="revoked",
                    revoked_at=_utc_now(),
                    refresh_token_hash=None,
                    access_token_nonce=None,
                ),
            )
            await db.commit()

        await AdminRbacService.record_audit(
            db,
            admin_user_id=user_id,
            event_type="logout",
            action="admin_logout",
            resource_type="admin_session",
            resource_id=str(session_id),
            ip_address=ip,
            success=True,
        )
        return {"message": "Logged out"}

    @staticmethod
    async def refresh_session(
        db: AsyncSession,
        refresh_token: str,
        request: Request | None = None,
    ) -> dict[str, Any]:
        payload = decode_admin_token(refresh_token, expected_type=TOKEN_TYPE_ADMIN_REFRESH)
        user_id = UUID(payload["sub"])
        session_id = UUID(payload["session_id"])

        user = await AdminAuthService.load_user_by_id(db, user_id)
        session = await AdminAuthService.load_session(db, session_id)
        if not user or user.status != "active" or not session:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        if session.session_status != "active":
            raise HTTPException(status_code=401, detail="Admin session revoked")
        if not session.refresh_token_hash:
            raise HTTPException(status_code=401, detail="Refresh token revoked")
        if session.refresh_token_hash != hash_refresh_token(refresh_token):
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        session.last_activity = _utc_now()
        new_refresh = create_refresh_token_value()
        session.refresh_token_hash = hash_refresh_token(new_refresh)
        new_nonce = secrets.token_urlsafe(32)
        session.access_token_nonce = new_nonce
        await db.commit()

        access_token = create_admin_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            session_id=session.id,
            access_token_nonce=new_nonce,
        )

        from app.services.admin_rbac_service import AdminRbacService

        ip, _ = _client_meta(request)
        await AdminRbacService.record_audit(
            db,
            admin_user_id=user.id,
            event_type="refresh",
            action="admin_token_refresh",
            resource_type="admin_session",
            resource_id=str(session.id),
            ip_address=ip,
            success=True,
        )
        return {
            "access_token": access_token,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "session_id": session.id,
        }

    @staticmethod
    async def me(db: AsyncSession, user: AdminUser, session_id: UUID | None = None) -> dict[str, Any]:
        from app.core.admin_permissions import permissions_for_role
        from app.services.admin_rbac_service import AdminRbacService

        if session_id:
            session = await AdminAuthService.load_session(db, session_id)
            if session and session.session_status == "active":
                session.last_activity = _utc_now()
                await db.commit()

        return {
            "user": AdminRbacService.serialize_user(user),
            "permissions": permissions_for_role(user.role),
            "roles_available": sorted(ADMIN_ROLES),
            "role_permissions": {
                role: permissions_for_role(role) for role in sorted(ADMIN_ROLES)
            },
        }

    @staticmethod
    async def ensure_bootstrap_admin(db: AsyncSession) -> dict[str, Any] | None:
        """Create or reset bootstrap super_admin from env vars (development only)."""
        if settings.APP_ENV != "development":
            return None

        bootstrap_email = getattr(settings, "ADMIN_BOOTSTRAP_EMAIL", "").strip().lower()
        bootstrap_password = getattr(settings, "ADMIN_BOOTSTRAP_PASSWORD", "")
        if not bootstrap_email or not bootstrap_password:
            return None

        user = await AdminAuthService.load_user_by_email(db, bootstrap_email)
        if user:
            user.password_hash = hash_password(bootstrap_password)
            user.role = "super_admin"
            user.status = "active"
            user.failed_login_attempts = 0
            user.locked_until = None
            user.updated_at = _utc_now()
            await db.commit()
            await db.refresh(user)
            logger.info("%s bootstrap admin reset: %s", MARKER, bootstrap_email)
            return {
                "message": "Bootstrap admin reset from environment configuration",
                "email": bootstrap_email,
                "user_id": str(user.id),
                "created": False,
                "reset": True,
            }

        user = AdminUser(
            email=bootstrap_email,
            role="super_admin",
            status="active",
            password_hash=hash_password(bootstrap_password),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("%s bootstrap admin created: %s", MARKER, bootstrap_email)
        return {
            "message": "Bootstrap admin created from environment configuration",
            "email": bootstrap_email,
            "user_id": str(user.id),
            "created": True,
            "reset": False,
        }
