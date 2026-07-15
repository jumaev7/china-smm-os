"""Deterministic CTA analysis using multilingual phrase catalog."""
from __future__ import annotations

from app.services.publishing_intelligence.checks._helpers import check, primary_caption
from app.services.publishing_intelligence.cta_catalog import detect_ctas, looks_informational
from app.services.publishing_intelligence.platform_policies import get_policy
from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext


def run_cta_checks(ctx: ReviewContext) -> list[CheckResult]:
    text = primary_caption(ctx)
    results: list[CheckResult] = []

    if looks_informational(text) or ctx.content_type == "announcement":
        for key in (
            "cta_present",
            "cta_action_verb",
            "cta_specificity",
            "cta_position",
            "multiple_conflicting_ctas",
            "cta_platform_fit",
        ):
            results.append(
                check(
                    key,
                    "cta_quality",
                    "not_applicable",
                    evidence={"reason": "informational_content"},
                )
            )
        return results

    matches = detect_ctas(text)
    families = sorted({m.family for m in matches})

    if not matches:
        results.append(
            check(
                "cta_present",
                "cta_quality",
                "warning",
                score=35,
                weight=3,
                severity="warning",
                evidence={"match_count": 0},
                recommendation_key="improve_cta_before_publishing",
            )
        )
        for key in ("cta_action_verb", "cta_specificity", "cta_position", "multiple_conflicting_ctas"):
            results.append(
                check(key, "cta_quality", "not_applicable", evidence={"reason": "no_cta"})
            )
    else:
        results.append(
            check(
                "cta_present",
                "cta_quality",
                "passed",
                score=100,
                weight=3,
                evidence={"match_count": len(matches), "families": families},
            )
        )
        results.append(
            check(
                "cta_action_verb",
                "cta_quality",
                "passed",
                score=100,
                weight=2,
                evidence={"families": families},
            )
        )
        # Specificity: prefer buy/request_quote/register/book_demo over learn_more alone
        specific = [f for f in families if f not in {"learn_more", "visit_link"}]
        results.append(
            check(
                "cta_specificity",
                "cta_quality",
                "passed" if specific else "warning",
                score=100 if specific else 60,
                weight=1,
                evidence={"specific_families": specific, "all_families": families},
                recommendation_key="prefer_specific_cta" if not specific else None,
            )
        )
        # Position: prefer CTA in last 40% of caption
        last = matches[-1]
        pos_ratio = last.start / max(len(text), 1)
        near_end = pos_ratio >= 0.45
        results.append(
            check(
                "cta_position",
                "cta_quality",
                "passed" if near_end else "warning",
                score=100 if near_end else 70,
                weight=1,
                evidence={"position_ratio": round(pos_ratio, 3)},
                recommendation_key="move_cta_near_end" if not near_end else None,
            )
        )
        # Conflicting families (buy + register + download simultaneously)
        competing = {"buy", "register", "download", "book_demo", "request_quote"}
        conflict = len(set(families) & competing) >= 3
        results.append(
            check(
                "multiple_conflicting_ctas",
                "cta_quality",
                "failed" if conflict else "passed",
                score=30 if conflict else 100,
                weight=2,
                severity="error" if conflict else "info",
                evidence={"families": families, "conflict": conflict},
                recommendation_key="resolve_conflicting_ctas" if conflict else None,
            )
        )

    # Platform fit
    if not ctx.platforms:
        results.append(
            check("cta_platform_fit", "cta_quality", "not_applicable", evidence={"reason": "no_platforms"})
        )
        return results

    recommended_platforms = [
        p for p in ctx.platforms if (get_policy(p) or {}).get("cta_recommended")
    ]
    if not matches and recommended_platforms:
        results.append(
            check(
                "cta_platform_fit",
                "cta_quality",
                "warning",
                score=40,
                weight=2,
                severity="warning",
                evidence={"platforms": recommended_platforms},
                recommendation_key="add_cta_for_platforms",
                recommendation_params={"platforms": recommended_platforms},
            )
        )
    else:
        results.append(
            check(
                "cta_platform_fit",
                "cta_quality",
                "passed",
                score=100,
                weight=2,
                evidence={"platforms": recommended_platforms, "families": families if matches else []},
            )
        )
    return results
