"""Deterministic hashtag analysis (no trend popularity claims)."""
from __future__ import annotations

import re

from app.services.publishing_intelligence.checks._helpers import check, primary_caption
from app.services.publishing_intelligence.platform_policies import get_policy
from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext

_HASHTAG_RE = re.compile(r"#([^\s#]+)")
_VALID_TAG = re.compile(r"^[\w]+$", re.UNICODE)
_GENERIC = frozenset({
    "love", "instagood", "photooftheday", "beautiful", "happy", "cute", "followme",
    "tbt", "likeer", "picoftheday", "follow", "me", "selfie", "summer", "art",
    "instadaily", "friends", "repost", "nature", "girl", "fun", "style", "smile",
    "food", "instalike", "family", "travel", "likeforlike", "fitness", "igers",
})


def run_hashtag_checks(ctx: ReviewContext) -> list[CheckResult]:
    tags = list(ctx.hashtags)
    caption = primary_caption(ctx)
    caption_tags = [m.group(1) for m in _HASHTAG_RE.finditer(caption)]
    all_tags = tags or [t.lower() for t in caption_tags]
    # Prefer explicit hashtags field; merge caption tags uniquely
    seen: set[str] = set()
    ordered: list[str] = []
    for t in [*tags, *[x.lower() for x in caption_tags]]:
        key = t.lower().lstrip("#")
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)

    results: list[CheckResult] = []
    count = len(ordered)

    # Platform recommended ranges
    rec_min = 0
    rec_max = 30
    for platform in ctx.platforms:
        policy = get_policy(platform)
        if not policy:
            continue
        rec_min = max(rec_min, int(policy["hashtag_recommended_min"]))
        rec_max = min(rec_max, int(policy["hashtag_recommended_max"]))

    if count < rec_min:
        results.append(
            check(
                "hashtag_count",
                "hashtag_quality",
                "warning",
                score=max(30, int(100 * count / max(rec_min, 1))),
                weight=2,
                severity="warning",
                evidence={"count": count, "recommended_min": rec_min, "recommended_max": rec_max},
                recommendation_key="add_hashtags",
                recommendation_params={"recommended_min": rec_min},
            )
        )
    elif count > rec_max:
        results.append(
            check(
                "hashtag_count",
                "hashtag_quality",
                "warning",
                score=max(40, 100 - (count - rec_max) * 8),
                weight=2,
                severity="warning",
                evidence={"count": count, "recommended_min": rec_min, "recommended_max": rec_max},
                recommendation_key="reduce_hashtags",
                recommendation_params={"recommended_max": rec_max},
            )
        )
    else:
        results.append(
            check(
                "hashtag_count",
                "hashtag_quality",
                "passed",
                score=100,
                weight=2,
                evidence={"count": count, "recommended_min": rec_min, "recommended_max": rec_max},
            )
        )

    # Duplicates from raw sources
    raw_all = [t.lower().lstrip("#") for t in [*tags, *[x.lower() for x in caption_tags]] if t]
    dup_count = len(raw_all) - len(set(raw_all))
    results.append(
        check(
            "duplicate_hashtags",
            "hashtag_quality",
            "passed" if dup_count == 0 else "warning",
            score=100 if dup_count == 0 else max(40, 100 - dup_count * 20),
            weight=2,
            evidence={"duplicate_count": dup_count},
            recommendation_key="remove_duplicate_hashtags" if dup_count else None,
        )
    )

    invalid = [t for t in ordered if not _VALID_TAG.match(t) or t.isdigit()]
    results.append(
        check(
            "invalid_format",
            "hashtag_quality",
            "passed" if not invalid else "failed",
            score=100 if not invalid else 20,
            weight=2,
            severity="error" if invalid else "info",
            evidence={"invalid_count": len(invalid)},
            recommendation_key="fix_hashtag_format" if invalid else None,
        )
    )

    long_tags = [t for t in ordered if len(t) > 30]
    results.append(
        check(
            "overly_long_hashtag",
            "hashtag_quality",
            "passed" if not long_tags else "warning",
            score=100 if not long_tags else 50,
            weight=1,
            evidence={"long_count": len(long_tags)},
            recommendation_key="shorten_hashtags" if long_tags else None,
        )
    )

    if count == 0:
        results.append(
            check(
                "generic_hashtag_ratio",
                "hashtag_quality",
                "not_applicable",
                evidence={"reason": "no_hashtags"},
            )
        )
    else:
        generic = sum(1 for t in ordered if t in _GENERIC)
        ratio = generic / count
        results.append(
            check(
                "generic_hashtag_ratio",
                "hashtag_quality",
                "passed" if ratio <= 0.5 else "warning",
                score=100 if ratio <= 0.5 else max(30, int(100 - ratio * 100)),
                weight=1,
                evidence={"generic_ratio": round(ratio, 3), "note": "Rule-based list — not trend data"},
                recommendation_key="use_specific_hashtags" if ratio > 0.5 else None,
            )
        )

    # Platform hashtag fit
    platform_notes = []
    worst = "passed"
    score = 100
    for platform in sorted(ctx.platforms):
        policy = get_policy(platform)
        if not policy:
            continue
        p_min = int(policy["hashtag_recommended_min"])
        p_max = int(policy["hashtag_recommended_max"])
        p_hard = int(policy["hashtag_hard_max"])
        if count > p_hard:
            worst = "failed"
            score = min(score, 20)
        elif count < p_min or count > p_max:
            if worst == "passed":
                worst = "warning"
            score = min(score, 65)
        platform_notes.append({"platform": platform, "recommended": [p_min, p_max], "count": count})

    results.append(
        check(
            "platform_hashtag_fit",
            "hashtag_quality",
            worst if ctx.platforms else "not_applicable",
            score=score if ctx.platforms else None,
            weight=2,
            evidence={"platforms": platform_notes, "note": "Recommendations only — no fabricated popularity"},
            recommendation_key="adjust_hashtags_for_platform" if worst != "passed" else None,
        )
    )

    # Caption body repeating same hashtag block excessively
    tagged_in_caption = len(caption_tags)
    repetition_issue = tagged_in_caption > 0 and tags and set(t.lower().lstrip("#") for t in tags) == set(
        t.lower() for t in caption_tags
    ) and tagged_in_caption > 10
    results.append(
        check(
            "caption_hashtag_repetition",
            "hashtag_quality",
            "warning" if repetition_issue else "passed",
            score=50 if repetition_issue else 100,
            weight=1,
            evidence={"caption_hashtag_count": tagged_in_caption, "field_hashtag_count": len(tags)},
            recommendation_key="dedupe_hashtag_blocks" if repetition_issue else None,
        )
    )
    return results
