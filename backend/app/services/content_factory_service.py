"""AI Content Factory — generate multiple content angles from one media asset."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.client_scope_guard import guard_resource_client_id
from app.core.config import settings
from app.core.storage import storage
from app.models.client import Client
from app.models.content import ContentItem
from app.models.content_factory import ContentFactory, ContentFactoryItem
from app.schemas.content import ContentCreate, GeneratedContent, PLATFORMS
from app.schemas.content_factory import ContentFactoryGenerateRequest, ContentFactoryTextGenerateRequest
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.brand_profile import brand_profile_from_client
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.client_service import ClientService
from app.services.content_enrichment_service import SUPPORTED_LANGUAGES as ENRICH_LANGS
from app.services.content_factory_constants import (
    CONTENT_CATEGORIES,
    FACTORY_CONTENT_TYPES,
    FACTORY_PLATFORMS,
    SUPPORTED_LANGUAGES,
    _TYPE_PLATFORMS,
    _TYPE_ROTATION,
)
from app.services.content_factory_platform_service import build_platform_variants
from app.services.content_factory_quality_service import score_content
from app.services.content_service import ContentService, CalendarService
from app.services.media_service import MediaService
from app.schemas.content import CalendarEntryCreate

logger = logging.getLogger(__name__)

CONTENT_FACTORY_SOURCE = "content_factory"
CONTENT_FACTORY_MARKER = "[Content Factory AI]"
FACTORY_STATUSES = frozenset({"draft", "generated", "failed"})

_CATEGORY_ANGLES: dict[str, list[tuple[str, str]]] = {
    "product_announcement": [
        ("New product launch", "Highlight export-ready specs and MOQ"),
        ("Catalog spotlight", "Feature key product benefits for buyers"),
    ],
    "factory_news": [
        ("Factory update", "Share production capacity or certification news"),
        ("Team milestone", "Celebrate manufacturing achievement"),
    ],
    "production_process": [
        ("Behind the scenes", "Show quality control and craftsmanship"),
        ("Production line", "Demonstrate scale and precision"),
    ],
    "customer_success": [
        ("Client story", "Social proof from export partner"),
        ("Case study", "Results delivered to international buyer"),
    ],
    "promotion": [
        ("Limited offer", "Time-bound export promotion"),
        ("Volume discount", "MOQ-based pricing advantage"),
    ],
    "exhibition": [
        ("Trade show", "Meet us at upcoming exhibition"),
        ("Booth invite", "Schedule meeting at expo"),
    ],
    "educational": [
        ("Industry insight", "Educate buyers on manufacturing standards"),
        ("How it's made", "Explain production expertise"),
    ],
    "export_opportunity": [
        ("Market opening", "New export corridor opportunity"),
        ("Partner sought", "Seeking distributors in target region"),
    ],
    "corporate_update": [
        ("Company news", "Corporate milestone or partnership"),
        ("Sustainability", "ESG and responsible manufacturing"),
    ],
    "other": [
        ("Brand story", "Connect visual to company values"),
        ("Product benefit", "Focus on customer outcome"),
    ],
}

_GENERATE_SYSTEM = """\
You are an SMM content strategist for manufacturers and exporters.
From ONE source input, propose multiple distinct content variations for international B2B buyers.

Return ONLY JSON:
{
  "variations": [
    {
      "content_type": "reel|post|story|carousel|article|telegram|linkedin",
      "theme": "short theme label",
      "angle": "1-2 sentences — creative angle",
      "title": "internal working title",
      "headline": "public headline hook",
      "platforms": ["telegram", "facebook", "linkedin", "instagram", "wechat", "whatsapp_status"],
      "caption_short_ru": "≤150 chars",
      "caption_short_uz": "≤150 chars",
      "caption_short_en": "≤150 chars",
      "caption_short_zh": "≤150 chars Simplified Chinese",
      "caption_long_ru": "200-400 chars with CTA",
      "caption_long_uz": "200-400 chars with CTA",
      "caption_long_en": "200-400 chars with CTA",
      "caption_long_zh": "200-400 chars Simplified Chinese with CTA",
      "hashtags": "#tag1 #tag2 ... (10-15 tags)",
      "cta_suggestion": "specific call-to-action"
    }
  ]
}

