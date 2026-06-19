"""
Content enrichment for Telegram ingestion — suggested titles, captions, hashtags, CTA.
Uses AI when configured; otherwise rule-based placeholders.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.models.client import Client

SUPPORTED_LANGUAGES = ("ru", "uz", "en", "zh")
DEFAULT_PLATFORMS = ("instagram", "telegram", "facebook")


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
    if not settings.OPENAI_API_KEY or settings.DEMO_MODE:
        return None
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
