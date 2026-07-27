"""Deterministic, explainable mention matching.

Supports case-insensitive phrase/alias matching with word-boundary awareness,
excluded terms, source filters, language filters, and handle/domain/URL checks.
Evidence (term, excerpt, offsets) is always retained.
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlsplit
from uuid import UUID

from app.models.listening import MATCHER_VERSION
from app.services.listening.schemas import MatchEvidence

_BOUNDARY_SAFE = re.compile(r"^[\w@#.+-]+$", re.UNICODE)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _normalize_lang(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower().split("-")[0] or None


def _excerpt(text: str, start: int, end: int, *, radius: int = 40) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def find_boundary_match(haystack: str, needle: str) -> tuple[int, int] | None:
    """Case-insensitive match with word-boundary guards for alphanumeric terms."""
    if not haystack or not needle:
        return None
    text = haystack
    term = needle.strip()
    if not term:
        return None
    lowered = text.casefold()
    target = term.casefold()

    if _BOUNDARY_SAFE.match(term) and " " not in term:
        pattern = re.compile(
            rf"(?<![\w@#]){re.escape(target)}(?![\w@#])",
            re.IGNORECASE | re.UNICODE,
        )
        m = pattern.search(text)
        if m:
            return m.start(), m.end()
        return None

    idx = lowered.find(target)
    if idx < 0:
        return None
    return idx, idx + len(term)


def _url_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _normalize_handle(handle: str | None) -> str | None:
    if not handle:
        return None
    h = handle.strip().lstrip("@").casefold()
    return h or None


def match_mention_against_queries(
    *,
    content_text: str | None,
    canonical_url: str | None,
    author_display: str | None,
    language: str | None,
    source_type: str,
    queries: Iterable[Any],
    subjects_by_id: dict[UUID, Any],
) -> list[MatchEvidence]:
    """Return unique MatchEvidence rows for enabled queries that match."""
    text = content_text or ""
    evidence: list[MatchEvidence] = []
    seen: set[tuple[Any, str, str]] = set()
    mention_lang = _normalize_lang(language)
    url_host = _url_host(canonical_url)
    author_handle = _normalize_handle(author_display)

    for query in queries:
        if not getattr(query, "is_enabled", True):
            continue

        source_filters = _as_list(getattr(query, "source_filters_json", None))
        if source_filters and source_type not in source_filters:
            continue

        lang_filters = [_normalize_lang(x) for x in _as_list(getattr(query, "language_filters_json", None))]
        lang_filters = [x for x in lang_filters if x]
        if lang_filters and (mention_lang is None or mention_lang not in lang_filters):
            continue

        exclude_terms = _as_list(getattr(query, "exclude_terms_json", None))
        excluded = False
        for term in exclude_terms:
            if find_boundary_match(text, term) is not None:
                excluded = True
                break
        if excluded:
            continue

        subject = None
        subject_id = getattr(query, "subject_id", None)
        if subject_id is not None:
            subject = subjects_by_id.get(subject_id)

        candidates: list[tuple[str, str]] = []
        for term in _as_list(getattr(query, "include_terms_json", None)):
            candidates.append(("keyword" if " " not in term.strip() else "phrase", term))

        if subject is not None:
            canonical = getattr(subject, "canonical_name", None)
            if canonical:
                candidates.append(("phrase", canonical))
            for alias in _as_list(getattr(subject, "aliases_json", None)):
                candidates.append(("alias", alias))
            handle = _normalize_handle(getattr(subject, "handle", None))
            if handle:
                candidates.append(("handle", handle))
            domain = (getattr(subject, "domain", None) or "").strip().lower()
            if domain.startswith("www."):
                domain = domain[4:]
            if domain:
                candidates.append(("domain", domain))

        for match_type, term in candidates:
            key = (getattr(query, "id", None), match_type, term.casefold())
            if key in seen:
                continue

            hit: tuple[int, int] | None = None
            if match_type == "handle":
                if author_handle and author_handle == _normalize_handle(term):
                    hit = (0, 0)
                else:
                    needle = f"@{term.lstrip('@')}"
                    hit = find_boundary_match(text, needle) or find_boundary_match(text, term)
            elif match_type == "domain":
                domain = term.lower()
                if url_host and (url_host == domain or url_host.endswith("." + domain)):
                    hit = (0, 0)
                else:
                    hit = find_boundary_match(text, domain)
            else:
                hit = find_boundary_match(text, term)

            if hit is None:
                continue

            start, end = hit
            excerpt = None
            if text and end > start:
                excerpt = _excerpt(text, start, end)
            elif canonical_url and match_type in {"domain", "url"}:
                excerpt = canonical_url[:500]
            elif author_display and match_type == "handle":
                excerpt = author_display[:500]

            seen.add(key)
            evidence.append(
                MatchEvidence(
                    query_id=getattr(query, "id", None),
                    subject_id=subject_id,
                    match_type=match_type,
                    matched_term=term,
                    evidence_excerpt=excerpt,
                    evidence_start=start if end > start else None,
                    evidence_end=end if end > start else None,
                    matcher_version=MATCHER_VERSION,
                )
            )

    return evidence


__all__ = [
    "find_boundary_match",
    "match_mention_against_queries",
]
