"""Keyword readiness — only tenant/content-provided keywords (no SEO inference)."""
from __future__ import annotations

from app.services.publishing_intelligence.checks._helpers import check, primary_caption, word_tokens
from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext


def run_keyword_checks(ctx: ReviewContext) -> list[CheckResult]:
    keywords = [k.lower().strip() for k in ctx.keywords if k and k.strip()]
    results: list[CheckResult] = []

    if not keywords:
        for key in (
            "keywords_present",
            "keyword_in_title",
            "keyword_in_opening",
            "keyword_stuffing",
            "keyword_distribution",
            "platform_keyword_fit",
        ):
            results.append(
                check(
                    key,
                    "keyword_readiness",
                    "not_applicable",
                    evidence={"reason": "no_keywords_configured"},
                )
            )
        return results

    text = primary_caption(ctx)
    lowered = text.lower()
    results.append(
        check(
            "keywords_present",
            "keyword_readiness",
            "passed",
            score=100,
            weight=2,
            evidence={"keyword_count": len(keywords)},
        )
    )

    # No dedicated title field — use first line as title proxy
    first_line = text.strip().splitlines()[0].lower() if text.strip() else ""
    in_title = sum(1 for k in keywords if k in first_line)
    results.append(
        check(
            "keyword_in_title",
            "keyword_readiness",
            "passed" if in_title else "warning",
            score=100 if in_title else 55,
            weight=1,
            evidence={"matched": in_title, "note": "Uses first line as title proxy (no title field)"},
            recommendation_key="add_keyword_to_opening" if not in_title else None,
        )
    )

    opening = text[:200].lower()
    in_opening = sum(1 for k in keywords if k in opening)
    results.append(
        check(
            "keyword_in_opening",
            "keyword_readiness",
            "passed" if in_opening else "warning",
            score=100 if in_opening else 50,
            weight=2,
            evidence={"matched": in_opening},
            recommendation_key="add_keyword_to_opening" if not in_opening else None,
        )
    )

    words = word_tokens(text)
    stuffing = False
    for k in keywords:
        parts = k.split()
        if len(parts) == 1 and words:
            density = words.count(parts[0]) / len(words)
            if density > 0.08:
                stuffing = True
                break
        elif lowered.count(k) >= 5:
            stuffing = True
            break
    results.append(
        check(
            "keyword_stuffing",
            "keyword_readiness",
            "failed" if stuffing else "passed",
            score=25 if stuffing else 100,
            weight=2,
            severity="error" if stuffing else "info",
            evidence={"stuffing_detected": stuffing},
            recommendation_key="reduce_keyword_stuffing" if stuffing else None,
        )
    )

    # Distribution: keywords appear in more than one segment
    thirds = [text[: len(text) // 3], text[len(text) // 3 : 2 * len(text) // 3], text[2 * len(text) // 3 :]]
    segments_hit = sum(1 for seg in thirds if any(k in seg.lower() for k in keywords))
    results.append(
        check(
            "keyword_distribution",
            "keyword_readiness",
            "passed" if segments_hit >= 2 or len(text) < 120 else "warning",
            score=100 if segments_hit >= 2 or len(text) < 120 else 65,
            weight=1,
            evidence={"segments_with_keywords": segments_hit},
        )
    )

    # Platform keyword fit — soft rule: keywords present is enough
    results.append(
        check(
            "platform_keyword_fit",
            "keyword_readiness",
            "passed",
            score=100,
            weight=1,
            evidence={"platforms": sorted(ctx.platforms), "note": "No AI SEO inference"},
        )
    )
    return results
