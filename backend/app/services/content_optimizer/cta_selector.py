"""Deterministic CTA selection — only ever reuses existing wording.

CTAs are drawn from two provenance-safe sources: phrases already present in the
source caption (detected via the versioned CTA catalog, sliced verbatim) and
tenant-approved plain-text CTA templates. Nothing is generated or rephrased.
"""
from __future__ import annotations

from app.services.publishing_intelligence.cta_catalog import detect_ctas


def extract_source_ctas(text: str | None) -> list[str]:
    """Verbatim CTA substrings found in the source text, in order of appearance."""
    if not text or not text.strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for match in detect_ctas(text):
        excerpt = text[match.start : match.end].strip()
        key = excerpt.casefold()
        if not excerpt or key in seen:
            continue
        seen.add(key)
        out.append(excerpt)
    return out


def select_existing_cta(
    text: str | None,
    templates: list[str] | None = None,
    *,
    max_len: int | None = None,
    prefer: str = "last",
) -> str | None:
    """Choose a single CTA that already exists in the source or approved templates.

    ``prefer='last'`` favours the CTA nearest the end of the source (typical
    placement); ``prefer='first'`` favours the earliest. Templates are considered
    only when no in-source CTA satisfies the length constraint.
    """
    candidates = extract_source_ctas(text)
    if prefer == "last":
        candidates = list(reversed(candidates))

    for candidate in candidates:
        if max_len is None or len(candidate) <= max_len:
            return candidate

    for template in templates or []:
        cleaned = (template or "").strip()
        if not cleaned:
            continue
        if max_len is None or len(cleaned) <= max_len:
            return cleaned

    return None


def source_has_cta(text: str | None) -> bool:
    return bool(extract_source_ctas(text))
