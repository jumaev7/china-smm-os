"""Shared HTTP verification bootstrap — admin login for disposable/dev databases."""
from __future__ import annotations

import json
import os
from typing import Any, Callable


ReqFn = Callable[..., tuple[int, Any, int]]


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def resolve_admin_credentials() -> tuple[str, str]:
    """Prefer ADMIN_BOOTSTRAP_* when set; otherwise fall back to local verify defaults."""
    email = _env("ADMIN_BOOTSTRAP_EMAIL") or _env("VERIFY_ADMIN_EMAIL") or "admin@example.com"
    password = _env("ADMIN_BOOTSTRAP_PASSWORD") or _env("VERIFY_ADMIN_PASSWORD") or "ChangeMe_12345!"
    return email, password


def _never_print_secrets(payload: Any) -> str:
    """Safe diagnostic string — strip tokens/passwords from error payloads."""
    if not isinstance(payload, dict):
        text = str(payload)
        if len(text) > 240:
            return text[:240] + "…"
        return text
    safe = {
        k: ("[redacted]" if any(s in str(k).lower() for s in ("token", "password", "secret", "authorization")) else v)
        for k, v in payload.items()
        if k not in {"access_token", "refresh_token", "temporary_password"}
    }
    return json.dumps(safe, default=str)[:400]


async def _db_bootstrap_admin(email: str, password: str) -> str | None:
    """
    Development/test-only local bootstrap via AdminAuthService.

    Requires APP_ENV=development. Sets ADMIN_BOOTSTRAP_* for the process, then
    creates/resets the platform admin. Never invents production credentials.
    """
    from app.core.config import settings

    if settings.APP_ENV != "development":
        return "db bootstrap skipped — APP_ENV is not development"
    if not email or not password:
        return "db bootstrap skipped — email/password missing"

    # Align settings with the credentials this verify run will use.
    settings.ADMIN_BOOTSTRAP_EMAIL = email
    settings.ADMIN_BOOTSTRAP_PASSWORD = password

    from app.core.database import AsyncSessionLocal
    from app.services.admin_auth_service import AdminAuthService

    async with AsyncSessionLocal() as db:
        result = await AdminAuthService.ensure_bootstrap_admin(db)
    if not result:
        return "db bootstrap returned None — check ADMIN_BOOTSTRAP_* and APP_ENV"
    return None


async def ensure_admin_token(req: ReqFn) -> tuple[str | None, str]:
    """
    Obtain a platform admin access token for HTTP verification.

    Strategy:
    1. Login with ADMIN_BOOTSTRAP_* / VERIFY_ADMIN_* / local defaults.
    2. If login fails, POST /admin-auth/bootstrap when APP_ENV permits (dev guard on server).
    3. Retry login once after HTTP bootstrap.
    4. If still failing and local APP_ENV=development, bootstrap via DB using the same credentials.
    5. Fail with a precise setup message — never invent production credentials.
    """
    email, password = resolve_admin_credentials()
    code, body, _ = req("POST", "/admin-auth/login", {"email": email, "password": password})
    if code == 200 and isinstance(body, dict) and body.get("access_token"):
        return body["access_token"], f"login ok as {email}"

    boot_code, boot_body, _ = req("POST", "/admin-auth/bootstrap", None)
    if boot_code in (200, 201):
        code2, body2, _ = req("POST", "/admin-auth/login", {"email": email, "password": password})
        if code2 == 200 and isinstance(body2, dict) and body2.get("access_token"):
            return body2["access_token"], f"http-bootstrap+login ok as {email}"

    # Local disposable DB path — only when explicitly development.
    allow_db = _env("VERIFY_ALLOW_DB_BOOTSTRAP", "1") not in {"0", "false", "False"}
    if allow_db:
        try:
            err = await _db_bootstrap_admin(email, password)
        except Exception as exc:
            err = f"db bootstrap error: {exc}"
        if err is None:
            code3, body3, _ = req("POST", "/admin-auth/login", {"email": email, "password": password})
            if code3 == 200 and isinstance(body3, dict) and body3.get("access_token"):
                return body3["access_token"], f"db-bootstrap+login ok as {email}"
            return None, (
                "admin login failed after DB bootstrap — password mismatch or auth failure. "
                f"login_status={code3} detail={_never_print_secrets(body3)}"
            )
        db_detail = err
    else:
        db_detail = "VERIFY_ALLOW_DB_BOOTSTRAP disabled"

    return None, (
        "admin login failed and secure bootstrap unavailable — set ADMIN_BOOTSTRAP_EMAIL and "
        "ADMIN_BOOTSTRAP_PASSWORD with APP_ENV=development, then retry. "
        f"login_status={code} http_bootstrap={boot_code} "
        f"http_detail={_never_print_secrets(boot_body)} db={db_detail}"
    )
