"""Deterministic deduplication for observed mentions.

Priority:
1. tenant + source_type + provider_account_ref + provider_external_id
2. tenant + canonicalized stable URL
3. versioned normalized fingerprint (fallback)

Uses hashlib.sha256 only — never Python hash().
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.models.listening import DEDUPE_VERSION
from app.services.listening.limits import MAX_CONTENT_TEXT_CHARS

_WHITESPACE_RE = re.compile(r"\s+")
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid",
})


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip())


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.lower().rstrip("/")
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or ""
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_content_for_fingerprint(text: str | None) -> str:
    if not text:
        return ""
    clipped = text[:MAX_CONTENT_TEXT_CHARS]
    return normalize_whitespace(clipped).casefold()


def build_content_fingerprint(
    *,
    source_type: str,
    provider_account_ref: str,
    author_display: str | None,
    content_text: str | None,
    published_at: datetime | None,
    canonical_url: str | None,
) -> str:
    """Versioned fingerprint used as fallback identity and edit detection."""
    published_token = published_at.astimezone().isoformat() if published_at else ""
    payload = "|".join([
        DEDUPE_VERSION,
        source_type or "",
        (provider_account_ref or "").strip(),
        (author_display or "").strip().casefold(),
        normalize_content_for_fingerprint(content_text),
        published_token,
        canonicalize_url(canonical_url) or "",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_dedupe_key(
    *,
    source_type: str,
    provider_account_ref: str,
    provider_external_id: str | None,
    canonical_url: str | None,
    content_fingerprint: str,
) -> str:
    """Stable tenant-local dedupe key (tenant_id applied at persistence layer)."""
    ext = (provider_external_id or "").strip()
    if ext:
        account = (provider_account_ref or "").strip() or "_"
        return f"ext:{source_type}:{account}:{ext}"

    url = canonicalize_url(canonical_url)
    if url:
        return f"url:{source_type}:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:40]}"

    return f"fp:{content_fingerprint}"


def provider_identity_key(
    *,
    source_type: str,
    provider_account_ref: str,
    provider_external_id: str | None,
) -> str | None:
    ext = (provider_external_id or "").strip()
    if not ext:
        return None
    account = (provider_account_ref or "").strip() or "_"
    return f"{source_type}|{account}|{ext}"


__all__ = [
    "normalize_whitespace",
    "canonicalize_url",
    "normalize_content_for_fingerprint",
    "build_content_fingerprint",
    "build_dedupe_key",
    "provider_identity_key",
]
