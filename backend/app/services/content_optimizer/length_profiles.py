"""Deterministic length profiles and pipeline composition.

Each profile composes an ordered list of allowlisted operations from the
platform strategy and the versioned policy. Profiles only ever shorten, select,
normalize or reorder — never invent. ``short`` keeps the opening + mandatory
disclosure + a fitting existing CTA + one link; ``standard`` is balanced with
deduplication and platform hashtag policy; ``extended`` preserves the most
detail, normalizing only and respecting the platform hard maximum.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.content_optimizer.platform_strategies import (
    PlatformStrategy,
    hashtag_steps,
    normalization_backbone,
)
from app.services.content_optimizer.schemas import LENGTH_PROFILES

_SHORT_HARD_CEILING = 300


@dataclass(frozen=True)
class LengthProfileSpec:
    name: str
    description: str


LENGTH_PROFILE_SPECS: dict[str, LengthProfileSpec] = {
    "short": LengthProfileSpec(
        "short",
        "First meaningful sentence, mandatory disclosure, fitting CTA and one link.",
    ),
    "standard": LengthProfileSpec(
        "standard",
        "Balanced body: deduplicated, normalized, platform hashtag policy applied.",
    ),
    "extended": LengthProfileSpec(
        "extended",
        "Maximum retained detail: normalize only, respect platform hard maximum.",
    ),
}


def is_valid_profile(name: str) -> bool:
    return name in LENGTH_PROFILES


def _recommended_max(policy: dict[str, Any]) -> int:
    return int(policy.get("caption_recommended_max") or policy.get("caption_hard_max") or 2000)


def _hard_max(policy: dict[str, Any]) -> int:
    return int(policy.get("caption_hard_max") or 4096)


def target_max_chars(profile: str, policy: dict[str, Any]) -> int:
    if profile == "short":
        return min(_recommended_max(policy), _SHORT_HARD_CEILING)
    if profile == "standard":
        return _recommended_max(policy)
    return _hard_max(policy)


def _cta_step(strategy: PlatformStrategy, *, short: bool) -> list[tuple[str, dict[str, Any]]]:
    prefer = "last" if strategy.cta_near_end else "first"
    params: dict[str, Any] = {"prefer": prefer}
    if short and strategy.require_existing_cta_only:
        params["max_len"] = strategy.short_cta_max_len
    steps: list[tuple[str, dict[str, Any]]] = []
    if strategy.cta_near_end:
        steps.append(("preserve_last_cta", {}))
    steps.append(("select_existing_cta", params))
    return steps


def build_pipeline(
    strategy: PlatformStrategy,
    profile: str,
    policy: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Compose the ordered, deterministic transformation pipeline for a variant."""
    steps: list[tuple[str, dict[str, Any]]] = list(normalization_backbone(strategy))

    if profile == "short":
        if strategy.preserve_first_paragraph:
            steps.append(("preserve_first_paragraph", {}))
        steps.append(("deduplicate_exact_sentences", {}))
        n_sentences = 1 if strategy.first_meaningful_sentence_only else 2
        steps.append(("select_first_n_sentences", {"n": n_sentences}))
        steps.append(("remove_repeated_link", {}))
        steps.extend(hashtag_steps(strategy, policy))
        steps.extend(_cta_step(strategy, short=True))
        steps.append(("truncate_at_sentence_boundary", {"max_chars": target_max_chars("short", policy)}))
        return steps

    if profile == "standard":
        if strategy.preserve_first_paragraph:
            steps.append(("preserve_first_paragraph", {}))
        steps.append(("deduplicate_exact_sentences", {}))
        steps.append(("remove_repeated_link", {}))
        if strategy.structured_paragraphs:
            steps.append(("join_short_lines", {"min_chars": 40}))
        steps.extend(hashtag_steps(strategy, policy))
        steps.extend(_cta_step(strategy, short=False))
        steps.append(("truncate_at_paragraph_boundary", {"max_chars": target_max_chars("standard", policy)}))
        steps.append(("truncate_at_sentence_boundary", {"max_chars": _hard_max(policy)}))
        return steps

    # extended
    steps.extend(
        hashtag_steps(strategy, policy, limit_override=int(policy.get("hashtag_hard_max", 30)))
    )
    steps.extend(_cta_step(strategy, short=False))
    steps.append(("truncate_at_paragraph_boundary", {"max_chars": target_max_chars("extended", policy)}))
    return steps


def get_effective_profiles() -> dict[str, str]:
    return {name: spec.description for name, spec in LENGTH_PROFILE_SPECS.items()}
