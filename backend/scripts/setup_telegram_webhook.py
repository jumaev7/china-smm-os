"""
Register Telegram bot webhook for local dev (cloudflared quick tunnel).

Usage:
  python scripts/setup_telegram_webhook.py --public-url https://xxxx.trycloudflare.com
  python scripts/setup_telegram_webhook.py --public-url https://xxxx.trycloudflare.com --check-only
  python scripts/sync_cloudflared_telegram_webhook.py   # full dev workflow (auto-detect tunnel)

Requires TELEGRAM_BOT_TOKEN in backend/.env.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings

TELEGRAM_API = "https://api.telegram.org"
WEBHOOK_PATH = "/api/v1/telegram/webhook"
HTTP_TIMEOUT = 10.0
METRICS_TIMEOUT = 3.0
CLOUDFLARED_METRICS_URL = "http://127.0.0.1:20241/metrics"
TEST_GROUP_CHAT_ID = -5111242647
_HOSTNAME_RE = re.compile(
    r'cloudflared_tunnel_user_hostnames(?:_counts)?\{userHostname="([^"]+)"\}\s+1'
)


def _normalize_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SystemExit(f"Invalid --public-url (need https://host): {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _require_token() -> str:
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set in backend/.env")
    return token


def _webhook_url(public_url: str) -> str:
    return f"{_normalize_public_url(public_url)}{WEBHOOK_PATH}"


async def check_backend_health(backend_base: str = "http://127.0.0.1:8000") -> dict:
    health_url = f"{backend_base.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(health_url)
        ok = resp.status_code == 200
        body = resp.json() if ok else resp.text[:200]
        return {"ok": ok, "url": health_url, "status_code": resp.status_code, "body": body}
    except httpx.RequestError as exc:
        return {"ok": False, "url": health_url, "error": str(exc)}


async def detect_cloudflared_public_url() -> str | None:
    """Read active trycloudflare hostname from cloudflared metrics (short timeout)."""
    try:
        async with httpx.AsyncClient(timeout=METRICS_TIMEOUT) as client:
            resp = await client.get(CLOUDFLARED_METRICS_URL)
        if resp.status_code != 200:
            return None
        for match in _HOSTNAME_RE.finditer(resp.text):
            host = match.group(1).strip()
            if host:
                if host.startswith("http://") or host.startswith("https://"):
                    return _normalize_public_url(host)
                return f"https://{host}"
    except httpx.RequestError:
        return None
    return None


async def get_webhook_info(token: str) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(f"{TELEGRAM_API}/bot{token}/getWebhookInfo")
    body = resp.json()
    if not body.get("ok"):
        raise SystemExit(f"getWebhookInfo failed: {json.dumps(body)}")
    return body.get("result") or {}


async def register_webhook(public_url: str, *, drop_pending: bool) -> dict:
    token = _require_token()
    webhook_url = _webhook_url(public_url)
    payload: dict = {
        "url": webhook_url,
        "allowed_updates": ["message", "edited_message", "callback_query"],
        "drop_pending_updates": drop_pending,
        "max_connections": 40,
    }
    secret = (settings.TELEGRAM_WEBHOOK_SECRET or "").strip()
    if secret:
        payload["secret_token"] = secret

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        set_resp = await client.post(f"{TELEGRAM_API}/bot{token}/setWebhook", json=payload)
        set_body = set_resp.json()
        if not set_body.get("ok"):
            raise SystemExit(f"setWebhook failed: {json.dumps(set_body)}")

        info = await get_webhook_info(token)

    return {
        "webhook_url": webhook_url,
        "setWebhook": set_body,
        "getWebhookInfo": info,
    }


async def probe_webhook(public_url: str) -> dict:
    webhook_url = _webhook_url(public_url)
    headers = {"Content-Type": "application/json"}
    secret = (settings.TELEGRAM_WEBHOOK_SECRET or "").strip()
    if secret:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                webhook_url,
                headers=headers,
                json={
                    "update_id": 0,
                    "message": {"message_id": 0, "date": 0, "chat": {"id": 0, "type": "private"}},
                },
            )
        return {"ok": resp.status_code == 200, "status_code": resp.status_code, "body": resp.text[:300]}
    except httpx.RequestError as exc:
        return {"ok": False, "error": str(exc)}


def _verify_webhook_url(expected: str, info: dict) -> None:
    actual = (info.get("url") or "").strip()
    if actual != expected:
        raise SystemExit(
            "Webhook URL mismatch after setWebhook.\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual or '(empty)'}"
        )


def _print_webhook_info(info: dict) -> None:
    print("getWebhookInfo:")
    print(json.dumps(info, indent=2))
    pending = info.get("pending_update_count")
    last_err = info.get("last_error_message")
    if pending:
        print(f"  pending_update_count: {pending}")
    if last_err:
        print(f"  last_error_message: {last_err}")
    elif info.get("url"):
        print("  last_error_message: (none)")


async def sync_webhook(
    public_url: str,
    *,
    backend_base: str = "http://127.0.0.1:8000",
    drop_pending: bool = False,
    probe: bool = True,
    require_backend: bool = True,
) -> dict:
    """Full deterministic sync: health → setWebhook → verify → optional probe."""
    _require_token()
    public_url = _normalize_public_url(public_url)
    expected_webhook = _webhook_url(public_url)

    print(f"Public tunnel URL: {public_url}")
    print(f"Webhook URL:       {expected_webhook}")

    health = await check_backend_health(backend_base)
    if health.get("ok"):
        print(f"Backend health:    OK ({health['url']})")
    elif require_backend:
        detail = health.get("error") or f"HTTP {health.get('status_code')}"
        raise SystemExit(f"Backend not reachable at {health['url']}: {detail}")
    else:
        print(f"Backend health:    WARN — {health.get('error') or health.get('status_code')}")

    result = await register_webhook(public_url, drop_pending=drop_pending)
    info = result["getWebhookInfo"]
    _verify_webhook_url(expected_webhook, info)
    print("setWebhook:        OK")
    _print_webhook_info(info)

    probe_result: dict | None = None
    if probe:
        probe_result = await probe_webhook(public_url)
        if probe_result.get("ok"):
            print(f"Tunnel probe:      OK (HTTP {probe_result['status_code']})")
        else:
            detail = probe_result.get("error") or f"HTTP {probe_result.get('status_code')}"
            print(f"Tunnel probe:      WARN — {detail}")
            if probe_result.get("body"):
                print(f"  body: {probe_result['body'][:200]}")

    print()
    print(f"READY — send a human photo+caption in group {TEST_GROUP_CHAT_ID}")

    return {
        "public_url": public_url,
        "webhook_url": expected_webhook,
        "health": health,
        "setWebhook": result["setWebhook"],
        "getWebhookInfo": info,
        "probe": probe_result,
        "ready": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Register Telegram webhook for a public dev tunnel URL")
    parser.add_argument("--public-url", help="Tunnel base URL, e.g. https://xxxx.trycloudflare.com")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="Local backend base URL")
    parser.add_argument("--drop-pending", action="store_true", help="Drop pending Telegram updates on register")
    parser.add_argument("--check-only", action="store_true", help="Only fetch getWebhookInfo (no setWebhook)")
    parser.add_argument("--probe", action="store_true", help="POST a minimal probe through the public tunnel URL")
    parser.add_argument("--sync", action="store_true", help="Full sync workflow (set + verify + probe)")
    parser.add_argument("--no-probe", action="store_true", help="Skip tunnel probe (with --sync)")
    args = parser.parse_args()

    if args.check_only:
        token = _require_token()
        info = asyncio.run(get_webhook_info(token))
        _print_webhook_info(info)
        return

    if args.sync:
        if not args.public_url:
            raise SystemExit("--public-url is required for --sync")
        asyncio.run(
            sync_webhook(
                args.public_url,
                backend_base=args.backend_url,
                drop_pending=args.drop_pending,
                probe=not args.no_probe,
            )
        )
        return

    if not args.public_url:
        raise SystemExit("--public-url is required")

    result = asyncio.run(register_webhook(args.public_url, drop_pending=args.drop_pending))
    print(json.dumps(result, indent=2))

    if args.probe:
        probe = asyncio.run(probe_webhook(args.public_url))
        print("probe:", json.dumps(probe, indent=2))


if __name__ == "__main__":
    main()
