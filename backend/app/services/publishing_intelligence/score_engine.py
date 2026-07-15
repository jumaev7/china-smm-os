"""Deterministic Publishing Score calculation (0–100, versioned, explainable)."""
from __future__ import annotations

from typing import Any

from app.services.publishing_intelligence.platform_policies import (
    CATEGORY_WEIGHTS,
    CRITICAL_SCORE_CAP,
)
from app.services.publishing_intelligence.schemas import (
    CategoryScore,
    CheckResult,
    PlatformReviewResult,
    RecommendationItem,
)

SCORE_ENGINE_VERSION = "1.0.0"


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def score_category(category: str, checks: list[CheckResult]) -> CategoryScore:
    applicable = [c for c in checks if c.status != "not_applicable" and c.score is not None]
    if not applicable:
        return CategoryScore(
            category=category,
            score=0,
            weight=CATEGORY_WEIGHTS.get(category, 0),
            applicable=False,
            evidence={"reason": "all_checks_not_applicable"},
            check_count=len(checks),
        )

    weight_sum = sum(max(1, c.weight) for c in applicable)
    weighted = sum((c.score or 0) * max(1, c.weight) for c in applicable)
    score = _clamp(int(round(weighted / weight_sum)))

    # Critical failure in category caps that category
    if any(c.status == "failed" and c.severity == "critical" for c in applicable):
        score = min(score, CRITICAL_SCORE_CAP)

    return CategoryScore(
        category=category,
        score=score,
        weight=CATEGORY_WEIGHTS.get(category, 0),
        applicable=True,
        evidence={
            "checks": [
                {"key": c.check_key, "status": c.status, "score": c.score, "weight": c.weight}
                for c in applicable
            ]
        },
        check_count=len(applicable),
        warning_count=sum(1 for c in applicable if c.status == "warning"),
        failure_count=sum(1 for c in applicable if c.status == "failed"),
    )


def compute_category_scores(checks: list[CheckResult]) -> dict[str, CategoryScore]:
    by_cat: dict[str, list[CheckResult]] = {}
    for c in checks:
        by_cat.setdefault(c.category, []).append(c)

    results: dict[str, CategoryScore] = {}
    for category in CATEGORY_WEIGHTS:
        results[category] = score_category(category, by_cat.get(category, []))
    return results


def compute_overall_score(category_scores: dict[str, CategoryScore]) -> tuple[int, dict[str, Any]]:
    """Weighted average over applicable categories only (N/A must not unfairly reduce)."""
    numerator = 0
    denominator = 0
    used: dict[str, int] = {}
    for category, weight in CATEGORY_WEIGHTS.items():
        cs = category_scores.get(category)
        if not cs or not cs.applicable or weight <= 0:
            continue
        numerator += cs.score * weight
        denominator += weight
        used[category] = cs.score

    if denominator == 0:
        return 0, {"reason": "no_applicable_categories", "category_scores": used}

    overall = _clamp(int(round(numerator / denominator)))

    # Critical failures across any check may cap overall
    critical_failed = any(
        cs.failure_count > 0
        and any(
            item.get("status") == "failed"
            for item in (cs.evidence.get("checks") or [])
        )
        for cs in category_scores.values()
        if cs.applicable
    )
    # Cap only when compliance/media critical-style categories heavily failed
    hard_cap = False
    for cat in ("compliance_readiness", "media_readiness"):
        cs = category_scores.get(cat)
        if cs and cs.applicable and cs.score <= CRITICAL_SCORE_CAP and cs.failure_count > 0:
            hard_cap = True
            break
    if hard_cap:
        overall = min(overall, CRITICAL_SCORE_CAP)

    return overall, {
        "denominator_weight": denominator,
        "category_scores": used,
        "critical_cap_applied": hard_cap and critical_failed,
        "engine_version": SCORE_ENGINE_VERSION,
    }


def compute_platform_reviews(
    platforms: list[str],
    checks: list[CheckResult],
    category_scores: dict[str, CategoryScore],
) -> list[PlatformReviewResult]:
    results: list[PlatformReviewResult] = []
    platform_fit = next((c for c in checks if c.check_key == "platform_caption_fit"), None)
    fit_by_platform: dict[str, int] = {}
    if platform_fit and isinstance(platform_fit.evidence.get("platforms"), list):
        for item in platform_fit.evidence["platforms"]:
            if isinstance(item, dict) and item.get("platform"):
                fit_by_platform[str(item["platform"])] = int(item.get("score") or 0)

    for platform in sorted(platforms):
        caption = category_scores.get("caption_quality")
        media = category_scores.get("media_readiness")
        cta = category_scores.get("cta_quality")
        hashtag = category_scores.get("hashtag_quality")
        language = category_scores.get("language_quality")
        compliance = category_scores.get("compliance_readiness")
        fit_score = fit_by_platform.get(platform)

        parts: list[tuple[int, int]] = []
        for score, weight in (
            (fit_score if fit_score is not None else (caption.score if caption and caption.applicable else None), 3),
            (caption.score if caption and caption.applicable else None, 2),
            (media.score if media and media.applicable else None, 2),
            (cta.score if cta and cta.applicable else None, 1),
            (hashtag.score if hashtag and hashtag.applicable else None, 1),
            (language.score if language and language.applicable else None, 1),
            (compliance.score if compliance and compliance.applicable else None, 1),
        ):
            if score is None:
                continue
            parts.append((score, weight))

        if parts:
            platform_score = _clamp(
                int(round(sum(s * w for s, w in parts) / sum(w for _, w in parts)))
            )
        else:
            platform_score = 0

        recs: list[dict[str, Any]] = []
        for c in checks:
            if c.status in {"warning", "failed"} and c.recommendation_key:
                params = c.recommendation_params or {}
                if params.get("platform") in (None, platform) or platform in (params.get("platforms") or []):
                    recs.append(
                        {
                            "key": c.recommendation_key,
                            "check_key": c.check_key,
                            "status": c.status,
                            "params": params,
                        }
                    )

        results.append(
            PlatformReviewResult(
                platform=platform,
                platform_score=platform_score,
                caption_score=caption.score if caption and caption.applicable else None,
                media_score=media.score if media and media.applicable else None,
                cta_score=cta.score if cta and cta.applicable else None,
                hashtag_score=hashtag.score if hashtag and hashtag.applicable else None,
                language_score=language.score if language and language.applicable else None,
                compliance_score=compliance.score if compliance and compliance.applicable else None,
                recommendations=recs[:12],
            )
        )
    return results


