"""Admin Security Hardening v1 — login rate limiting, lockout, failed-attempt tracking."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.admin_user import AdminUser

_ip_attempts: dict[str, list[float]] = defaultdict(list)
_LOCKOUT_WINDOW_SEC = 900


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _prune_ip_attempts(ip: str, *, window_sec: int) -> None:
    cutoff = time.monotonic() - window_sec
    _ip_attempts[ip] = [t for t in _ip_attempts[ip] if t > cutoff]


class AdminLoginSecurityService:
    @staticmethod
    def check_rate_limit(request: Request | None) -> None:
        if not request or not request.client:
            return
        ip = request.client.host or "unknown"
        _prune_ip_attempts(ip, window_sec=settings.ADMIN_LOGIN_RATE_WINDOW_SEC)
        if len(_ip_attempts[ip]) >= settings.ADMIN_LOGIN_RATE_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts — try again later",
            )

    @staticmethod
    def record_rate_limit_attempt(request: Request | None) -> None:
        if not request or not request.client:
            return
        ip = request.client.host or "unknown"
        _ip_attempts[ip].append(time.monotonic())

    @staticmethod
    def assert_not_locked(user: AdminUser | None) -> None:
        if not user or not user.locked_until:
            return
        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > _utc_now():
            raise HTTPException(
                status_code=423,
                detail="Admin account temporarily locked due to failed login attempts",
            )

    @staticmethod
    async def record_failed_login(db: AsyncSession, user: AdminUser | None) -> None:
        if not user:
            return
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= settings.ADMIN_LOGIN_LOCKOUT_THRESHOLD:
            user.locked_until = _utc_now() + timedelta(minutes=settings.ADMIN_LOGIN_LOCKOUT_MINUTES)
        user.updated_at = _utc_now()
        await db.commit()

    @staticmethod
    async def reset_failed_logins(db: AsyncSession, user: AdminUser) -> None:
        if user.failed_login_attempts or user.locked_until:
            user.failed_login_attempts = 0
            user.locked_until = None
            user.updated_at = _utc_now()
            await db.commit()