Rules:
- Each variation must have a DISTINCT angle
- Match platforms to format; include wechat for Chinese buyers, whatsapp_status for quick updates
- Use client brand and knowledge base — do not invent unsupported claims
- Never mention AI or internal tools in captions
- Target languages requested: {languages}
- Content category: {category}
"""


def _normalize_platforms(raw: Any, content_type: str) -> list[str]:
    defaults = _TYPE_PLATFORMS.get(content_type, ["instagram", "telegram"])
    if not isinstance(raw, list):
        return [p for p in defaults if p in FACTORY_PLATFORMS]
    out: list[str] = []
    for p in raw:
        key = str(p).lower().strip()
        if key in FACTORY_PLATFORMS and key not in out:
            out.append(key)
        elif key in PLATFORMS and key not in out:
            out.append(key)
    return out or defaults


def _normalize_content_type(raw: Any, index: int) -> str:
    key = str(raw or "").lower().strip()
    if key in FACTORY_CONTENT_TYPES:
        return key
    return _TYPE_ROTATION[index % len(_TYPE_ROTATION)]


def _normalize_languages(raw: list[str] | None) -> list[str]:
    if not raw:
        return list(SUPPORTED_LANGUAGES)
    return [l for l in raw if l in SUPPORTED_LANGUAGES] or list(SUPPORTED_LANGUAGES)


def _preview_from_captions(captions: dict[str, Any]) -> str:
    for field in (
        "caption_long_ru", "caption_short_ru",
        "caption_long_en", "caption_short_en",
        "caption_long_zh", "caption_short_zh",
    ):
        val = str(captions.get(field) or "").strip()
        if val:
            return val[:280]
    return ""


def _ensure_generated_payload(raw: dict[str, Any], *, fallback_title: str) -> dict[str, str]:
    fb = fallback_title[:120]
    fields = (
        "caption_short_ru", "caption_short_uz", "caption_short_en",
        "caption_long_ru", "caption_long_uz", "caption_long_en",
        "hashtags",
    )
    out: dict[str, str] = {}
    for field in fields:
        val = str(raw.get(field) or "").strip()
        if not val:
            if field == "hashtags":
                val = "#export #manufacturing #quality"
            elif field.startswith("caption_short"):
                val = fb[:150]
            else:
                val = fb[:400]
        out[field] = val
    return out


def _serialize_item(item: ContentFactoryItem) -> dict[str, Any]:
    platforms = _parse_json_list(item.platforms_json)
    scores = _parse_json_dict(item.quality_scores_json)
    variants = _parse_json_dict(item.platform_variants_json)
    captions = _parse_json_dict(item.captions_json) or {}
    return {
        "id": item.id,
        "content_type": item.content_type,
        "theme": item.theme,
        "angle": item.angle,
        "title": item.title,
        "headline": item.headline,
        "platforms": platforms,
        "hashtags": item.hashtags,
        "cta_suggestion": item.cta_suggestion,
        "preview_caption": item.preview_caption,
        "captions": captions,
        "generated_content_id": item.generated_content_id,
        "review_status": item.review_status or "generated",
        "quality_scores": scores,
        "platform_variants": variants,
        "scheduled_for": item.scheduled_for,
        "created_at": item.created_at,
    }


def _serialize_factory(factory: ContentFactory) -> dict[str, Any]:
    media = factory.source_media
    media_url = storage.get_url(media.storage_path) if media else None
    company_name = factory.client.company_name if factory.client else None
    return {
        "id": factory.id,
        "client_id": factory.client_id,
        "company_name": company_name,
        "source_media_id": factory.source_media_id,
        "source_media_url": media_url,
        "source_media_type": media.file_type if media else None,
        "source_content_id": factory.source_content_id,
        "status": factory.status,
        "input_type": factory.input_type,
        "input_text": factory.input_text,
        "content_category": factory.content_category,
        "target_languages": _parse_json_list(factory.target_languages_json),
        "items": [_serialize_item(i) for i in factory.items],
        "created_at": factory.created_at,
    }


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_json_dict(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _heuristic_variations(
    *,
    client: Client,
    media_type: str,
    count: int,
    content_category: str = "other",
    target_languages: list[str] | None = None,
    input_text: str | None = None,
) -> list[dict[str, Any]]:
    angles = _CATEGORY_ANGLES.get(content_category, _CATEGORY_ANGLES["other"])
    langs = target_languages or list(SUPPORTED_LANGUAGES)
    variations: list[dict[str, Any]] = []
    media_label = "video" if media_type == "video" else "document" if media_type == "document" else "photo"
    context = (input_text or "")[:200]

    for i in range(count):
        content_type = _normalize_content_type(None, i)
        platforms = _normalize_platforms(None, content_type)
        theme, angle_base = angles[i % len(angles)]
        angle = f"{angle_base} using this {media_label} for {client.company_name}."
        if context:
            angle = f"{angle_base}. Context: {context}"
        title = f"{theme} — {content_type.title()}"
        name = client.company_name

        captions: dict[str, str] = {}
        if "ru" in langs:
            captions.update({
                "caption_short_ru": f"{name}: {theme} — узнайте больше!",
                "caption_long_ru": f"{angle} {name} — надёжный экспортный партнёр. Свяжитесь с нами.",
            })
        if "uz" in langs:
            captions.update({
                "caption_short_uz": f"{name}: {theme} — batafsil!",
                "caption_long_uz": f"{angle} {name} — ishonchli eksport hamkori.",
            })
        if "en" in langs:
            captions.update({
                "caption_short_en": f"{name}: {theme} — learn more!",
                "caption_long_en": f"{angle} {name} — trusted export manufacturing partner.",
            })
        if "zh" in langs:
            captions.update({
                "caption_short_zh": f"{name}：{theme} — 了解更多！",
                "caption_long_zh": f"{angle} {name} — 可靠的出口制造合作伙伴。欢迎咨询。",
            })

        variations.append({
            "content_type": content_type,
            "theme": theme,
            "angle": angle,
            "title": title,
            "headline": f"{name} — {theme}",
            "platforms": platforms,
            "cta_suggestion": "Contact us for export catalog and MOQ details",
            "hashtags": f"#export #manufacturing #{name.replace(' ', '')} #quality #B2B",
            **captions,
        })
    return variations


async def _ai_variations(
    db: AsyncSession,
    *,
    client: Client,
    media_type: str,
    media_filename: str,
    count: int,
    content_category: str,
    target_languages: list[str],
    input_text: str | None = None,
) -> list[dict[str, Any]]:
    if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
        return _heuristic_variations(
            client=client,
            media_type=media_type,
            count=count,
            content_category=content_category,
            target_languages=target_languages,
            input_text=input_text,
        )

    _validate_api_key()
    kb_block = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, max_chars=3000, context="content_factory",
    )
    brand = brand_profile_from_client(client)
    brand_lines = "\n".join(f"- {k}: {v}" for k, v in brand.items() if v) if brand else ""

    system = _GENERATE_SYSTEM.format(
        languages=", ".join(target_languages),
        category=content_category,
    )
    user_prompt = f"""\
