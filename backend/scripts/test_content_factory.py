"""Unit tests for AI Content Factory pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.content_factory_constants import CONTENT_CATEGORIES, SUPPORTED_LANGUAGES
from app.services.content_factory_platform_service import adapt_for_platform, build_platform_variants
from app.services.content_factory_quality_service import score_content


def test_supported_languages():
    assert "zh" in SUPPORTED_LANGUAGES
    assert "ru" in SUPPORTED_LANGUAGES


def test_content_categories_manufacturer_focus():
    assert "product_announcement" in CONTENT_CATEGORIES
    assert "export_opportunity" in CONTENT_CATEGORIES


def test_quality_scoring():
    result = score_content(
        captions={
            "caption_short_en": "New export line from our factory",
            "caption_long_en": "Premium manufacturing with ISO certification. Contact us for MOQ and lead time details.",
        },
        hashtags="#export #manufacturing #quality #B2B #factory",
        headline="Introducing our new export product line",
        cta="Contact us for catalog",
        platforms=["linkedin", "telegram", "wechat"],
        target_languages=["en", "ru", "zh"],
        content_category="product_announcement",
    )
    assert result["overall_score"] >= 50
    assert "quality_score" in result
    assert isinstance(result["recommendations"], list)


def test_platform_adaptation_telegram():
    captions = {
        "caption_long_en": "Factory tour showing our production line and quality control.",
        "caption_short_en": "Factory tour — quality at every step",
    }
    adapted = adapt_for_platform(
        platform="telegram",
        captions=captions,
        headline="See our factory",
        hashtags="#factory #export",
        cta="Message us for catalog",
    )
    assert adapted["platform"] == "telegram"
    assert "Factory tour" in adapted["text"]
    assert len(adapted["text"]) <= 4096


def test_platform_adaptation_wechat():
    captions = {
        "caption_long_zh": "欢迎了解我们的出口产品线，品质保证，支持小批量订购。",
    }
    adapted = adapt_for_platform(platform="wechat", captions=captions, headline=None, hashtags=None, cta="欢迎咨询")
    assert adapted["format"] == "wechat_moments"
    assert "出口" in adapted["text"]


def test_build_platform_variants():
    captions = {"caption_long_en": "Export-ready products with fast lead times."}
    variants = build_platform_variants(
        platforms=["telegram", "linkedin", "whatsapp_status"],
        captions=captions,
        headline="Export catalog",
        hashtags="#export",
        cta="Inquire now",
    )
    assert "telegram" in variants
    assert "whatsapp_status" in variants
    assert variants["whatsapp_status"]["text"]


def test_quality_missing_languages():
    result = score_content(
        captions={"caption_long_en": "Short"},
        hashtags="#one",
        headline=None,
        cta=None,
        platforms=["instagram"],
        target_languages=["en", "ru", "uz", "zh"],
    )
    assert any("language" in r.lower() or "caption" in r.lower() or "CTA" in r or "hashtag" in r.lower()
               for r in result["recommendations"])


if __name__ == "__main__":
    test_supported_languages()
    test_content_categories_manufacturer_focus()
    test_quality_scoring()
    test_platform_adaptation_telegram()
    test_platform_adaptation_wechat()
    test_build_platform_variants()
    test_quality_missing_languages()
    print("All content factory tests passed.")
