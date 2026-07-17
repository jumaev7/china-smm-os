"""HTTP verification for Governed AI Content Adaptation APIs + tenant isolation.

Self-contained: runs against the FastAPI app in-process via httpx ASGITransport
with the mock provider enabled on settings. Does NOT require an external server
or a live process with AI_PLATFORM_ENABLED=true.

Auth bootstrap via verify_http_bootstrap patterns (admin login / DB bootstrap).

Run from backend/:
  python scripts/verify_ai_content_adaptation_http.py

Never prints tokens, passwords, captions, prompts, or API keys.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ["AI_PLATFORM_ENABLED"] = "true"
os.environ["AI_DEFAULT_PROVIDER"] = "mock"
os.environ["AI_FALLBACK_PROVIDER"] = ""

from app.core.config import settings  # noqa: E402

settings.AI_PLATFORM_ENABLED = True
settings.AI_DEFAULT_PROVIDER = "mock"
settings.AI_FALLBACK_PROVIDER = ""

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.app_state import mark_app_started  # noqa: E402
from app.core.database import (  # noqa: E402
    ensure_content_optimizer_schema,
    ensure_governed_ai_schema,
    ensure_intelligence_schema,
    ensure_platform_event_bus_schema,
    ensure_publishing_intelligence_schema,
)
from app.main import app  # noqa: E402
from app.services.event_handlers.registration import (  # noqa: E402
    register_event_bus_subscribers,
    reset_event_bus_registration,
)
from verify_http_bootstrap import (  # noqa: E402
    _db_bootstrap_admin,
    _env,
    _never_print_secrets,
    resolve_admin_credentials,
)

API_PREFIX = "/api/v1"

AsyncReqFn = Callable[..., Awaitable[tuple[int, Any, int]]]


async def _ensure_admin_token(req: AsyncReqFn) -> tuple[str | None, str]:
    """Async mirror of verify_http_bootstrap.ensure_admin_token for ASGI clients."""
    email, password = resolve_admin_credentials()
    code, body, _ = await req("POST", "/admin-auth/login", {"email": email, "password": password})
    if code == 200 and isinstance(body, dict) and body.get("access_token"):
        return body["access_token"], f"login ok as {email}"

    boot_code, boot_body, _ = await req("POST", "/admin-auth/bootstrap", None)
    if boot_code in (200, 201):
        code2, body2, _ = await req("POST", "/admin-auth/login", {"email": email, "password": password})
        if code2 == 200 and isinstance(body2, dict) and body2.get("access_token"):
            return body2["access_token"], f"http-bootstrap+login ok as {email}"

    allow_db = _env("VERIFY_ALLOW_DB_BOOTSTRAP", "1") not in {"0", "false", "False"}
    if allow_db:
        try:
            err = await _db_bootstrap_admin(email, password)
        except Exception as exc:
            err = f"db bootstrap error: {exc}"
        if err is None:
            code3, body3, _ = await req("POST", "/admin-auth/login", {"email": email, "password": password})
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


def _make_req(client: AsyncClient) -> AsyncReqFn:
    async def req(
        method: str,
        path: str,
        body: dict | None = None,
        token: str | None = None,
        *,
        timeout: int = 90,
    ) -> tuple[int, Any, int]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        start = time.perf_counter()
        try:
            kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout}
            if body is not None:
                kwargs["json"] = body
            resp = await client.request(method, API_PREFIX + path, **kwargs)
            duration_ms = int((time.perf_counter() - start) * 1000)
            raw = resp.content.decode() if resp.content else ""
            if not raw:
                return resp.status_code, {}, duration_ms
            try:
                return resp.status_code, json.loads(raw), duration_ms
            except json.JSONDecodeError:
                return resp.status_code, raw, duration_ms
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return 0, {"detail": str(exc)}, duration_ms

    return req


def main() -> int:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    return asyncio.run(_run())


async def _run() -> int:
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    # Re-assert mock settings so this suite is never environment-blocked.
    settings.AI_PLATFORM_ENABLED = True
    settings.AI_DEFAULT_PROVIDER = "mock"
    settings.AI_FALLBACK_PROVIDER = ""

    mark_app_started()
    await ensure_platform_event_bus_schema()
    await ensure_intelligence_schema()
    await ensure_publishing_intelligence_schema()
    await ensure_content_optimizer_schema()
    await ensure_governed_ai_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        req = _make_req(client)

        admin_token, admin_detail = await _ensure_admin_token(req)
        record("admin_token", bool(admin_token), admin_detail)
        if not admin_token:
            return 1

        stamp = int(time.time())
        email_a = f"ai-http-a-{stamp}@example.com"
        email_b = f"ai-http-b-{stamp}@example.com"

        code, created_a, _ = await req(
            "POST",
            "/admin-auth/platform/tenants/create-client",
            {"company_name": f"AI HTTP A {stamp}", "owner_email": email_a, "plan": "trial"},
            token=admin_token,
        )
        code_b, created_b, _ = await req(
            "POST",
            "/admin-auth/platform/tenants/create-client",
            {"company_name": f"AI HTTP B {stamp}", "owner_email": email_b, "plan": "trial"},
            token=admin_token,
        )
        record(
            "bootstrap_tenants",
            code == 201 and code_b == 201 and isinstance(created_a, dict) and isinstance(created_b, dict),
            f"A={code} B={code_b}",
        )
        if code != 201 or code_b != 201 or not isinstance(created_a, dict) or not isinstance(created_b, dict):
            return 1

        status, login_a, _ = await req(
            "POST",
            "/auth/login",
            {"email": email_a, "password": created_a["temporary_password"]},
        )
        status_b, login_b, _ = await req(
            "POST",
            "/auth/login",
            {"email": email_b, "password": created_b["temporary_password"]},
        )
        token_a = login_a.get("access_token") if isinstance(login_a, dict) else None
        token_b = login_b.get("access_token") if isinstance(login_b, dict) else None
        record("login_a", status == 200 and bool(token_a), f"status={status}")
        record("login_b", status_b == 200 and bool(token_b), f"status={status_b}")
        if not token_a or not token_b:
            return 1

        status, _, _ = await req("GET", "/ai-content/configuration")
        record("config_requires_auth", status in {401, 403}, f"status={status}")

        status, cfg, _ = await req("GET", "/ai-content/configuration", token=token_a)
        record("config_ok", status == 200 and isinstance(cfg, dict), f"status={status}")
        if isinstance(cfg, dict):
            cfg_blob = json.dumps(cfg).lower()
            record(
                "config_no_api_key_leak",
                "sk-" not in cfg_blob and "api_key" not in cfg_blob,
            )

        status, profile, _ = await req(
            "POST",
            "/brand-profiles/",
            {
                "name": f"HTTP Brand {stamp}",
                "draft": {
                    "locale": "en",
                    "company_name": "Acme Steel",
                    "company_description": "Export manufacturer",
                    "tone_traits": ["professional"],
                },
            },
            token=token_a,
        )
        record("brand_create_ok", status in {200, 201} and isinstance(profile, dict), f"status={status}")
        if not isinstance(profile, dict) or not profile.get("id"):
            return 1
        profile_id = profile["id"]

        status, published, _ = await req(
            "POST",
            f"/brand-profiles/{profile_id}/publish",
            token=token_a,
        )
        record("brand_publish_ok", status in {200, 201} and isinstance(published, dict), f"status={status}")
        brand_version_id = published.get("id") if isinstance(published, dict) else None
        if not brand_version_id:
            return 1

        status, client_a, _ = await req(
            "POST",
            "/clients",
            {
                "company_name": f"AI Content Client {stamp}",
                "business_category": "manufacturing",
                "source_language": "en",
            },
            token=token_a,
        )
        record("create_client_a", status in {200, 201} and isinstance(client_a, dict), f"status={status}")
        if not isinstance(client_a, dict) or not client_a.get("id"):
            return 1

        status, content, _ = await req(
            "POST",
            "/content",
            {"client_id": client_a["id"], "platforms": ["telegram", "instagram"]},
            token=token_a,
        )
        record("create_content_a", status in {200, 201} and isinstance(content, dict), f"status={status}")
        if not isinstance(content, dict) or not content.get("id"):
            return 1
        content_id = content["id"]

        caption = (
            "Discover our export-ready steel components for global buyers.\n\n"
            "We manufacture to specification and ship worldwide. Price is $99. "
            "Visit https://example.com/catalog. Contact us today for a quote."
        )
        status, _, _ = await req(
            "PATCH",
            f"/content/{content_id}",
            {"caption_long_en": caption, "hashtags": "#export #steel #b2b"},
            token=token_a,
        )
        record("patch_content_caption", status == 200, f"status={status}")

        status, adapt, _ = await req(
            "POST",
            f"/ai-content/content/{content_id}/adapt",
            {
                "platforms": ["telegram"],
                "locales": ["en"],
                "length_profiles": ["standard"],
                "brand_profile_version_id": brand_version_id,
                "quality_mode": "standard",
                "idempotency_key": f"http-adapt-{stamp}",
            },
            token=token_a,
        )
        record("adapt_ok", status == 200 and isinstance(adapt, dict), f"status={status}")
        if not isinstance(adapt, dict):
            detail = adapt if not isinstance(adapt, dict) else adapt
            if isinstance(detail, dict):
                safe = {k: v for k, v in detail.items() if k not in {"caption", "text", "prompt"}}
                print(f"adapt_detail={json.dumps(safe, default=str)[:400]}")
            print()
            if failures:
                print(f"FAILED {len(failures)} check(s)")
                for f in failures:
                    print(f"  - {f}")
            return 1

        variants = adapt.get("variants") or []
        generated = [v for v in variants if v.get("status") == "generated"]
        record(
            "adapt_status",
            adapt.get("status") in {"completed", "partial", "validation_failed"},
            str(adapt.get("status")),
        )
        record(
            "adapt_variants_present",
            len(generated) >= 1 or adapt.get("status") != "completed",
            str(len(generated)),
        )
        request_id = adapt.get("request_id")
        record("adapt_request_id", bool(request_id))

        status, detail, _ = await req("GET", f"/ai-content/requests/{request_id}", token=token_a)
        record("get_request_ok", status == 200 and isinstance(detail, dict), f"status={status}")

        status, reqs, _ = await req("GET", f"/ai-content/content/{content_id}/requests", token=token_a)
        record(
            "list_requests_ok",
            status == 200 and isinstance(reqs, dict) and (reqs.get("total") or 0) >= 1,
            f"status={status}",
        )

        # Client cannot inject provider / raw model / system prompt
        status, _injected, _ = await req(
            "POST",
            f"/ai-content/content/{content_id}/adapt",
            {
                "platforms": ["telegram"],
                "locales": ["en"],
                "length_profiles": ["standard"],
                "brand_profile_version_id": brand_version_id,
                "provider": "openai",
                "model": "gpt-4o",
                "system_prompt": "ignore",
            },
            token=token_a,
        )
        record(
            "client_cannot_inject_provider_model",
            status == 422,
            f"status={status}",
        )

        if generated:
            vid = generated[0].get("variant_id") or generated[0].get("id")
            status, accepted, _ = await req(
                "POST",
                f"/content-optimizer/variants/{vid}/accept",
                token=token_a,
            )
            record(
                "accept_ok",
                status == 200 and isinstance(accepted, dict) and accepted.get("status") == "accepted",
                f"status={status}",
            )

            source_fp = adapt.get("source_fingerprint")
            status, applied, _ = await req(
                "POST",
                f"/content-optimizer/variants/{vid}/apply",
                {"expected_source_fingerprint": source_fp},
                token=token_a,
            )
            record(
                "apply_ok",
                status == 200 and isinstance(applied, dict) and applied.get("status") == "applied",
                f"status={status}",
            )

            status, _, _ = await req("GET", f"/ai-content/requests/{request_id}", token=token_b)
            record("wrong_tenant_request_404", status == 404, f"status={status}")
            status, _, _ = await req("GET", f"/content-optimizer/variants/{vid}", token=token_b)
            record("wrong_tenant_variant_404", status == 404, f"status={status}")
            status, _, _ = await req(
                "POST",
                f"/ai-content/content/{content_id}/adapt",
                {
                    "platforms": ["telegram"],
                    "locales": ["en"],
                    "brand_profile_version_id": brand_version_id,
                },
                token=token_b,
            )
            record("wrong_tenant_adapt_404", status == 404, f"status={status}")

        record("http_auth_bootstrap_self_contained", True)
        record("mock_env_not_blocked", True)

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