CLIENT: {client.company_name}
CATEGORY: {client.business_category}
CONTENT STYLE: {client.content_style}
CONTENT CATEGORY: {content_category}
SOURCE MEDIA: {media_type} file "{media_filename}"
INPUT TEXT: {(input_text or '(none)')[:2000]}
VARIATIONS NEEDED: {count}
TARGET LANGUAGES: {', '.join(target_languages)}

{brand_lines}

{kb_block or ''}

Generate exactly {count} distinct content variations.
Each variation needs captions in requested languages plus headline, CTA, hashtags.
"""

    openai = get_openai()
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.65,
        max_tokens=4000,
        response_format={"type": "json_object"},
    )
    parsed = _extract_json(response.choices[0].message.content or "{}")
    raw_items = parsed.get("variations") or parsed.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        return _heuristic_variations(
            client=client, media_type=media_type, count=count,
            content_category=content_category, target_languages=target_languages,
            input_text=input_text,
        )

    variations: list[dict[str, Any]] = []
    caption_fields = [
        "caption_short_ru", "caption_short_uz", "caption_short_en", "caption_short_zh",
        "caption_long_ru", "caption_long_uz", "caption_long_en", "caption_long_zh",
    ]
    for i, raw in enumerate(raw_items[:count]):
        if not isinstance(raw, dict):
            continue
        content_type = _normalize_content_type(raw.get("content_type"), i)
        platforms = _normalize_platforms(raw.get("platforms"), content_type)
        captions = {f: str(raw.get(f) or "")[:2000] for f in caption_fields if raw.get(f)}
        variations.append({
            "content_type": content_type,
            "theme": str(raw.get("theme") or f"Variation {i + 1}").strip()[:500],
            "angle": str(raw.get("angle") or raw.get("theme") or "").strip(),
            "title": str(raw.get("title") or raw.get("theme") or f"Variation {i + 1}").strip()[:255],
            "headline": str(raw.get("headline") or "").strip()[:500],
            "platforms": platforms,
            "cta_suggestion": str(raw.get("cta_suggestion") or "Contact us for details").strip(),
            "hashtags": str(raw.get("hashtags") or "")[:500],
            **captions,
        })

    while len(variations) < count:
        extra = _heuristic_variations(
            client=client, media_type=media_type, count=count - len(variations),
            content_category=content_category, target_languages=target_languages,
            input_text=input_text,
        )
        variations.extend(extra)

    return variations[:count]


def _build_item_from_variation(
    factory_id: UUID,
    var: dict[str, Any],
    *,
    target_languages: list[str],
    content_category: str,
) -> ContentFactoryItem:
    caption_fields = [
        "caption_short_ru", "caption_short_uz", "caption_short_en", "caption_short_zh",
        "caption_long_ru", "caption_long_uz", "caption_long_en", "caption_long_zh",
    ]
    captions_payload = {k: var[k] for k in caption_fields if k in var}
    scores = score_content(
        captions=captions_payload,
        hashtags=var.get("hashtags"),
        headline=var.get("headline"),
        cta=var.get("cta_suggestion"),
        platforms=var.get("platforms") or [],
        target_languages=target_languages,
        content_category=content_category,
    )
    variants = build_platform_variants(
        platforms=var.get("platforms") or [],
        captions=captions_payload,
        headline=var.get("headline"),
        hashtags=var.get("hashtags"),
        cta=var.get("cta_suggestion"),
    )
    return ContentFactoryItem(
        factory_id=factory_id,
        content_type=var["content_type"],
        theme=var["theme"],
        angle=var["angle"],
        title=var["title"],
        headline=var.get("headline"),
        platforms_json=json.dumps(var.get("platforms") or []),
        hashtags=var.get("hashtags"),
        cta_suggestion=var.get("cta_suggestion"),
        preview_caption=_preview_from_captions(var),
        captions_json=json.dumps(captions_payload, ensure_ascii=False),
        quality_scores_json=json.dumps(scores, ensure_ascii=False),
        platform_variants_json=json.dumps(variants, ensure_ascii=False),
        review_status="generated",
    )


class ContentFactoryService:
    @staticmethod
    async def generate(
        db: AsyncSession,
        data: ContentFactoryGenerateRequest,
    ) -> dict[str, Any]:
        client = await ClientService.get(db, data.client_id)
        guard_resource_client_id(client.id)

        media = None
        if data.source_media_id:
            media = await MediaService.get(db, data.source_media_id)
            if media.client_id != client.id:
                raise HTTPException(status_code=400, detail="Media does not belong to this client")

        if not media and not data.input_text:
            raise HTTPException(status_code=400, detail="Provide source_media_id or input_text")

        if data.source_content_id:
            src = await ContentService.get(db, data.source_content_id)
            if src.client_id != client.id:
                raise HTTPException(status_code=400, detail="Source content does not belong to this client")

        category = data.content_category or "other"
        if category not in CONTENT_CATEGORIES:
            category = "other"
        langs = _normalize_languages(data.target_languages)
        input_type = data.input_type or (media.file_type if media else "text")

        factory = ContentFactory(
            client_id=client.id,
            source_media_id=media.id if media else None,
            source_content_id=data.source_content_id,
            status="draft",
            input_type=input_type,
            input_text=data.input_text,
            content_category=category,
            target_languages_json=json.dumps(langs),
        )
        db.add(factory)
        await db.flush()

        media_type = media.file_type if media else "text"
        media_filename = media.original_filename if media else "text-input"

        try:
            variations = await _ai_variations(
                db,
                client=client,
                media_type=media_type,
                media_filename=media_filename,
                count=data.number_of_variations,
                content_category=category,
                target_languages=langs,
                input_text=data.input_text,
            )
        except Exception as exc:
            logger.warning("[Content Factory] AI failed, using fallback: %s", exc)
            variations = _heuristic_variations(
                client=client,
                media_type=media_type,
                count=data.number_of_variations,
                content_category=category,
                target_languages=langs,
                input_text=data.input_text,
            )

        for var in variations:
            db.add(_build_item_from_variation(
                factory.id, var, target_languages=langs, content_category=category,
            ))

        factory.status = "generated"
        await db.commit()

        logger.info(
            "[Content Factory] generated: factory=%s client=%s items=%s category=%s",
            factory.id, client.id, len(variations), category,
        )
        return await ContentFactoryService.get_factory(db, factory.id)

    @staticmethod
    async def generate_from_text(
        db: AsyncSession,
        data: ContentFactoryTextGenerateRequest,
    ) -> dict[str, Any]:
        req = ContentFactoryGenerateRequest(
            client_id=data.client_id,
            source_media_id=data.source_media_id,
            source_content_id=data.source_content_id,
            number_of_variations=data.number_of_variations,
            content_category=data.content_category,
            target_languages=data.target_languages,
            input_text=data.input_text,
            input_type=data.input_type or "text",
            target_platforms=data.target_platforms,
        )
        return await ContentFactoryService.generate(db, req)

    @staticmethod
    async def generate_from_telegram(
        db: AsyncSession,
        content_id: UUID,
        *,
        number_of_variations: int = 3,
        target_languages: list[str] | None = None,
    ) -> dict[str, Any]:
        content = await ContentService.get(db, content_id)
        guard_resource_client_id(content.client_id)

        if content.source not in ("telegram", "telegram_group"):
            raise HTTPException(status_code=400, detail="Content is not from Telegram")

        if not content.media_file_id:
            raise HTTPException(status_code=400, detail="Telegram content has no media")

        classification = content.content_classification or "other"
        category_map = {
            "product": "product_announcement",
            "factory": "factory_news",
            "production_process": "production_process",
            "promotion": "promotion",
            "customer_review": "customer_success",
            "company_news": "corporate_update",
            "exhibition_event": "exhibition",
            "educational_content": "educational",
        }
        category = category_map.get(classification, "other")

        input_text = (
            content.telegram_original_caption
            or content.internal_notes
            or ""
        )
        suggestions = _parse_json_dict(content.suggestions_json)
        if suggestions:
            input_text = f"{input_text}\n{suggestions.get('title', '')}"

        langs = _normalize_languages(target_languages or list(ENRICH_LANGS))

        req = ContentFactoryGenerateRequest(
            client_id=content.client_id,
            source_media_id=content.media_file_id,
            source_content_id=content.id,
            number_of_variations=number_of_variations,
            content_category=category,
            target_languages=langs,
            input_text=input_text[:3000],
            input_type="mixed",
        )
        result = await ContentFactoryService.generate(db, req)

        # Mark source content for approval workflow
        if content.status in ("needs_review", "needs_caption", "draft", "new"):
            content.status = "needs_review"
            await db.commit()

        return result

    @staticmethod
    async def get_factory(db: AsyncSession, factory_id: UUID) -> dict[str, Any]:
        factory = await ContentFactoryService._load_factory(db, factory_id)
        guard_resource_client_id(factory.client_id)
        return _serialize_factory(factory)

    @staticmethod
    async def create_draft_from_item(
        db: AsyncSession,
        item_id: UUID,
        *,
        generate_ai: bool = True,
    ) -> dict[str, Any]:
        result = await db.execute(
            select(ContentFactoryItem)
            .options(
                selectinload(ContentFactoryItem.factory).selectinload(ContentFactory.client),
                selectinload(ContentFactoryItem.factory).selectinload(ContentFactory.source_media),
            )
            .where(ContentFactoryItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Factory item not found")

        guard_resource_client_id(item.factory.client_id)

        if item.generated_content_id:
            return {
                "ok": True,
                "created": False,
                "message": "Draft already exists for this factory item",
                "factory_item_id": item_id,
                "content_id": item.generated_content_id,
                "ai_applied": False,
                "ai_error": None,
            }

        factory = item.factory
        platforms = _parse_json_list(item.platforms_json)
        publish_platforms = [p for p in platforms if p in PLATFORMS]
        if not publish_platforms:
            publish_platforms = ["telegram"]

        notes = (
            f"[Content Factory]\n"
            f"Title: {item.title}\n"
            f"Headline: {item.headline or ''}\n"
            f"Theme: {item.theme}\n"
            f"Angle: {item.angle}\n"
            f"Format: {item.content_type}\n"
            f"Category: {factory.content_category or 'other'}\n"
            f"Factory: {factory.id}"
        )

        content = await ContentService.create(
            db,
            ContentCreate(
                client_id=factory.client_id,
                media_file_id=factory.source_media_id,
                platforms=publish_platforms,
                internal_notes=notes,
                source=CONTENT_FACTORY_SOURCE,
            ),
        )

        ai_applied = False
        ai_error: str | None = None

        if generate_ai and item.captions_json:
            try:
                raw = json.loads(item.captions_json)
                payload = _ensure_generated_payload(raw, fallback_title=item.title)
                generated = GeneratedContent(**payload)
                await ContentService.apply_generated(db, content.id, generated)
                content_row = await ContentService.get(db, content.id)
                content_row.status = "needs_review"
                if factory.content_category:
                    content_row.content_classification = factory.content_category
                existing_notes = (content_row.internal_notes or "").rstrip()
                content_row.internal_notes = (
                    f"{existing_notes}\n{CONTENT_FACTORY_MARKER} Captions from factory variation."
                ).strip()
                await db.commit()
                ai_applied = True
            except Exception as exc:
                ai_error = str(exc)
                logger.warning(
                    "[Content Factory] caption apply failed: item=%s content=%s error=%s",
                    item_id, content.id, exc,
                )

        item.generated_content_id = content.id
        item.review_status = "needs_review"
        await db.commit()

        return {
            "ok": True,
            "created": True,
            "message": "Draft created — review before publish",
            "factory_item_id": item_id,
            "content_id": content.id,
            "ai_applied": ai_applied,
            "ai_error": ai_error,
        }

    @staticmethod
    async def schedule_item(
        db: AsyncSession,
        item_id: UUID,
        *,
        scheduled_for: datetime,
        platforms: list[str] | None = None,
    ) -> dict[str, Any]:
        item = await ContentFactoryService._get_item(db, item_id)
        guard_resource_client_id(item.factory.client_id)

        if not item.generated_content_id:
            draft_result = await ContentFactoryService.create_draft_from_item(db, item_id)
            item = await ContentFactoryService._get_item(db, item_id)
            if not item.generated_content_id:
                raise HTTPException(status_code=400, detail="Could not create content draft for scheduling")

        content_id = item.generated_content_id
        sched_date = scheduled_for.date()
        time_slot = scheduled_for.strftime("%H:%M")

        entry = await CalendarService.schedule(
            db,
            CalendarEntryCreate(
                content_item_id=content_id,
                scheduled_date=sched_date,
                time_slot=time_slot,
                scheduled_for=scheduled_for,
                platforms=platforms or _parse_json_list(item.platforms_json) or ["telegram"],
            ),
        )

        item.review_status = "scheduled"
        item.scheduled_for = scheduled_for
        await db.commit()

        return {
            "ok": True,
            "item_id": item_id,
            "content_id": content_id,
            "calendar_entry_id": entry.id,
            "scheduled_for": scheduled_for,
            "review_status": "scheduled",
        }

    @staticmethod
    async def _get_item(db: AsyncSession, item_id: UUID) -> ContentFactoryItem:
        result = await db.execute(
            select(ContentFactoryItem)
            .options(selectinload(ContentFactoryItem.factory))
            .where(ContentFactoryItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Factory item not found")
        return item

    @staticmethod
    async def _load_factory(db: AsyncSession, factory_id: UUID) -> ContentFactory:
        result = await db.execute(
            select(ContentFactory)
            .options(
                selectinload(ContentFactory.client),
                selectinload(ContentFactory.source_media),
                selectinload(ContentFactory.items),
            )
            .where(ContentFactory.id == factory_id)
        )
        factory = result.scalar_one_or_none()
        if not factory:
            raise HTTPException(status_code=404, detail="Content factory not found")
        return factory