_REC_ACTIONS: dict[str, tuple[str, str, str]] = {
    # key -> priority, reason, suggested_action
    "add_caption": ("critical", "Caption is missing", "Add a caption before publishing"),
    "expand_caption": ("medium", "Caption is shorter than recommended", "Expand the caption to the recommended minimum length"),
    "shorten_caption": ("high", "Caption exceeds platform hard limit", "Shorten the caption to fit the platform maximum"),
    "shorten_caption_for_platform": ("high", "Caption exceeds a platform hard limit", "Shorten the caption for the affected platform"),
    "review_caption_length_for_platform": ("medium", "Caption length is outside platform recommendation", "Review caption length for the target platform"),
    "expand_caption_for_platform": ("medium", "Caption is short for the platform", "Expand caption for better platform fit"),
    "strengthen_opening": ("low", "Opening strength heuristic is weak", "Rewrite the first line with a clear topic or benefit"),
    "improve_cta_before_publishing": ("high", "No CTA phrase detected", "Improve CTA before publishing"),
    "add_cta_for_platforms": ("medium", "CTA recommended for selected platforms", "Add a clear call to action"),
    "prefer_specific_cta": ("low", "CTA is generic", "Prefer a more specific action verb"),
    "move_cta_near_end": ("low", "CTA appears early in the caption", "Place the CTA nearer the end"),
    "resolve_conflicting_ctas": ("high", "Multiple competing CTAs detected", "Keep a single primary CTA"),
    "add_hashtags": ("medium", "Too few hashtags for platform guidance", "Add relevant hashtags"),
    "reduce_hashtags": ("medium", "Too many hashtags for platform guidance", "Reduce hashtag count"),
    "remove_duplicate_hashtags": ("medium", "Duplicate hashtags detected", "Remove duplicate hashtags"),
    "fix_hashtag_format": ("high", "Invalid hashtag format", "Fix hashtag formatting"),
    "add_required_platform_media": ("critical", "Required platform media is missing", "Add required platform media"),
    "complete_media_upload": ("critical", "Media upload/processing incomplete", "Finish media upload before publishing"),
    "use_supported_media_type": ("critical", "Media type unsupported for platform", "Use a supported media type"),
    "complete_missing_translation": ("high", "Translation incomplete", "Complete missing translation"),
    "translate_copied_source": ("medium", "Target translation matches source text", "Provide a distinct translation"),
    "remove_translation_placeholders": ("high", "Placeholder text in translation", "Remove translation placeholders"),
    "remove_placeholders": ("critical", "Placeholder tokens in caption", "Remove draft/placeholder text"),
    "remove_secrets_from_caption": ("critical", "Secret-like pattern in caption", "Remove secrets from caption"),
    "reconnect_publishing_account": ("high", "Publishing account unavailable", "Reconnect selected publishing account"),
    "select_platforms": ("high", "No target platforms selected", "Select at least one publishing platform"),
    "approve_content_before_publish": ("medium", "Content not admin-approved", "Approve content before publishing"),
    "resolve_client_changes": ("high", "Client requested changes", "Resolve client change requests"),
    "set_scheduled_time": ("high", "Scheduled content missing time", "Set a scheduled publish time"),
    "reschedule_publish_time": ("high", "Scheduled time is not in the future", "Reschedule to a future time"),
}


def build_recommendations(checks: list[CheckResult]) -> list[RecommendationItem]:
    items: list[RecommendationItem] = []
    seen: set[str] = set()
    for c in checks:
        if c.status not in {"warning", "failed"} or not c.recommendation_key:
            continue
        key = c.recommendation_key
        if key in seen:
            continue
        seen.add(key)
        priority, reason, action = _REC_ACTIONS.get(
            key,
            (
                "medium" if c.status == "warning" else "high",
                f"Check {c.check_key} returned {c.status}",
                f"Review {c.check_key}",
            ),
        )
        if c.severity == "critical":
            priority = "critical"
        items.append(
            RecommendationItem(
                key=key,
                category=c.category,
                priority=priority,
                reason=reason,
                evidence_summary=str(
                    {k: v for k, v in (c.evidence or {}).items() if k != "note"}
                )[:240],
                suggested_action=action,
                params=c.recommendation_params or {},
            )
        )
    priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items.sort(key=lambda r: (priority_rank.get(r.priority, 9), r.key))
    return items
