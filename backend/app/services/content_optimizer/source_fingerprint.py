"""Deterministic source fingerprint (v1) for the Content Optimizer.

Captures every input that can change optimizer output — captions, title,
description, hashtags, note-derived keywords, selected CTA template texts, links,
locale/platform targets, content type and the effective optimizer configuration.
Unrelated metadata (timestamps, CRM links, internal notes body) is excluded so
edits that do not affect rendering do not needlessly supersede prior runs.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.content_optimizer.schemas import NormalizedSource

SOURCE_FINGERPRINT_VERSION = "v1"


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stable(value[k]) for k in sorted(value.keys(), key=str)}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    return value


def build_source_payload(
    source: NormalizedSource,
    *,
    target_platforms: list[str],
    target_locales: list[str],
    length_profiles: list[str],
    cta_template_texts: list[str],
    optimizer_version: str,
    policy_version: str,
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    captions = {
        locale: {
            "short": ls.short_text,
            "long": ls.long_text,
        }
        for locale, ls in sorted(source.locale_sources.items())
    }
    return {
        "v": SOURCE_FINGERPRINT_VERSION,
        "optimizer_version": optimizer_version,
        "policy_version": policy_version,
        "content_type": source.content_type,
        "captions": captions,
        "title": source.title,
        "description": source.description,
        "hashtags": list(source.hashtags),
        "keywords": sorted(source.keywords),
        "links": list(source.links),
        "cta_templates": sorted(cta_template_texts),
        "target_locales": sorted(set(target_locales)),
        "target_platforms": sorted(set(target_platforms)),
        "length_profiles": sorted(set(length_profiles)),
        "configuration": _stable(configuration or {}),
    }


def compute_source_fingerprint(
    source: NormalizedSource,
    *,
    target_platforms: list[str],
    target_locales: list[str],
    length_profiles: list[str],
    cta_template_texts: list[str],
    optimizer_version: str,
    policy_version: str,
    configuration: dict[str, Any] | None = None,
) -> str:
    payload = build_source_payload(
        source,
        target_platforms=target_platforms,
        target_locales=target_locales,
        length_profiles=length_profiles,
        cta_template_texts=cta_template_texts,
        optimizer_version=optimizer_version,
        policy_version=policy_version,
        configuration=configuration,
    )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
