"""Platform-specific content adaptation for AI Content Factory."""
from __future__ import annotations

from typing import Any

from app.services.content_factory_constants import (
    _PLATFORM_FORMAT_HINTS,
    FACTORY_PLATFORMS,
)


def adapt_for_platform(
    *,
    platform: str,
    captions: dict[str, str],
    headline: str | None,
    hashtags: str | None,
    cta: str | None,
    preferred_lang: str = "en",
) -> dict[str, Any]:
    """Build platform-tailored text from multilingual captions."""
    platform = platform.lower().strip()
    if platform not in FACTORY_PLATFORMS:
        platform = "telegram"

    long_key = f"caption_long_{preferred_lang}"
    short_key = f"caption_short_{preferred_lang}"
    body = (
        captions.get(long_key)
        or captions.get(short_key)
        or captions.get(preferred_lang)
        or captions.get("caption_long_en")
        or captions.get("en")
        or ""
    ).strip()

    headline_text = (headline or "").strip()
    cta_text = (cta or "").strip()
    tags = (hashtags or "").strip()

    if platform == "telegram":
        parts = [p for p in [headline_text, body, cta_text] if p]
        text = "\n\n".join(parts)
        if tags and len(text) + len(tags) + 2 <= 4096:
            text = f"{text}\n\n{tags}"
        return {
            "platform": platform,
            "format": "telegram_post",
            "text": text[:4096],
            "max_length": 4096,
            "hint": _PLATFORM_FORMAT_HINTS["telegram"],
        }

    if platform == "instagram":
        caption = body
        if headline_text and headline_text not in caption:
            caption = f"{headline_text}\n\n{caption}"
        if cta_text:
            caption = f"{caption}\n\n{cta_text}"
        if tags:
            caption = f"{caption}\n\n{tags}"
        return {
            "platform": platform,
            "format": "instagram_caption",
            "text": caption[:2200],
            "max_length": 2200,
            "hint": _PLATFORM_FORMAT_HINTS["instagram"],
        }

    if platform == "facebook":
        text = body
        if headline_text:
            text = f"{headline_text}\n\n{text}"
        if cta_text:
            text = f"{text}\n\n👉 {cta_text}"
        return {
            "platform": platform,
            "format": "facebook_post",
            "text": text[:63206],
            "max_length": 63206,
            "hint": _PLATFORM_FORMAT_HINTS["facebook"],
        }

    if platform == "linkedin":
        text = body
        if headline_text:
            text = f"{headline_text}\n\n{text}"
        if cta_text:
            text = f"{text}\n\n{cta_text}"
        if tags:
            text = f"{text}\n\n{tags}"
        return {
            "platform": platform,
            "format": "linkedin_post",
            "text": text[:3000],
            "max_length": 3000,
            "hint": _PLATFORM_FORMAT_HINTS["linkedin"],
        }

    if platform == "wechat":
        zh_body = (
            captions.get("caption_long_zh")
            or captions.get("caption_short_zh")
            or captions.get("zh")
            or body
        )
        text = zh_body
        if cta_text:
            text = f"{text}\n\n{cta_text}"
        return {
            "platform": platform,
            "format": "wechat_moments",
            "text": text[:2000],
            "max_length": 2000,
            "hint": _PLATFORM_FORMAT_HINTS["wechat"],
        }

    if platform == "whatsapp_status":
        short = (
            captions.get("caption_short_en")
            or captions.get("caption_short_ru")
            or body[:280]
        )
        if cta_text and len(short) + len(cta_text) + 3 <= 700:
            short = f"{short} — {cta_text}"
        return {
            "platform": platform,
            "format": "whatsapp_status",
            "text": short[:700],
            "max_length": 700,
            "hint": _PLATFORM_FORMAT_HINTS["whatsapp_status"],
        }

    return {"platform": platform, "format": "generic", "text": body, "max_length": 2000}


def build_platform_variants(
    *,
    platforms: list[str],
    captions: dict[str, str],
    headline: str | None,
    hashtags: str | None,
    cta: str | None,
    preferred_lang: str = "en",
) -> dict[str, dict[str, Any]]:
    return {
        p: adapt_for_platform(
            platform=p,
            captions=captions,
            headline=headline,
            hashtags=hashtags,
            cta=cta,
            preferred_lang=preferred_lang,
        )
        for p in platforms
        if p in FACTORY_PLATFORMS
    }
