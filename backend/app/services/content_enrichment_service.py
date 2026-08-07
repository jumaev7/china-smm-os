"""
Content enrichment for Telegram ingestion — suggested titles, captions, hashtags, CTA.
Uses AI when configured; otherwise rule-based placeholders.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.models.client import Client

SUPPORTED_LANGUAGES = ("ru", "uz", "en", "zh")
DEFAULT_PLATFORMS = ("instagram", "telegram", "facebook")
logger = logging.getLogger(__name__)


def _first_sentence(text: str, max_len: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    for sep in (". ", "!\n", "?\n", "\n"):
        if sep in cleaned:
            cleaned = cleaned.split(sep)[0].strip()
            break
    return cleaned[:max_len].strip()


def _extract_price(text: str) -> str | None:
    match = re.search(r"(\$|€|¥|₽|USD|EUR|CNY|RUB|UZS|\d[\d\s.,]*(?:\$|€|¥|₽|usd|eur))", text, re.I)
    return match.group(0).strip() if match else None


def _default_hashtags(classification: str, client: Client) -> str:
    base = []
    if client.hashtag_preferences:
        base.extend(h.strip() for h in client.hashtag_preferences.replace(",", " ").split() if h.strip())
    cat_tags = {
        "product": ["#product", "#catalog"],
        "factory": ["#factory", "#manufacturing"],
        "promotion": ["#sale", "#promo"],
        "customer_review": ["#review", "#testimonial"],
        "exhibition_event": ["#expo", "#event"],
    }.get(classification, ["#content"])
    merged = list(dict.fromkeys(base + cat_tags))[:8]
    return " ".join(merged)


def _default_cta(client: Client) -> str:
    if client.cta_telegram:
        return f"Contact us on Telegram: {client.cta_telegram}"
    if client.cta_phone:
        return f"Call: {client.cta_phone}"
    if client.cta_website:
        return f"Learn more: {client.cta_website}"
    return "Contact us for details"


def enrich_content(
    *,
    client: Client,
    caption: str | None,
    internal_notes: str | None,
    classification: str,
    target_languages: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build suggested enrichment fields. Rule-based placeholders when AI unavailable.
    """
    langs = [l for l in (target_languages or list(SUPPORTED_LANGUAGES)) if l in SUPPORTED_LANGUAGES]
    if not langs:
        langs = list(SUPPORTED_LANGUAGES)

    source = (caption or "").strip() or _first_sentence(internal_notes or "")
    title = _first_sentence(source, 80) or f"{client.company_name} — {classification.replace('_', ' ').title()}"
    short_desc = _first_sentence(source, 200) or f"Content from {client.company_name}"

    captions: dict[str, str] = {}
    for lang in langs:
        if lang == "ru":
            captions["ru"] = source[:500] if source else f"[RU caption pending — {title}]"
        elif lang == "uz":
            captions["uz"] = source[:500] if source else f"[UZ caption pending — {title}]"
        elif lang == "en":
            captions["en"] = source[:500] if source else f"[EN caption pending — {title}]"
        elif lang == "zh":
            captions["zh"] = source[:500] if source else f"[中文 caption pending — {title}]"

    platforms = list(DEFAULT_PLATFORMS)
    if classification in ("company_news", "exhibition_event"):
        platforms = ["telegram", "linkedin", "facebook"]
    elif classification == "customer_review":
        platforms = ["instagram", "telegram"]

    return {
        "title": title,
        "short_description": short_desc,
        "captions": captions,
        "hashtags": _default_hashtags(classification, client),
        "cta": _default_cta(client),
        "target_platforms": platforms,
        "price_detected": _extract_price(source),
        "method": "rule_based",
    }


async def enrich_with_ai(
    *,
    client: Client,
    caption: str | None,
    internal_notes: str | None,
    classification: str,
    target_languages: list[str],
) -> dict[str, Any] | None:
    """AI enrichment hook — returns None when not configured."""
    from app.core.config import settings
    if settings.DEMO_MODE or not settings.AI_PLATFORM_ENABLED or not client.tenant_id:
        return None
    from app.services.ai_platform.generation_service import GenerationService
    from app.services.ai_platform.schemas import TASK_AI_CONTENT_ADAPTATION

    source_parts: list[str] = []
    if (caption or "").strip():
        source_parts.append(f"Operator caption:\n{caption.strip()}")
    if (internal_notes or "").strip():
        source_parts.append(f"Extracted media context (OCR/transcript):\n{internal_notes.strip()}")
    source = "\n\n".join(source_parts)
    if not source:
        return None
    langs = [lang for lang in target_languages if lang in SUPPORTED_LANGUAGES]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "captions", "hashtags", "cta", "target_platforms"],
        "properties": {
            "title": {"type": "string"},
            "captions": {
                "type": "object",
                "additionalProperties": False,
                "properties": {lang: {"type": "string"} for lang in langs},
            },
            "hashtags": {"type": "string"},
            "cta": {"type": "string"},
            "target_platforms": {
                "type": "array",
                "items": {"type": "string", "enum": list(DEFAULT_PLATFORMS)},
            },
        },
    }
    brand = {
        "company_name": client.company_name,
        "category": getattr(client, "business_category", None),
        "tone": getattr(client, "tone_of_voice", None),
        "cta_telegram": client.cta_telegram,
        "cta_phone": client.cta_phone,
        "cta_website": client.cta_website,
        "hashtag_preferences": client.hashtag_preferences,
    }
    try:
        response, _, _ = await GenerationService.generate_structured(
            tenant_id=str(client.tenant_id),
            task_type=TASK_AI_CONTENT_ADAPTATION,
            model_alias="content_standard",
            system_instructions=(
                "Create publish-ready social captions from the supplied source. Preserve every factual claim; "
                "never invent prices, features, contacts, guarantees, or events. Return JSON only. "
                "Write one natural caption for each requested language and concise relevant hashtags. "
                "Your JSON must match this schema exactly: "
                + json.dumps(schema, ensure_ascii=False)
            ),
            input_messages=[{
                "role": "user",
                "content": json.dumps({
                    "source": source,
                    "classification": classification,
                    "languages": langs,
                    "brand": brand,
                    "platforms": list(DEFAULT_PLATFORMS),
                }, ensure_ascii=False),
            }],
            output_schema=schema,
            temperature=0.25,
            max_output_tokens=1400,
            metadata={"pipeline": "telegram_ingestion_enrichment"},
            parse_output=False,
        )
        data = response.structured_output or {}
        captions = data.get("captions") if isinstance(data.get("captions"), dict) else {}
        clean_captions = {
            lang: str(captions.get(lang) or "").strip()[:4000]
            for lang in langs
            if str(captions.get(lang) or "").strip()
        }
        platforms = [p for p in data.get("target_platforms", []) if p in DEFAULT_PLATFORMS]
        if not clean_captions:
            return None
        return {
            "title": str(data.get("title") or "").strip()[:200],
            "short_description": _first_sentence(next(iter(clean_captions.values())), 200),
            "captions": clean_captions,
            "hashtags": str(data.get("hashtags") or "").strip()[:500],
            "cta": str(data.get("cta") or "").strip()[:500],
            "target_platforms": platforms or list(DEFAULT_PLATFORMS),
            "price_detected": _extract_price(source),
            "method": "governed_ai",
        }
    except Exception as exc:
        logger.warning("telegram_ai_enrichment_fallback error=%s", type(exc).__name__)
        return None


def suggestions_to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def suggestions_from_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
