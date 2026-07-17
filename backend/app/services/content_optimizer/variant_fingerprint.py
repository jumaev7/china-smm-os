"""Deterministic variant fingerprint (v1) for the Content Optimizer.

A variant fingerprint identifies the *rendered* output uniquely: same platform,
locale, length profile, caption, hashtags, CTA, link, optimizer and policy
versions always hash to the same digest. Used for idempotency and change
detection of immutable variant snapshots.
"""
from __future__ import annotations

import hashlib
import json

VARIANT_FINGERPRINT_VERSION = "v1"


def build_variant_payload(
    *,
    platform: str,
    locale: str,
    length_profile: str,
    caption: str,
    hashtags: list[str],
    cta: str | None,
    link: str | None,
    optimizer_version: str,
    policy_version: str,
) -> dict[str, object]:
    return {
        "v": VARIANT_FINGERPRINT_VERSION,
        "platform": platform,
        "locale": locale,
        "length_profile": length_profile,
        "caption": caption,
        "hashtags": list(hashtags),
        "cta": cta,
        "link": link,
        "optimizer_version": optimizer_version,
        "policy_version": policy_version,
    }


def compute_variant_fingerprint(
    *,
    platform: str,
    locale: str,
    length_profile: str,
    caption: str,
    hashtags: list[str],
    cta: str | None,
    link: str | None,
    optimizer_version: str,
    policy_version: str,
) -> str:
    payload = build_variant_payload(
        platform=platform,
        locale=locale,
        length_profile=length_profile,
        caption=caption,
        hashtags=hashtags,
        cta=cta,
        link=link,
        optimizer_version=optimizer_version,
        policy_version=policy_version,
    )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
