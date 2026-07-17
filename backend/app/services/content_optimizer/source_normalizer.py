"""Normalize a ContentItem into an immutable, deterministic NormalizedSource.

Reads the source *without mutating it*. Produces a per-locale structural view
(paragraphs + sentences), a normalized hashtag list, note-derived keywords,
extracted links and optional disclosure detection. This is the single source of
truth the fingerprint, transformation engine and provenance validator consume.
"""
from __future__ import annotations

import re
from uuid import UUID

from app.models.content import ContentItem
from app.services.content_optimizer import hashtag_optimizer as ht
from app.services.content_optimizer.schemas import (
    LOCALE_CAPTION_FIELDS,
    MIN_SOURCE_CHARS,
    MIN_SOURCE_WORDS,
    LocaleSource,
    NormalizedSource,
)
from app.services.content_optimizer.sentence_segmenter import (
    segment,
    split_sentences,
)
from app.services.publishing_intelligence.platform_policies import SUPPORTED_PLATFORMS

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_DISCLOSURE_MARKERS = (
    "#ad",
    "#sponsored",
    "sponsored",
    "advertisement",
    "promoted",
    "на правах рекламы",
    "реклама",
    "reklama",
    "广告",
    "廣告",
)


def _extract_links(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,);]")
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _detect_disclosure(paragraphs: list[str]) -> str | None:
    for paragraph in paragraphs:
        lowered = paragraph.casefold()
        if any(marker in lowered for marker in _DISCLOSURE_MARKERS):
            return paragraph
    return None


def _extract_keywords_from_notes(notes: str | None) -> list[str]:
    if not notes:
        return []
    for line in notes.splitlines():
        if line.lower().startswith("keywords:"):
            payload = line.split(":", 1)[1]
            out: list[str] = []
            seen: set[str] = set()
            for part in payload.split(","):
                kw = part.strip().lower()
                if kw and kw not in seen:
                    seen.add(kw)
                    out.append(kw)
            return out
    return []


def _primary_locale(locale_sources: dict[str, LocaleSource]) -> str | None:
    for locale in ("en", "ru", "uz"):
        ls = locale_sources.get(locale)
        if ls and ls.text.strip():
            return locale
    for locale, ls in locale_sources.items():
        if ls.text.strip():
            return locale
    return None


def normalize_source(item: ContentItem, tenant_id: UUID) -> NormalizedSource:
    locale_sources: dict[str, LocaleSource] = {}
    all_links: list[str] = []
    seen_links: set[str] = set()

    for locale, (short_attr, long_attr) in LOCALE_CAPTION_FIELDS.items():
        short_text = (getattr(item, short_attr, None) or "").strip()
        long_text = (getattr(item, long_attr, None) or "").strip()
        text = long_text or short_text
        if not text:
            continue
        sections = segment(text)
        paragraphs = [s.text for s in sections]
        sentences = split_sentences(text)
        locale_sources[locale] = LocaleSource(
            locale=locale,
            short_text=short_text,
            long_text=long_text,
            text=text,
            paragraphs=paragraphs,
            sections=sections,
            sentences=sentences,
            disclosure=_detect_disclosure(paragraphs),
        )
        for url in _extract_links(text):
            if url not in seen_links:
                seen_links.add(url)
                all_links.append(url)

    hashtags = ht.parse_hashtag_field(item.hashtags)
    for ls in locale_sources.values():
        inline = ht.extract_inline_hashtags(ls.text)
        if inline:
            hashtags = ht.dedupe_hashtags(hashtags + inline)

    platforms = [p for p in (item.platforms or []) if p in SUPPORTED_PLATFORMS]

    return NormalizedSource(
        content_id=item.id,
        tenant_id=tenant_id,
        content_type=(item.media_file.file_type if item.media_file else None) or "text",
        primary_locale=_primary_locale(locale_sources),
        locales=list(locale_sources.keys()),
        platforms=platforms,
        locale_sources=locale_sources,
        hashtags=hashtags,
        hashtags_raw=item.hashtags or "",
        keywords=_extract_keywords_from_notes(item.internal_notes),
        links=all_links,
        title=None,
        description=None,
    )


def total_source_length(source: NormalizedSource) -> int:
    return sum(len(ls.text) for ls in source.locale_sources.values())


def is_locale_sufficient(source: NormalizedSource, locale: str) -> bool:
    ls = source.locale_sources.get(locale)
    if not ls or not ls.text.strip():
        return False
    if len(ls.text.strip()) < MIN_SOURCE_CHARS:
        return False
    return len(_WORD_RE.findall(ls.text)) >= MIN_SOURCE_WORDS or bool(
        re.search(r"[\u4e00-\u9fff]", ls.text)
    )


def has_any_sufficient_locale(source: NormalizedSource) -> bool:
    return any(is_locale_sufficient(source, locale) for locale in source.locale_sources)
