"""
Automated content quality checks for Telegram-ingested content.
"""
from __future__ import annotations

import json
from typing import Any

from app.models.content import ContentItem
from app.models.media import MediaFile
from app.services.content_enrichment_service import suggestions_from_json

TELEGRAM_BOT_MAX_BYTES = 20 * 1024 * 1024
SUPPORTED_MIME_PREFIXES = ("image/", "video/")
SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm")
MIN_TEXT_LENGTH = 10


def _warning(wid: str, message: str, *, critical: bool = False) -> dict[str, Any]:
    return {"id": wid, "message": message, "critical": critical}


def run_quality_checks(
    *,
    content_item: ContentItem,
    media_file: MediaFile | None,
    caption: str | None,
    selected_media_count: int = 1,
    target_languages: list[str] | None = None,
    suggestions: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    suggestions = suggestions or suggestions_from_json(content_item.suggestions_json)

    if not (caption or "").strip() and not (content_item.telegram_original_caption or "").strip():
        if not content_item.internal_notes or len(content_item.internal_notes.strip()) < MIN_TEXT_LENGTH:
            warnings.append(_warning("missing_caption", "Missing caption"))

    if suggestions:
        title = (suggestions.get("title") or "").lower()
        if "product" in (content_item.content_classification or "") and "product" not in title:
            if not any(w in (caption or "").lower() for w in ("product", "товар", "产品", "mahsulot")):
                warnings.append(_warning("missing_product_name", "Missing product name"))
        if not suggestions.get("price_detected") and "promotion" in (content_item.content_classification or ""):
            warnings.append(_warning("missing_price", "Missing price (promotion content)"))
        cta = suggestions.get("cta") or ""
        if cta == "Contact us for details" or not cta.strip():
            warnings.append(_warning("missing_contact_cta", "Missing contact CTA"))

    if media_file:
        if media_file.file_size and media_file.file_size > TELEGRAM_BOT_MAX_BYTES:
            warnings.append(_warning("video_too_large", "Video too large for Telegram Bot API (>20MB)", critical=True))
        fname = (media_file.original_filename or "").lower()
        mime = media_file.mime_type or ""
        if mime and not any(mime.startswith(p) for p in SUPPORTED_MIME_PREFIXES):
            if not any(fname.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
                warnings.append(_warning("unsupported_file_type", f"Unsupported file type: {mime or fname}"))

    notes = (content_item.internal_notes or "").lower()
    if "duplicate" in notes or content_item.telegram_excluded:
        warnings.append(_warning("duplicate_media", "Possible duplicate media"))

    if not target_languages:
        warnings.append(_warning("no_target_language", "No target language selected"))
    elif not any(
        getattr(content_item, f"caption_short_{lang}", None)
        or getattr(content_item, f"caption_long_{lang}", None)
        for lang in target_languages
        if lang in ("ru", "uz", "en")
    ):
        suggestions_caps = (suggestions or {}).get("captions") or {}
        if not any(suggestions_caps.get(l) for l in (target_languages or [])):
            warnings.append(_warning("missing_generated_captions", "Captions not generated for target languages"))

    text_len = len((caption or content_item.internal_notes or "").strip())
    if text_len > 0 and text_len < MIN_TEXT_LENGTH and selected_media_count <= 1:
        warnings.append(_warning("very_short_text", "Very short text content"))

    return warnings


def warnings_to_json(warnings: list[dict[str, Any]]) -> str:
    return json.dumps(warnings, ensure_ascii=False)


def warnings_from_json(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []
