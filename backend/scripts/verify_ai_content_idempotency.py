"""Idempotency verification for Governed AI Content Adaptation.

Same idempotency key → same request returned; mock provider call_count must not
increase on the duplicate call.

Run from backend/:  python scripts/verify_ai_content_idempotency.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["AI_PLATFORM_ENABLED"] = "true"
os.environ["AI_DEFAULT_PROVIDER"] = "mock"
os.environ["AI_FALLBACK_PROVIDER"] = ""

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def main() -> int:
    import asyncio

    return asyncio.run(_run())


async def _run() -> int:
    from app.core.config import settings
    from app.core.database import (
        AsyncSessionLocal,
        ensure_content_optimizer_schema,
        ensure_governed_ai_schema,
        ensure_intelligence_schema,
        ensure_platform_event_bus_schema,
        ensure_publishing_intelligence_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.tenant import Tenant, TenantUser
    from app.services.ai_content.adaptation_service import AIContentAdaptationService
    from app.services.ai_content.brand_profile_service import BrandProfileService
    from app.services.ai_content.schemas import AdaptRequest
    from app.services.ai_platform.provider_registry import get_mock_provider
    from app.services.auth_service import hash_password
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )

    settings.AI_PLATFORM_ENABLED = True
    settings.AI_DEFAULT_PROVIDER = "mock"

    await ensure_platform_event_bus_schema()
    await ensure_intelligence_schema()
    await ensure_publishing_intelligence_schema()
    await ensure_content_optimizer_schema()
    await ensure_governed_ai_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []
    mock = get_mock_provider()
    mock.reset_test_hooks()

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    caption = (
        "Discover export-ready steel for global buyers. We ship worldwide. "
        "Price is $99 at https://example.com/catalog. Contact us today."
    )
    idem_key = f"idem-{stamp}-{uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"AI Idem {stamp}", status="active", plan="trial")
        user = TenantUser(
            id=uuid4(),
            tenant_id=tenant.id,
            email=f"ai-idem-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        client = Client(
            id=uuid4(),
            tenant_id=tenant.id,
            company_name=f"AI Idem Client {stamp}",
            business_category="manufacturing",
            status="active",
        )
        content = ContentItem(
            id=uuid4(),
            client_id=client.id,
            platforms=["telegram"],
            status="draft",
            caption_long_en=caption,
            hashtags="#export",
        )
        db.add(tenant)
        await db.commit()
        db.add_all([user, client])
        await db.commit()
        db.add(content)
        await db.commit()

        profile = await BrandProfileService.create_profile(
            db,
            tenant.id,
            name=f"Idem Brand {stamp}",
            draft={
                "locale": "en",
                "company_name": "Acme",
                "company_description": "Steel export",
                "tone_traits": ["clear"],
            },
            created_by=user.id,
        )
        version = await BrandProfileService.publish(db, tenant.id, profile.id, created_by=user.id)
        await db.commit()

        mock.reset_test_hooks()
        req_body = AdaptRequest(
            content_id=content.id,
            platforms=["telegram"],
            locales=["en"],
            length_profiles=["standard"],
            brand_profile_version_id=version.id,
            quality_mode="standard",
            idempotency_key=idem_key,
        )
        first = await AIContentAdaptationService.adapt(
            db, tenant.id, req_body, requested_by=user.id,
        )
        await db.commit()
        calls_after_first = mock.call_count
        first_id = str(first.get("request_id"))
        record("first_adapt_ok", first.get("status") in {"completed", "partial", "validation_failed"}, str(first.get("status")))
        record("first_provider_called", calls_after_first >= 1, str(calls_after_first))

        second = await AIContentAdaptationService.adapt(
            db, tenant.id, req_body, requested_by=user.id,
        )
        await db.commit()
        calls_after_second = mock.call_count
        second_id = str(second.get("request_id"))

        record("idempotent_same_request_id", first_id == second_id, f"{first_id[:8]}…")
        record(
            "idempotent_no_duplicate_provider_calls",
            calls_after_second == calls_after_first,
            f"first={calls_after_first} second={calls_after_second}",
        )
        record("idempotent_same_status", first.get("status") == second.get("status"))

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
