"""Platform-specific caption/media fit checks."""
from __future__ import annotations

from app.services.publishing_intelligence.checks._helpers import check, find_urls, primary_caption
from app.services.publishing_intelligence.platform_policies import get_policy
from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext


def run_platform_fit_checks(ctx: ReviewContext) -> list[CheckResult]:
    text = primary_caption(ctx)
    length = len(text.strip())
    results: list[CheckResult] = []

    if not ctx.platforms:
        results.append(
            check(
                "platform_caption_fit",
                "platform_fit",
                "failed",
                score=0,
                weight=3,
                severity="error",
                evidence={"platforms": []},
                recommendation_key="select_platforms",
            )
        )
        return results

    scores: list[int] = []
    details: list[dict] = []
    worst_status = "passed"
    rec_key = None
    rec_params = None

    for platform in sorted(ctx.platforms):
        policy = get_policy(platform)
        if not policy:
            details.append({"platform": platform, "status": "unknown_policy"})
            continue
        hard_max = int(policy["caption_hard_max"])
        rec_max = int(policy["caption_recommended_max"])
        rec_min = int(policy["caption_recommended_min"])
        platform_score = 100
        status = "passed"
        if length == 0:
            platform_score = 0
            status = "failed"
            worst_status = "failed"
            rec_key = "add_caption"
        elif length > hard_max:
            platform_score = 0
            status = "failed"
            worst_status = "failed"
            rec_key = "shorten_caption_for_platform"
            rec_params = {"platform": platform, "hard_max": hard_max}
        elif length > rec_max:
            platform_score = 65
            status = "warning"
            if worst_status == "passed":
                worst_status = "warning"
            rec_key = "review_caption_length_for_platform"
            rec_params = {"platform": platform, "recommended_max": rec_max}
        elif length < rec_min:
            platform_score = 70
            status = "warning"
            if worst_status == "passed":
                worst_status = "warning"
            rec_key = "expand_caption_for_platform"
            rec_params = {"platform": platform, "recommended_min": rec_min}

        urls = find_urls(text)
        if urls and not policy.get("link_allowed", True):
            platform_score = min(platform_score, 55)
            if status == "passed":
                status = "warning"
            if worst_status == "passed":
                worst_status = "warning"
            rec_key = rec_key or "remove_caption_links_for_platform"
            rec_params = rec_params or {"platform": platform}

        if policy.get("media_required") and not ctx.media:
            platform_score = min(platform_score, 20)
            status = "failed"
            worst_status = "failed"
            rec_key = "add_required_platform_media"
            rec_params = {"platform": platform}

        scores.append(platform_score)
        details.append(
            {
                "platform": platform,
                "status": status,
                "score": platform_score,
                "caption_length": length,
                "hard_max": hard_max,
                "recommended_max": rec_max,
            }
        )

    avg = int(round(sum(scores) / len(scores))) if scores else 0
    results.append(
        check(
            "platform_caption_fit",
            "platform_fit",
            worst_status,
            score=avg,
            weight=4,
            severity="error" if worst_status == "failed" else ("warning" if worst_status == "warning" else "info"),
            evidence={"platforms": details},
            recommendation_key=rec_key,
            recommendation_params=rec_params,
        )
    )
    return results
