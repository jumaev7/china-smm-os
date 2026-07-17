"""Deterministic hashtag helpers — select/normalize/dedupe existing tags only.

No hashtag is ever invented. Every function operates purely on tags that already
exist in the source (its ``hashtags`` field or inline ``#tokens``), reordering,
deduplicating, validating or trimming them under stable rules.
"""
from __future__ import annotations

import re

_INLINE_HASHTAG_RE = re.compile(r"#([^\s#.,;:!?)（）]+)", re.UNICODE)
_FIELD_SPLIT_RE = re.compile(r"[,;\n\r\t ]+")
_VALID_BODY_RE = re.compile(r"^[^\W\d_](?:[\w]|[-])*$", re.UNICODE)


def normalize_tag(raw: str) -> str:
    """Strip a leading '#' and surrounding whitespace; wording preserved."""
    return raw.strip().lstrip("#").strip()


def _dedupe_key(tag: str) -> str:
    return tag.casefold()


def parse_hashtag_field(raw: str | None) -> list[str]:
    """Parse a comma/space separated hashtag string into ordered unique tags."""
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in _FIELD_SPLIT_RE.split(raw.strip()):
        tag = normalize_tag(part)
        if not tag:
            continue
        key = _dedupe_key(tag)
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def extract_inline_hashtags(text: str | None) -> list[str]:
    """Ordered unique hashtags embedded within a body of text."""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for match in _INLINE_HASHTAG_RE.finditer(text):
        tag = normalize_tag(match.group(1))
        if not tag:
            continue
        key = _dedupe_key(tag)
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def dedupe_hashtags(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        key = _dedupe_key(tag)
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def is_valid_hashtag(tag: str) -> bool:
    """A tag is supported when it is a single word token (letters allowed)."""
    body = normalize_tag(tag)
    if not body:
        return False
    return bool(_VALID_BODY_RE.match(body))


def filter_supported(tags: list[str]) -> list[str]:
    return [t for t in tags if is_valid_hashtag(t)]


def limit_hashtags(tags: list[str], max_count: int) -> list[str]:
    if max_count < 0:
        return list(tags)
    return list(tags[:max_count])


def render_hashtag(tag: str) -> str:
    return f"#{normalize_tag(tag)}"
