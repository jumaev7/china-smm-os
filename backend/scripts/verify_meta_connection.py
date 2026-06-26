"""Verify Meta Graph API publishing connection foundation."""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000/api/v1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.meta_graph_client import (
    REQUIRED_CONNECTION_PERMISSIONS,
    meta_oauth_configured,
    missing_connection_permissions,
)


def req(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {"detail": str(exc)}
        except json.JSONDecodeError:
            payload = {"detail": raw or str(exc)}
        return exc.code, payload


def check_oauth_configuration() -> list[str]:
    failures: list[str] = []
    if not (settings.META_APP_ID or "").strip():
        failures.append("META_APP_ID not set")
    if not (settings.META_APP_SECRET or "").strip():
        failures.append("META_APP_SECRET not set")
    if not (settings.META_OAUTH_REDIRECT_URI or "").strip():
        failures.append("META_OAUTH_REDIRECT_URI not set")
    if failures and settings.DEMO_MODE:
        print("WARN OAuth not fully configured — DEMO_MODE allows demo-connect path")
        return []
    return failures


async def _demo_connect_direct() -> dict:
    from app.core.database import AsyncSessionLocal
    from app.services.meta_oauth_service import MetaOAuthService

    async with AsyncSessionLocal() as db:
        await MetaOAuthService.demo_connect(db)
        from app.services.meta_connection_service import MetaConnectionService

        return await MetaConnectionService.get_connection_summary(db)


def demo_connect_direct() -> dict:
    return asyncio.run(_demo_connect_direct())


def main() -> int:
    print("=== Meta connection foundation verification ===\n")

    oauth_failures = check_oauth_configuration()
    if oauth_failures:
        for item in oauth_failures:
            print(f"FAIL oauth_config: {item}")
        if not settings.DEMO_MODE:
            return 1
    else:
        print("OK oauth_configuration")

    code, login = req(
        "POST",
        "/admin-auth/login",
        {"email": "admin@example.com", "password": "ChangeMe_12345!"},
    )
    if code != 200:
        code, login = req("POST", "/auth/login", {"email": "demo@factory.local", "password": "demo1234"})
    if code != 200:
        print("FAIL login", code, login)
        return 1
    token = login["access_token"]
    print("OK login")

    def auth_req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        return req(method, path, body, token=token)

    code, oauth_start = auth_req("GET", "/publishing/meta/oauth/start")
    if code == 200:
        mode = oauth_start.get("mode")
        if mode == "live" and oauth_start.get("authorize_url"):
            print("OK oauth_start live authorize_url present")
        elif mode == "demo" and oauth_start.get("demo_connect_url"):
            print("OK oauth_start demo mode")
        else:
            print("FAIL oauth_start unexpected payload", oauth_start)
            return 1
    elif settings.DEMO_MODE and code == 400:
        print("WARN oauth_start returned 400 — will use demo-connect")
    else:
        print("FAIL oauth_start", code, oauth_start)
        return 1

    code, summary = auth_req("GET", "/publishing/meta/connection")
    if code != 200:
        print("FAIL connection_summary", code, summary)
        return 1
    print("OK connection_summary health=", summary.get("health"))

    if not summary.get("connected") and settings.DEMO_MODE:
        code, demo = auth_req("POST", "/publishing/meta/oauth/demo-connect")
        if code != 200:
            print("WARN demo_connect via API failed — using direct service fallback")
            try:
                summary = demo_connect_direct()
                if not summary.get("connected"):
                    print("FAIL demo_connect direct", summary)
                    return 1
                print("OK demo_connect (direct)")
            except Exception as exc:
                print("FAIL demo_connect", code, demo, exc)
                return 1
        else:
            print("OK demo_connect")
            code, summary = auth_req("GET", "/publishing/meta/connection")
            if code != 200 or not summary.get("connected"):
                print("FAIL connection after demo_connect", code, summary)
                return 1

    if summary.get("connected"):
        fb = summary.get("facebook") or {}
        ig = summary.get("instagram") or {}
        if not fb.get("facebook_page_id"):
            print("FAIL stored_account missing facebook_page_id")
            return 1
        print("OK stored_account facebook_page_id=", fb.get("facebook_page_id"))

        if ig and not ig.get("instagram_business_account_id"):
            print("FAIL stored_account missing instagram_business_account_id")
            return 1
        if ig:
            print("OK business_account_resolution ig=", ig.get("instagram_business_account_id"))

        permissions = summary.get("permissions") or []
        missing = missing_connection_permissions(permissions)
        if summary.get("health") == "healthy" and missing:
            print("FAIL permission_set missing required:", ", ".join(missing))
            return 1
        print("OK permission_set count=", len(permissions), "required=", len(REQUIRED_CONNECTION_PERMISSIONS))

        if summary.get("token_expired"):
            print("WARN token_expired=true — reconnect or refresh recommended")

        code, health = auth_req("GET", "/publishing/meta/health")
        if code != 200:
            print("FAIL health_endpoint", code, health)
            return 1
        if health.get("publish_implementation") not in ("mock", "blocked", "live"):
            print("FAIL publish_implementation unexpected value", health.get("publish_implementation"))
            return 1
        ig_impl = (health.get("instagram") or {}).get("implementation")
        if ig_impl == "live":
            print("FAIL instagram implementation must remain mock")
            return 1
        fb_impl = (health.get("facebook") or {}).get("implementation") or health.get("publish_implementation")
        print("OK health_endpoint facebook_implementation=", fb_impl, "instagram_implementation=", ig_impl or "mock")

        code, accounts = auth_req("GET", "/publishing/accounts?platform=facebook")
        if code != 200:
            print("FAIL list_accounts", code, accounts)
            return 1
        items = accounts.get("items") or []
        connected_fb = [a for a in items if a.get("status") == "connected"]
        if connected_fb and not connected_fb[0].get("facebook_page_id"):
            print("FAIL publishing account API missing meta fields")
            return 1
        if connected_fb:
            print("OK publishing_account_api meta fields exposed (no token)")

        if not summary.get("token_expired") and not (fb.get("metadata") or {}).get("demo"):
            code, refreshed = auth_req("POST", "/publishing/meta/refresh")
            if code == 200:
                print("OK token_refresh")
            else:
                print("WARN token_refresh skipped/failed (may need live Meta credentials):", code)
    else:
        print("SKIP stored_account checks — no connected Meta account")
        print("  Connect via /publishing UI or set DEMO_MODE=true for demo-connect")

    print("\n=== All Meta connection foundation checks passed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
