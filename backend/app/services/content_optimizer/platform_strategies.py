"""Per-platform deterministic optimization strategies.

A strategy declares *what* structural preferences a platform has — it never
invents tone or wording. It only decides which allowlisted operations run and
with which parameters (hashtag placement/limits, paragraph structure, CTA
placement, link handling). Everything is derived from the versioned policy
catalog so behaviour stays stable and explainable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.publishing_intelligence.platform_policies import (
    SUPPORTED_PLATFORMS,
    get_policy,
)


@dataclass(frozen=True)
class PlatformStrategy:
    platform: str
    preferred_profile: str
    hashtags_at_end: bool
    limit_hashtags_to_recommended: bool
    preserve_first_paragraph: bool
    cta_near_end: bool
    require_existing_cta_only: bool
    allow_links: bool
    existing_hashtags_only: bool
    first_meaningful_sentence_only: bool
    structured_paragraphs: bool
    short_cta_max_len: int


_STRATEGIES: dict[str, PlatformStrategy] = {
    "telegram": PlatformStrategy(
        platform="telegram",
        preferred_profile="extended",
        hashtags_at_end=True,
        limit_hashtags_to_recommended=True,
        preserve_first_paragraph=False,
        cta_near_end=True,
        require_existing_cta_only=False,
        allow_links=True,
        existing_hashtags_only=True,
        first_meaningful_sentence_only=False,
        structured_paragraphs=False,
        short_cta_max_len=160,
    ),
    "facebook": PlatformStrategy(
        platform="facebook",
        preferred_profile="standard",
        hashtags_at_end=True,
        limit_hashtags_to_recommended=True,
        preserve_first_paragraph=False,
        cta_near_end=True,
        require_existing_cta_only=False,
        allow_links=True,
        existing_hashtags_only=True,
        first_meaningful_sentence_only=False,
        structured_paragraphs=False,
        short_cta_max_len=140,
    ),
    "instagram": PlatformStrategy(
        platform="instagram",
        preferred_profile="standard",
        hashtags_at_end=True,
        limit_hashtags_to_recommended=True,
        preserve_first_paragraph=True,
        cta_near_end=True,
        require_existing_cta_only=False,
        allow_links=False,
        existing_hashtags_only=True,
        first_meaningful_sentence_only=False,
        structured_paragraphs=False,
        short_cta_max_len=120,
    ),
    "tiktok": PlatformStrategy(
        platform="tiktok",
        preferred_profile="short",
        hashtags_at_end=True,
        limit_hashtags_to_recommended=True,
        preserve_first_paragraph=True,
        cta_near_end=True,
        require_existing_cta_only=True,
        allow_links=False,
        existing_hashtags_only=True,
        first_meaningful_sentence_only=True,
        structured_paragraphs=False,
        short_cta_max_len=80,
    ),
    "linkedin": PlatformStrategy(
        platform="linkedin",
        preferred_profile="standard",
        hashtags_at_end=True,
        limit_hashtags_to_recommended=True,
        preserve_first_paragraph=True,
        cta_near_end=True,
        require_existing_cta_only=False,
        allow_links=True,
        existing_hashtags_only=True,
        first_meaningful_sentence_only=False,
        structured_paragraphs=True,
        short_cta_max_len=140,
    ),
}


def get_strategy(platform: str) -> PlatformStrategy | None:
    return _STRATEGIES.get(platform.lower())


def is_supported_platform(platform: str) -> bool:
    return platform in SUPPORTED_PLATFORMS and platform in _STRATEGIES


def hashtag_limit(strategy: PlatformStrategy, policy: dict[str, Any]) -> int:
    if strategy.limit_hashtags_to_recommended:
        recommended = policy.get("hashtag_recommended_max")
        if recommended is not None:
            return int(recommended)
    return int(policy.get("hashtag_hard_max", 30))


def normalization_backbone(strategy: PlatformStrategy) -> list[tuple[str, dict[str, Any]]]:
    """Common, wording-preserving cleanup applied for every profile."""
    steps: list[tuple[str, dict[str, Any]]] = [
        ("normalize_line_breaks", {}),
        ("normalize_whitespace", {}),
        ("remove_duplicate_blank_lines", {}),
        ("normalize_bullet_format", {}),
        ("trim_leading_trailing_punctuation", {}),
        ("remove_empty_sections", {}),
    ]
    if strategy.structured_paragraphs:
        steps.append(("split_long_paragraphs", {"max_chars": 350}))
    return steps


def hashtag_steps(
    strategy: PlatformStrategy,
    policy: dict[str, Any],
    *,
    limit_override: int | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    steps: list[tuple[str, dict[str, Any]]] = [
        ("deduplicate_exact_hashtags", {}),
    ]
    if strategy.existing_hashtags_only:
        steps.append(("remove_unsupported_hashtags", {}))
    if strategy.hashtags_at_end:
        steps.append(("move_hashtags_to_end", {}))
    limit = limit_override if limit_override is not None else hashtag_limit(strategy, policy)
    steps.append(("limit_hashtag_count", {"max": limit}))
    return steps


def get_effective_strategies() -> dict[str, dict[str, Any]]:
    """Read-only view of strategy configuration for the configuration endpoint."""
    return {
        platform: {
            "preferred_profile": s.preferred_profile,
            "hashtags_at_end": s.hashtags_at_end,
            "limit_hashtags_to_recommended": s.limit_hashtags_to_recommended,
            "preserve_first_paragraph": s.preserve_first_paragraph,
            "cta_near_end": s.cta_near_end,
            "require_existing_cta_only": s.require_existing_cta_only,
            "allow_links": s.allow_links,
            "existing_hashtags_only": s.existing_hashtags_only,
            "first_meaningful_sentence_only": s.first_meaningful_sentence_only,
            "structured_paragraphs": s.structured_paragraphs,
        }
        for platform, s in _STRATEGIES.items()
    }
