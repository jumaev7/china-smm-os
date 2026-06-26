"""Verify Facebook Page publishing — mock/blocked paths and optional live smoke."""
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
    missing_facebook_publish_permissions,
    meta_oauth_configured,
)


def req(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {"detail": str(exc)}
        except json.JSONDecodeError:
            payload = {"detail": raw or str(exc)}
        return exc.code, payload


async def _demo_connect_direct() -> dict:
    from app.core.database import AsyncSessionLocal
    from app.services.meta_connection_service import MetaConnectionService
    from app.services.meta_oauth_service import MetaOAuthService

    async with AsyncSessionLocal() as db:
        await MetaOAuthService.demo_connect(db)
        return await MetaConnectionService.get_connection_summary(db)


def demo_connect_direct() -> dict:
    return asyncio.run(_demo_connect_direct())


async def _seed_publish_verify_ready() -> dict | None:
    from app.core.database import AsyncSessionLocal
    from app.services.demo_tenant_seed_service import ensure_publish_verify_ready_for_demo_user

    async with AsyncSessionLocal() as db:
        return await ensure_publish_verify_ready_for_demo_user(db)


def seed_publish_verify_ready() -> dict | None:
    return asyncio.run(_seed_publish_verify_ready())


def main() -> int:
    print("=== Facebook Page publishing verification ===\n")
    report: dict = {
        "demo_mode": settings.DEMO_MODE,
        "oauth_configured": meta_oauth_configured(),
        "live_smoke_enabled": settings.ENABLE_FACEBOOK_LIVE_SMOKE,
        "facebook": {},
        "live_smoke": {"skipped": True, "reason": None},
    }
    failures: list[str] = []

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

    code, summary = auth_req("GET", "/publishing/meta/connection")
    if code != 200:
        print("FAIL connection_summary", code, summary)
        return 1
    print("OK connection_summary")

    if not summary.get("connected") and settings.DEMO_MODE:
        code, demo = auth_req("POST", "/publishing/meta/oauth/demo-connect")
        if code != 200:
            try:
                summary = demo_connect_direct()
            except Exception as exc:
                print("FAIL demo_connect", exc)
                return 1
        else:
            code, summary = auth_req("GET", "/publishing/meta/connection")

    fb_health = summary.get("facebook") or {}
    ig_health = summary.get("instagram") or {}
    report["facebook"]["health"] = fb_health
    report["facebook"]["publish_implementation"] = summary.get("publish_implementation")

    if ig_health.get("implementation") == "live":
        failures.append("instagram implementation must not be live")
        print("FAIL instagram implementation is live")
    else:
        print("OK instagram remains mock")

    is_demo_account = bool((fb_health.get("metadata") or {}).get("demo"))
    fb_impl = fb_health.get("implementation") or summary.get("publish_implementation") or "mock"

    if settings.DEMO_MODE or is_demo_account or not meta_oauth_configured():
        if fb_impl == "live" and fb_health.get("publish_ready"):
            failures.append("demo/no-credentials path must not claim facebook live-ready")
            print("FAIL facebook claims live-ready in demo/no-credentials mode")
        else:
            print("OK facebook mock/blocked in demo or no-credentials mode implementation=", fb_impl)

    code, accounts = auth_req("GET", "/publishing/accounts?platform=facebook")
    mock_accounts = []
    connected_accounts = []
    if code == 200:
        items = accounts.get("items") or []
        mock_accounts = [a for a in items if a.get("status") == "mock"]
        connected_accounts = [a for a in items if a.get("status") == "connected"]

    if mock_accounts:
        seed_info = seed_publish_verify_ready()
        content_id = (seed_info or {}).get("content_id")
        if not content_id:
            code, content = auth_req("GET", "/content?limit=20")
            items = (content.get("items") or []) if code == 200 else []
            content_id = items[0]["id"] if items else None
        if content_id:
            code, pub = auth_req(
                "POST",
                f"/content/{content_id}/publish",
                {"test": True, "mode": "test_publish", "platforms": ["facebook"]},
            )
            results = pub.get("results") or []
            first = results[0] if results else {}
            report["facebook"]["mock_publish"] = {
                "http": code,
                "mock": first.get("mock"),
                "platform_post_id": first.get("platform_post_id"),
                "blocked": first.get("blocked"),
            }
            if code == 500:
                failures.append("mock facebook publish returned 500")
                print("FAIL mock facebook publish http=500")
            elif code != 200:
                failures.append(f"mock facebook publish expected 200 got {code}")
                print("FAIL mock facebook publish http=", code)
            elif first.get("mock") is not True:
                failures.append("mock facebook account must return mock=true")
                print("FAIL mock facebook publish missing mock=true")
            elif not str(first.get("platform_post_id") or "").startswith("mock-fb-"):
                failures.append("mock facebook post_id must be mock-fb-*")
                print("FAIL mock facebook post_id", first.get("platform_post_id"))
            else:
                print("OK mock facebook publish mock-fb-*")

    if connected_accounts and not settings.ENABLE_FACEBOOK_LIVE_SMOKE:
        seed_info = seed_publish_verify_ready()
        content_id = (seed_info or {}).get("content_id")
        if content_id:
            code, pub = auth_req(
                "POST",
                f"/content/{content_id}/publish",
                {"test": True, "mode": "test_publish", "platforms": ["facebook"]},
            )
            results = pub.get("results") or []
            first = results[0] if results else {}
            report["facebook"]["connected_without_smoke"] = {
                "http": code,
                "success": first.get("success"),
                "mock": first.get("mock"),
                "blocked": first.get("blocked"),
                "error": first.get("error"),
            }
            if code == 500:
                failures.append("connected facebook publish without smoke returned 500")
                print("FAIL connected facebook publish returned 500")
            elif first.get("mock") is True:
                failures.append("connected facebook without smoke must not fake mock success")
                print("FAIL connected facebook returned mock=true without live smoke flag")
            elif first.get("success") is True and not first.get("mock"):
                failures.append("connected facebook without smoke must not succeed live")
                print("FAIL connected facebook live success without ENABLE_FACEBOOK_LIVE_SMOKE")
            else:
                print("OK connected facebook blocked/skipped without live smoke flag")

    if settings.ENABLE_FACEBOOK_LIVE_SMOKE and connected_accounts and not is_demo_account:
        permissions = fb_health.get("permissions") or []
        missing_publish = missing_facebook_publish_permissions(permissions)
        if missing_publish or fb_health.get("token_expired"):
            report["live_smoke"]["reason"] = "connected account not publish-ready"
            print("SKIP live smoke — account not publish-ready")
        else:
            seed_info = seed_publish_verify_ready()
            content_id = (seed_info or {}).get("content_id")
            if not content_id:
                failures.append("no content for facebook live smoke")
                print("FAIL no content for live smoke")
            else:
                code, pub = auth_req(
                    "POST",
                    f"/content/{content_id}/publish",
                    {
                        "test": True,
                        "mode": "test_publish",
                        "platforms": ["facebook"],
                    },
                )
                results = pub.get("results") or []
                first = results[0] if results else {}
                report["live_smoke"] = {
                    "skipped": False,
                    "http": code,
                    "success": first.get("success"),
                    "mock": first.get("mock"),
                    "platform_post_id": first.get("platform_post_id"),
                    "post_url": first.get("post_url"),
                    "error": first.get("error"),
                }
                if code == 500:
                    failures.append("facebook live smoke returned 500")
                    print("FAIL facebook live smoke http=500")
                elif first.get("mock") is True:
                    failures.append("facebook live smoke must not return mock=true")
                    print("FAIL facebook live smoke returned mock")
                elif not first.get("success"):
                    print("WARN facebook live smoke failed:", first.get("error"))
                elif not first.get("platform_post_id"):
                    failures.append("facebook live smoke missing platform_post_id")
                    print("FAIL facebook live smoke missing post id")
                else:
                    print("OK facebook live smoke post_id=", first.get("platform_post_id"))
    else:
        reason = "ENABLE_FACEBOOK_LIVE_SMOKE not set"
        if not connected_accounts:
            reason = "no connected facebook account"
        if is_demo_account:
            reason = "demo account — live smoke skipped"
        report["live_smoke"]["reason"] = reason
        print("SKIP live smoke:", reason)

    out_path = Path(__file__).with_name(".verify_facebook_publish_last.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print("REPORT", out_path)

    if failures:
        print("\nFAILURES:")
        for item in failures:
            print(" -", item)
        return 1

    print("\n=== Facebook publishing verification passed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
