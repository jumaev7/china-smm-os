"""Unit tests for Telegram ingestion pipeline (classification, enrichment, quality)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.content_classification_service import classify_content, CLASSIFICATION_CATEGORIES
from app.services.content_enrichment_service import enrich_content
from app.services.content_quality_service import run_quality_checks
from app.services.telegram_ingestion_service import (
    TelegramIngestionService,
    extract_forward_info,
)


def test_classify_product():
    result = classify_content(caption="New product catalog — model X200, price $499")
    assert result["category"] == "product"
    assert result["category"] in CLASSIFICATION_CATEGORIES


def test_classify_promotion():
    result = classify_content(caption="Big discount sale 30% off this week!")
    assert result["category"] == "promotion"


def test_enrich_content():
    client = SimpleNamespace(
        company_name="Test Factory",
        hashtag_preferences="#factory #madeinchina",
        cta_phone="+998901234567",
        cta_telegram=None,
        cta_website=None,
    )
    data = enrich_content(
        client=client,
        caption="Factory tour video",
        internal_notes=None,
        classification="factory",
        target_languages=["ru", "en"],
    )
    assert data["title"]
    assert "ru" in data["captions"]
    assert data["cta"]


def test_quality_missing_caption():
    item = SimpleNamespace(
        content_classification="product",
        telegram_original_caption=None,
        internal_notes="",
        suggestions_json=None,
        telegram_excluded=False,
        caption_short_ru=None,
        caption_long_ru=None,
        caption_short_uz=None,
        caption_long_uz=None,
        caption_short_en=None,
        caption_long_en=None,
    )
    warnings = run_quality_checks(
        content_item=item,
        media_file=None,
        caption=None,
        target_languages=["ru", "en"],
    )
    ids = {w["id"] for w in warnings}
    assert "missing_caption" in ids


def test_forward_info():
    msg = {
        "forward_origin": {
            "type": "channel",
            "chat": {"title": "Supplier News"},
        }
    }
    assert "Supplier News" in (extract_forward_info(msg) or "")


def test_feedback_message():
    item = SimpleNamespace(status="needs_review", id=uuid4())
    text = TelegramIngestionService.build_feedback_message(
        content_item=item,
        media_count=2,
        caption_detected=True,
        warnings=[],
        dashboard_url="http://localhost:3000/content/abc",
    )
    assert "Content received ✅" in text
    assert "Needs Review" in text
    assert "2 files" in text


def main() -> None:
    tests = [
        test_classify_product,
        test_classify_promotion,
        test_enrich_content,
        test_quality_missing_caption,
        test_forward_info,
        test_feedback_message,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK  {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed.")


if __name__ == "__main__":
    main()
