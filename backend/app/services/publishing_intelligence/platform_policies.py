"""Versioned deterministic platform policy catalog for Publishing Intelligence.

Hard constraints = provider-enforced / project-adapter limits when known.
Recommendations = internal guidelines (not claimed as hard platform restrictions).
"""
from __future__ import annotations

from typing import Any

POLICY_CATALOG_VERSION = "1.0.0"

# Platforms actually represented in publish adapters / DESTINATIONS.
SUPPORTED_PLATFORMS = ("telegram", "facebook", "instagram", "tiktok", "linkedin")

# Category weights for overall Publishing Score (sum = 100).
CATEGORY_WEIGHTS: dict[str, int] = {
    "caption_quality": 20,
    "platform_fit": 20,
    "cta_quality": 10,
    "hashtag_quality": 10,
    "media_readiness": 15,
    "language_quality": 10,
    "translation_readiness": 5,
    "compliance_readiness": 5,
    "scheduling_readiness": 5,
}

# Critical failure overall-score cap.
CRITICAL_SCORE_CAP = 40
LOW_SCORE_THRESHOLD = 55
PLATFORM_FIT_LOW_THRESHOLD = 50

_PLATFORM_POLICIES: dict[str, dict[str, Any]] = {
    "telegram": {
        "label": "Telegram",
        "caption_recommended_min": 20,
        "caption_recommended_max": 900,
        "caption_hard_max": 4096,  # Bot API message limit (hard)
        "hashtag_recommended_min": 0,
        "hashtag_recommended_max": 8,
        "hashtag_hard_max": 30,
        "media_required": False,
        "supported_media_types": ["image", "video"],
        "link_allowed": True,
        "cta_recommended": True,
        "emoji_recommended_max_ratio": 0.15,
        "notes": "Hard max from Telegram Bot API message length.",
    },
    "facebook": {
        "label": "Facebook",
        "caption_recommended_min": 40,
        "caption_recommended_max": 500,
        "caption_hard_max": 63206,
        "hashtag_recommended_min": 0,
        "hashtag_recommended_max": 5,
        "hashtag_hard_max": 30,
        "media_required": False,
        "supported_media_types": ["image", "video"],
        "link_allowed": True,
        "cta_recommended": True,
        "emoji_recommended_max_ratio": 0.12,
        "notes": "Recommended lengths are internal guidelines.",
    },
    "instagram": {
        "label": "Instagram",
        "caption_recommended_min": 50,
        "caption_recommended_max": 300,
        "caption_hard_max": 2200,  # widely documented IG caption limit
        "hashtag_recommended_min": 3,
        "hashtag_recommended_max": 15,
        "hashtag_hard_max": 30,
        "media_required": True,  # IG posts require media
        "supported_media_types": ["image", "video"],
        "link_allowed": False,  # caption links not clickable in feed
        "cta_recommended": True,
        "emoji_recommended_max_ratio": 0.18,
        "notes": "media_required and caption_hard_max are hard constraints; hashtag ranges are recommendations.",
    },
    "tiktok": {
        "label": "TikTok",
        "caption_recommended_min": 20,
        "caption_recommended_max": 150,
        "caption_hard_max": 2200,
        "hashtag_recommended_min": 2,
        "hashtag_recommended_max": 8,
        "hashtag_hard_max": 30,
        "media_required": True,
        "supported_media_types": ["video"],
        "link_allowed": False,
        "cta_recommended": True,
        "emoji_recommended_max_ratio": 0.20,
        "notes": "media_required=video is a hard constraint for typical posts; other limits mix hard and recommended.",
    },
    "linkedin": {
        "label": "LinkedIn",
        "caption_recommended_min": 80,
        "caption_recommended_max": 1300,
        "caption_hard_max": 3000,
        "hashtag_recommended_min": 1,
        "hashtag_recommended_max": 5,
        "hashtag_hard_max": 15,
        "media_required": False,
        "supported_media_types": ["image", "video"],
        "link_allowed": True,
        "cta_recommended": True,
        "emoji_recommended_max_ratio": 0.08,
        "notes": "Recommended professional tone lengths are internal guidelines.",
    },
}


def get_policy(platform: str) -> dict[str, Any] | None:
    return _PLATFORM_POLICIES.get(platform.lower())


def list_policies() -> dict[str, Any]:
    return {
        "catalog_version": POLICY_CATALOG_VERSION,
        "platforms": {
            key: {**value, "platform": key}
            for key, value in _PLATFORM_POLICIES.items()
        },
        "category_weights": dict(CATEGORY_WEIGHTS),
        "critical_score_cap": CRITICAL_SCORE_CAP,
        "low_score_threshold": LOW_SCORE_THRESHOLD,
        "constraint_legend": {
            "hard": "Provider-enforced or project-adapter limit",
            "recommended": "Internal guideline — not a hard platform restriction",
        },
    }


