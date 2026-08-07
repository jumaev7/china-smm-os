"""Re-run governed AI enrichment for one Telegram content item.

This is an operator repair tool: it never approves, schedules, or publishes.
Existing caption fields are replaced only when --replace-existing-generated is
explicitly supplied and the stored suggestions came from a generated method.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.content import ContentItem
from app.services.content_enrichment_service import enrich_with_ai, suggestions_to_json
from app.services.telegram_ingestion_service import apply_suggestions_to_content, _short_caption
from app.services.telegram_service import _strip_post_command


_CAPTION_FIELDS = (
    "caption_short_ru", "caption_long_ru",
    "caption_short_uz", "caption_long_uz",
    "caption_short_en", "caption_long_en",
)


async def reprocess(content_id: UUID, *, replace_existing_generated: bool) -> dict:
    async with AsyncSessionLocal() as db:
        item = await db.get(ContentItem, content_id)
        if item is None:
            raise SystemExit(f"Content item not found: {content_id}")
        if not (item.source or "").startswith("telegram"):
            raise SystemExit("Refusing to reprocess a non-Telegram content item")
        client = await db.scalar(select(Client).where(Client.id == item.client_id))
        if client is None:
            raise SystemExit("Content client not found")

        source = _strip_post_command(item.telegram_original_caption or "")
        suggestions = await enrich_with_ai(
            client=client,
            caption=source,
            internal_notes=item.internal_notes,
            classification=item.content_classification or "other",
            target_languages=["ru", "uz", "en"],
        )
        if not suggestions or suggestions.get("method") != "governed_ai":
            raise SystemExit("Governed AI enrichment did not return a valid result; no changes saved")

        old_method = None
        if item.suggestions_json:
            try:
                old_method = json.loads(item.suggestions_json).get("method")
            except (TypeError, ValueError, json.JSONDecodeError):
                old_method = None
        if replace_existing_generated:
            if old_method not in ("rule_based", "governed_ai"):
                raise SystemExit("Refusing to replace fields not marked as generated")
            for field in _CAPTION_FIELDS:
                setattr(item, field, None)
            item.hashtags = None

        item.telegram_original_caption = source or None
        item.suggestions_json = suggestions_to_json(suggestions)
        apply_suggestions_to_content(item, suggestions)
        await db.commit()
        return {
            "content_id": str(item.id),
            "status": item.status,
            "method": suggestions["method"],
            "platforms": item.platforms,
            "languages": sorted(suggestions.get("captions", {}).keys()),
            "caption_lengths": {
                lang: len(text)
                for lang, text in suggestions.get("captions", {}).items()
            },
            "published": item.status == "published",
        }


async def normalize_short_captions(content_id: UUID) -> dict:
    """Repair short generated fields without making an AI/provider request."""
    async with AsyncSessionLocal() as db:
        item = await db.get(ContentItem, content_id)
        if item is None:
            raise SystemExit(f"Content item not found: {content_id}")
        lengths: dict[str, int] = {}
        for lang in ("ru", "uz", "en"):
            long_text = getattr(item, f"caption_long_{lang}", None)
            if long_text:
                short_text = _short_caption(long_text)
                setattr(item, f"caption_short_{lang}", short_text)
                lengths[lang] = len(short_text)
        await db.commit()
        return {"content_id": str(item.id), "short_caption_lengths": lengths, "published": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("content_id", type=UUID)
    parser.add_argument("--replace-existing-generated", action="store_true")
    parser.add_argument("--normalize-short-only", action="store_true")
    args = parser.parse_args()
    if args.normalize_short_only:
        print(json.dumps(asyncio.run(normalize_short_captions(args.content_id)), ensure_ascii=False, indent=2))
        return
    print(json.dumps(asyncio.run(reprocess(
        args.content_id,
        replace_existing_generated=args.replace_existing_generated,
    )), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
