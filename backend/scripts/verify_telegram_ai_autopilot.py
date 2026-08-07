"""Verify governed AI hooks used by Telegram ingestion without network calls."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.ai_platform.provider_registry import get_mock_provider
from app.services.content_classification_service import classify_with_ai
from app.services.content_enrichment_service import enrich_with_ai


async def main() -> None:
    original_enabled = settings.AI_PLATFORM_ENABLED
    original_provider = settings.AI_DEFAULT_PROVIDER
    provider = get_mock_provider()
    provider.reset_test_hooks()
    try:
        settings.AI_PLATFORM_ENABLED = True
        settings.AI_DEFAULT_PROVIDER = "mock"
        provider.set_custom_output({"category": "product", "confidence": 0.91})
        classified = await classify_with_ai(
            caption="New export product catalog",
            internal_notes=None,
            tenant_id=str(uuid4()),
        )
        assert classified == {"category": "product", "confidence": 0.91, "method": "governed_ai"}

        provider.set_custom_output({
            "title": "New export product",
            "captions": {
                "ru": "Новый экспортный продукт.",
                "uz": "Yangi eksport mahsuloti.",
                "en": "A new export product.",
            },
            "hashtags": "#export #product",
            "cta": "Contact us for details",
            "target_platforms": ["telegram", "instagram", "facebook"],
        })
        client = SimpleNamespace(
            tenant_id=uuid4(),
            company_name="Autopilot Test Client",
            business_category="manufacturing",
            tone_of_voice="professional",
            cta_telegram=None,
            cta_phone=None,
            cta_website=None,
            hashtag_preferences="#export",
        )
        enriched = await enrich_with_ai(
            client=client,
            caption="New export product catalog",
            internal_notes=None,
            classification="product",
            target_languages=["ru", "uz", "en"],
        )
        assert enriched and enriched["method"] == "governed_ai"
        assert enriched["captions"]["en"] == "A new export product."
        assert enriched["target_platforms"] == ["telegram", "instagram", "facebook"]
        print("OK Telegram AI autopilot classification and multilingual enrichment")
    finally:
        provider.reset_test_hooks()
        settings.AI_PLATFORM_ENABLED = original_enabled
        settings.AI_DEFAULT_PROVIDER = original_provider


if __name__ == "__main__":
    asyncio.run(main())