def check_catalog() -> dict[str, Any]:
    """Stable catalog of check keys exposed to clients."""
    return {
        "engine_version": "1.0.0",
        "categories": sorted(CATEGORY_WEIGHTS.keys()),
        "checks": [
            {"key": "caption_present", "category": "caption_quality"},
            {"key": "caption_minimum_length", "category": "caption_quality"},
            {"key": "caption_maximum_length", "category": "caption_quality"},
            {"key": "opening_strength_heuristic", "category": "caption_quality"},
            {"key": "paragraph_readability", "category": "caption_quality"},
            {"key": "sentence_length", "category": "caption_quality"},
            {"key": "excessive_repetition", "category": "caption_quality"},
            {"key": "excessive_uppercase", "category": "caption_quality"},
            {"key": "excessive_punctuation", "category": "caption_quality"},
            {"key": "emoji_density", "category": "caption_quality"},
            {"key": "link_presence", "category": "caption_quality"},
            {"key": "platform_caption_fit", "category": "platform_fit"},
            {"key": "cta_present", "category": "cta_quality"},
            {"key": "cta_action_verb", "category": "cta_quality"},
            {"key": "cta_specificity", "category": "cta_quality"},
            {"key": "cta_position", "category": "cta_quality"},
            {"key": "multiple_conflicting_ctas", "category": "cta_quality"},
            {"key": "cta_platform_fit", "category": "cta_quality"},
            {"key": "hashtag_count", "category": "hashtag_quality"},
            {"key": "duplicate_hashtags", "category": "hashtag_quality"},
            {"key": "invalid_format", "category": "hashtag_quality"},
            {"key": "overly_long_hashtag", "category": "hashtag_quality"},
            {"key": "generic_hashtag_ratio", "category": "hashtag_quality"},
            {"key": "platform_hashtag_fit", "category": "hashtag_quality"},
            {"key": "caption_hashtag_repetition", "category": "hashtag_quality"},
            {"key": "keywords_present", "category": "keyword_readiness"},
            {"key": "keyword_in_title", "category": "keyword_readiness"},
            {"key": "keyword_in_opening", "category": "keyword_readiness"},
            {"key": "keyword_stuffing", "category": "keyword_readiness"},
            {"key": "keyword_distribution", "category": "keyword_readiness"},
            {"key": "platform_keyword_fit", "category": "keyword_readiness"},
            {"key": "media_present_when_required", "category": "media_readiness"},
            {"key": "media_processing_complete", "category": "media_readiness"},
            {"key": "supported_media_type", "category": "media_readiness"},
            {"key": "file_size_within_limit", "category": "media_readiness"},
            {"key": "aspect_ratio_recommended", "category": "media_readiness"},
            {"key": "resolution_minimum", "category": "media_readiness"},
            {"key": "video_duration_fit", "category": "media_readiness"},
            {"key": "thumbnail_ready", "category": "media_readiness"},
            {"key": "missing_alt_text", "category": "media_readiness"},
            {"key": "language_present", "category": "language_quality"},
            {"key": "language_matches_selected_locale", "category": "language_quality"},
            {"key": "mixed_script_ratio", "category": "language_quality"},
            {"key": "empty_translation", "category": "translation_readiness"},
            {"key": "translation_language_mismatch", "category": "translation_readiness"},
            {"key": "translation_completeness", "category": "translation_readiness"},
            {"key": "unsupported_language", "category": "language_quality"},
            {"key": "excessive_untranslated_segments", "category": "translation_readiness"},
            {"key": "missing_required_disclosure", "category": "compliance_readiness"},
            {"key": "forbidden_placeholder", "category": "compliance_readiness"},
            {"key": "unsupported_link_scheme", "category": "compliance_readiness"},
            {"key": "sensitive_secret_pattern", "category": "compliance_readiness"},
            {"key": "internal_test_text", "category": "compliance_readiness"},
            {"key": "draft_marker_present", "category": "compliance_readiness"},
            {"key": "prohibited_token_pattern", "category": "compliance_readiness"},
            {"key": "scheduled_time_present", "category": "scheduling_readiness"},
            {"key": "scheduled_time_in_future", "category": "scheduling_readiness"},
            {"key": "publishing_accounts_selected", "category": "scheduling_readiness"},
            {"key": "platform_account_available", "category": "scheduling_readiness"},
            {"key": "integration_connected", "category": "scheduling_readiness"},
            {"key": "content_status_allows_publish", "category": "scheduling_readiness"},
            {"key": "approval_status_allows_publish", "category": "scheduling_readiness"},
        ],
    }
