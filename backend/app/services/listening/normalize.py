"""Normalize raw adapter observations into mention drafts with provenance."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.listening import (
    CONTENT_TYPES,
    DEDUPE_VERSION,
    NORMALIZATION_VERSION,
    OBSERVATION_ORIGINS,
)
from app.services.listening.dedupe import (
    build_content_fingerprint,
    build_dedupe_key,
    canonicalize_url,
    normalize_whitespace,
)
from app.services.listening.limits import MAX_CONTENT_TEXT_CHARS, MAX_EXCERPT_CHARS
from app.services.listening.schemas import NormalizedMentionDraft, RawObservation


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_excerpt(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = normalize_whitespace(text)
    if len(cleaned) <= MAX_EXCERPT_CHARS:
        return cleaned
    return cleaned[: MAX_EXCERPT_CHARS - 1] + "…"


def _clip_text(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = text.replace("\x00", "")
    if len(cleaned) > MAX_CONTENT_TEXT_CHARS:
        cleaned = cleaned[:MAX_CONTENT_TEXT_CHARS]
    return cleaned


def _sanitize_engagement(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        safe_key = key.strip()[:64]
        if isinstance(value, bool):
            out[safe_key] = value
        elif isinstance(value, int) and not isinstance(value, bool):
            out[safe_key] = value
        elif isinstance(value, float):
            out[safe_key] = value
        elif isinstance(value, str):
            out[safe_key] = value[:128]
        if len(out) >= 32:
            break
    return out or None


def origin_for_source_type(source_type: str) -> str:
    if source_type == "fixture":
        return "fixture"
    if source_type == "manual_import":
        return "manual_import"
    if source_type in OBSERVATION_ORIGINS:
        return source_type
    return "manual_import"


def normalize_observation(
    raw: RawObservation,
    *,
    source_type: str,
    observed_at: datetime | None = None,
    ingestion_run_id: str | None = None,
    project_id: str | None = None,
) -> NormalizedMentionDraft | None:
    """Return a normalized draft, or None if the observation is unusable."""
    if raw.malformed:
        return None

    content_text = _clip_text(raw.content_text)
    url = canonicalize_url(raw.canonical_url)
    if not content_text and not url and not (raw.provider_external_id or "").strip():
        return None

    content_type = raw.content_type if raw.content_type in CONTENT_TYPES else "other"
    observed = observed_at or utcnow()
    # Do not invent published_at — unknown stays None.
    published_at = raw.published_at
    source_updated_at = raw.source_updated_at

    account_ref = (raw.provider_account_ref or "").strip()
    external_id = (raw.provider_external_id or "").strip() or None
    fingerprint = build_content_fingerprint(
        source_type=source_type,
        provider_account_ref=account_ref,
        author_display=raw.author_display,
        content_text=content_text,
        published_at=published_at,
        canonical_url=url,
    )
    dedupe_key = build_dedupe_key(
        source_type=source_type,
        provider_account_ref=account_ref,
        provider_external_id=external_id,
        canonical_url=url,
        content_fingerprint=fingerprint,
    )
    origin = origin_for_source_type(source_type)

    provenance = {
        "source_type": source_type,
        "observation_origin": origin,
        "normalization_version": NORMALIZATION_VERSION,
        "ingestion_run_id": ingestion_run_id,
        "project_id": project_id,
        "provider_external_id": external_id,
        "raw_summary_keys": sorted((raw.raw_safe_summary or {}).keys())[:32],
        # Explicit honesty flags for UI / analytics consumers.
        "is_live_provider": origin == "live_provider",
        "is_fixture": origin == "fixture",
        "is_manual_import": origin == "manual_import",
    }

    author_display = (raw.author_display or "").strip()[:255] or None
    # Minimize PII: keep author external id only when provided and short.
    author_ext = (raw.author_external_id or "").strip()[:255] or None

    return NormalizedMentionDraft(
        source_type=source_type,
        observation_origin=origin,
        provider_account_ref=account_ref,
        provider_external_id=external_id,
        canonical_url=url,
        author_display=author_display,
        author_external_id=author_ext,
        content_text=content_text,
        content_excerpt=_safe_excerpt(content_text),
        content_type=content_type,
        language=(raw.language or "").strip().lower()[:16] or None,
        published_at=published_at,
        source_updated_at=source_updated_at,
        observed_at=observed,
        engagement_json=_sanitize_engagement(raw.engagement),
        content_fingerprint=fingerprint,
        dedupe_key=dedupe_key,
        dedupe_version=DEDUPE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        provenance_json=provenance,
    )


__all__ = [
    "utcnow",
    "normalize_observation",
    "origin_for_source_type",
]
