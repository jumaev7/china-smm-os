"""Focused hardening regressions for Chinese Content Pipeline 2.0."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.content import GeneratedContent
from app.services.client_review_telegram_service import _primary_caption
from app.services.content_service import ContentService
from app.services.publish_service import _pick_caption
from app.services.content_repurpose_service import _GENERATE_SYSTEM
from app.services.telegram_ingestion_service import apply_suggestions_to_content


class _FakeDb:
    async def commit(self):
        return None


def test_generated_content_accepts_zh():
    payload = GeneratedContent(
        caption_short_ru="ru",
        caption_short_uz="uz",
        caption_short_en="en",
        caption_short_zh="zh-short",
        caption_long_ru="ru long",
        caption_long_uz="uz long",
        caption_long_en="en long",
        caption_long_zh="zh long",
        hashtags="#tags",
    )
    dumped = payload.model_dump(exclude_none=True)
    assert dumped["caption_short_zh"] == "zh-short"
    assert dumped["caption_long_zh"] == "zh long"


async def _run_apply_generated_preserve_zh() -> None:
    item = SimpleNamespace(
        id=uuid4(),
        status="draft",
        caption_short_zh="existing zh short",
        caption_long_zh="existing zh long",
        caption_short_ru=None,
        caption_long_ru=None,
        caption_short_uz=None,
        caption_long_uz=None,
        caption_short_en=None,
        caption_long_en=None,
        hashtags=None,
    )
    db = _FakeDb()

    async def _fake_get(_db, _content_id):
        return item

    original_get = ContentService.get
    try:
        ContentService.get = staticmethod(_fake_get)
        generated = GeneratedContent(
            caption_short_ru="new ru short",
            caption_short_uz="new uz short",
            caption_short_en="new en short",
            caption_long_ru="new ru long",
            caption_long_uz="new uz long",
            caption_long_en="new en long",
            hashtags="#new",
            # Explicitly omitted zh -> must not erase existing zh.
        )
        await ContentService.apply_generated(db, item.id, generated)
    finally:
        ContentService.get = original_get

    assert item.caption_short_zh == "existing zh short"
    assert item.caption_long_zh == "existing zh long"
    assert item.caption_short_ru == "new ru short"
    assert item.status == "ready"


def test_apply_generated_preserves_existing_zh_when_absent_in_payload():
    asyncio.run(_run_apply_generated_preserve_zh())


def test_publish_caption_fallback_preserves_existing_order_and_allows_zh_only():
    full = SimpleNamespace(
        caption_long_ru="ru long",
        caption_long_uz="uz long",
        caption_long_en="en long",
        caption_long_zh="zh long",
        caption_short_ru=None,
        caption_short_uz=None,
        caption_short_en=None,
        caption_short_zh=None,
    )
    assert _pick_caption(full) == "ru long"

    no_ru = SimpleNamespace(
        caption_long_ru=None,
        caption_long_uz="uz long",
        caption_long_en="en long",
        caption_long_zh="zh long",
        caption_short_ru=None,
        caption_short_uz=None,
        caption_short_en=None,
        caption_short_zh=None,
    )
    assert _pick_caption(no_ru) == "uz long"

    zh_only = SimpleNamespace(
        caption_long_ru=None,
        caption_long_uz=None,
        caption_long_en=None,
        caption_long_zh="zh only",
        caption_short_ru=None,
        caption_short_uz=None,
        caption_short_en=None,
        caption_short_zh=None,
    )
    assert _pick_caption(zh_only) == "zh only"


def test_telegram_suggestions_materialize_zh_without_overwriting_existing():
    item = SimpleNamespace(
        platforms=[],
        caption_short_ru=None,
        caption_long_ru=None,
        caption_short_uz=None,
        caption_long_uz=None,
        caption_short_en=None,
        caption_long_en=None,
        caption_short_zh="existing short",
        caption_long_zh="existing long",
        hashtags=None,
    )
    apply_suggestions_to_content(item, {
        "target_platforms": ["telegram"],
        "captions": {"zh": "新的中文文案"},
        "hashtags": "#zh",
    })
    # Existing zh should remain untouched by enrichment materializer.
    assert item.caption_short_zh == "existing short"
    assert item.caption_long_zh == "existing long"
    assert item.platforms == ["telegram"]
    assert item.hashtags == "#zh"


def test_client_review_primary_caption_supports_zh_fallback():
    item = SimpleNamespace(
        caption_short_ru=None,
        caption_long_ru=None,
        caption_short_uz=None,
        caption_long_uz=None,
        caption_short_en=None,
        caption_long_en=None,
        caption_short_zh="中文短文案",
        caption_long_zh=None,
    )
    assert "中文短文案" in _primary_caption(item)


def test_repurpose_generation_contract_mentions_zh_fields():
    assert "caption_short_zh" in _GENERATE_SYSTEM
    assert "caption_long_zh" in _GENERATE_SYSTEM
