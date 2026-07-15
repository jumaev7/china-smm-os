"""Deterministic content fingerprint for publishing review invalidation.

Fingerprint version: v1

Included fields (review-relevant only):
- captions (short/long per language, non-empty values, language keys sorted)
- hashtags (normalized, sorted)
- keywords (normalized, sorted)
- primary_language
- target platforms (sorted)
- media IDs and verified metadata (id, file_type, mime_type, file_size, thumbnail_present)
- scheduled_for (ISO UTC or null)
- content status (publish-relevant)
- content_type
- link (if present)
- CTA hint text (if present)

Excluded (do not invalidate review):
- internal_notes
- client_review feedback text
- unrelated CRM / campaign FK changes
- review_token
- timestamps other than scheduled_for
- media file binary contents (Phase 1 uses IDs + metadata only)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.services.publishing_intelligence.schemas import ReviewContext

FINGERPRINT_VERSION = "v1"


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.astimezone().isoformat()


def build_fingerprint_payload(ctx: ReviewContext) -> dict[str, Any]:
    """Stable ordered payload used for hashing."""
    media_meta = None
    if ctx.media:
        media_meta = {
            "id": str(ctx.media.get("id") or ""),
            "file_type": ctx.media.get("file_type"),
            "mime_type": ctx.media.get("mime_type"),
            "file_size": ctx.media.get("file_size"),
            "thumbnail_present": bool(ctx.media.get("thumbnail_present")),
            "upload_complete": bool(ctx.media.get("upload_complete")),
        }
    return {
        "v": FINGERPRINT_VERSION,
        "captions": {k: ctx.captions[k] for k in sorted(ctx.captions.keys())},
        "hashtags": list(ctx.hashtags),
        "keywords": list(ctx.keywords),
        "primary_language": ctx.primary_language,
        "platforms": sorted(ctx.platforms),
        "media": media_meta,
        "scheduled_for": _iso(ctx.scheduled_for),
        "status": ctx.status,
        "content_type": ctx.content_type,
        "link": ctx.link,
        "cta_hint": ctx.cta_hint,
        "approved": ctx.approved_at is not None,
        "client_review_status": ctx.client_review_status,
    }


def compute_content_fingerprint(ctx: ReviewContext) -> str:
    """SHA-256 hex digest of the versioned fingerprint payload."""
    payload = build_fingerprint_payload(ctx)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
