"""Event/signal leakage verification for Governed AI Content Adaptation.

Proves domain activity events and marketing signals contain no captions,
prompts, system instructions, API keys, or JWTs.

Run from backend/:  python scripts/verify_ai_content_signals.py
"""
from __future__ import annotations

import json
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
    from sqlalchemy import select

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
    from app.models.intelligence import TenantMarketingSignal
    from app.models.platform_event import TenantActivityEvent
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
    from app.services.intelligence.types import SIGNAL_TYPES

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

    marker = f"AI-SIG-MARKER-{stamp}-NEVER-LEAK"
    caption = (
        f"{marker} Discover export-ready steel components for global buyers. "
        "Price is $99 at https://example.com/catalog. Contact us today for a quote."
    )
    fake_key = "sk-abcdefghijklmnopqrstuvwxyz123456"

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"AI Sig {stamp}", status="active", plan="trial")
        user = TenantUser(
            id=uuid4(),
            tenant_id=tenant.id,
            email=f"ai-sig-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        client = Client(
            id=uuid4(),
            tenant_id=tenant.id,
            company_name=f"AI Sig Client {stamp}",
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
            name=f"Sig Brand {stamp}",
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

        result = await AIContentAdaptationService.adapt(
            db,
            tenant.id,
            AdaptRequest(
                content_id=content.id,
                platforms=["telegram"],
                locales=["en"],
                length_profiles=["standard"],
                brand_profile_version_id=version.id,
                quality_mode="standard",
            ),
            requested_by=user.id,
        )
        await db.commit()
        record(
            "adapt_completed_for_signals",
            result.get("status") in {"completed", "partial", "validation_failed"},
            str(result.get("status")),
        )

        wanted_signals = {
            "ai.content_adaptation_completed",
            "ai.content_adaptation_failed",
            "brand.profile_published",
        }
        record("ai_signal_types_registered", wanted_signals.issubset(set(SIGNAL_TYPES)))

        events = list(
            (
                await db.execute(
                    select(TenantActivityEvent).where(
                        TenantActivityEvent.tenant_id == tenant.id,
                        TenantActivityEvent.event_type.like("ai.%"),
                    )
                )
            ).scalars().all()
        )
        brand_events = list(
            (
                await db.execute(
                    select(TenantActivityEvent).where(
                        TenantActivityEvent.tenant_id == tenant.id,
                        TenantActivityEvent.event_type == "brand.profile_published",
                    )
                )
            ).scalars().all()
        )
        record("ai_activity_events_emitted", len(events) >= 1, str(len(events)))
        record("brand_publish_event_emitted", len(brand_events) >= 1, str(len(brand_events)))

        signals = list(
            (
                await db.execute(
                    select(TenantMarketingSignal).where(
                        TenantMarketingSignal.tenant_id == tenant.id,
                        TenantMarketingSignal.signal_type.in_([
                            "ai.content_adaptation_completed",
                            "ai.content_adaptation_failed",
                            "ai.factual_validation_failed",
                            "brand.profile_published",
                        ]),
                    )
                )
            ).scalars().all()
        )
        record("ai_marketing_signals_present", len(signals) >= 1, str(len(signals)))

        leak_needles = [
            marker,
            "export-ready steel",
            "Contact us today",
            fake_key,
            "system prompt",
            "You are a governed",
            "eyJ",
        ]

        def _blob_leaks(obj) -> bool:
            text = json.dumps(obj, default=str).lower() if not isinstance(obj, str) else obj.lower()
            return any(n.lower() in text for n in leak_needles)

        event_leak = any(_blob_leaks(e.payload) or _blob_leaks(e.description or "") for e in events + brand_events)
        signal_leak = any(_blob_leaks(s.metadata_json or {}) for s in signals)
        record("no_caption_leak_in_ai_events", not event_leak)
        record("no_caption_leak_in_ai_signals", not signal_leak)
        record(
            "no_prompt_or_key_leak",
            not event_leak and not signal_leak,
        )

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
