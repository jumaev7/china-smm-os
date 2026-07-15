"""Deterministic caption-quality checks."""
from __future__ import annotations

import re

from app.services.publishing_intelligence.checks._helpers import (
    check,
    emoji_ratio,
    find_urls,
    primary_caption,
    punctuation_run_score,
    uppercase_ratio,
    word_tokens,
)
from app.services.publishing_intelligence.platform_policies import get_policy
from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext

_OPENING_BOOST = re.compile(
    r"^(\d+|why|how|what|when|discover|meet|introducing|new|save|get|learn|"
    r"почему|как|что|узнайте|новый|скидка|"
    r"nima\s+uchun|qanday|yangi|"
    r"为什么|如何|什么|新|发现)",
    re.IGNORECASE,
)


def run_caption_checks(ctx: ReviewContext) -> list[CheckResult]:
    text = primary_caption(ctx)
    results: list[CheckResult] = []
    length = len(text.strip())

    if length == 0:
        results.append(
            check(
                "caption_present",
                "caption_quality",
                "failed",
                score=0,
                weight=3,
                severity="error",
                evidence={"length": 0},
                recommendation_key="add_caption",
            )
        )
        # Remaining caption checks are N/A when empty
        for key in (
            "caption_minimum_length",
            "caption_maximum_length",
            "opening_strength_heuristic",
            "paragraph_readability",
            "sentence_length",
            "excessive_repetition",
            "excessive_uppercase",
            "excessive_punctuation",
            "emoji_density",
            "link_presence",
        ):
            results.append(
                check(key, "caption_quality", "not_applicable", evidence={"reason": "no_caption"})
            )
        return results

    results.append(
        check(
            "caption_present",
            "caption_quality",
            "passed",
            score=100,
            weight=3,
            evidence={"length": length},
        )
    )

    # Platform-agnostic min/max using strictest recommended across targets, fallback defaults
    min_len = 20
    max_hard = 4096
    for platform in ctx.platforms:
        policy = get_policy(platform)
        if not policy:
            continue
        min_len = min(min_len, int(policy["caption_recommended_min"]))
        max_hard = min(max_hard, int(policy["caption_hard_max"]))

    if length < min_len:
        results.append(
            check(
                "caption_minimum_length",
                "caption_quality",
                "warning",
                score=max(0, int(100 * length / min_len)),
                weight=2,
                severity="warning",
                evidence={"length": length, "recommended_min": min_len},
                recommendation_key="expand_caption",
                recommendation_params={"recommended_min": min_len},
            )
        )
    else:
        results.append(
            check(
                "caption_minimum_length",
                "caption_quality",
                "passed",
                score=100,
                weight=2,
                evidence={"length": length, "recommended_min": min_len},
            )
        )

    if length > max_hard:
        results.append(
            check(
                "caption_maximum_length",
                "caption_quality",
                "failed",
                score=0,
                weight=3,
                severity="error",
                evidence={"length": length, "hard_max": max_hard},
                recommendation_key="shorten_caption",
                recommendation_params={"hard_max": max_hard},
            )
        )
    else:
        results.append(
            check(
                "caption_maximum_length",
                "caption_quality",
                "passed",
                score=100,
                weight=2,
                evidence={"length": length, "hard_max": max_hard},
            )
        )

    # Opening strength heuristic (not AI understanding)
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    first_sentence = re.split(r"[.!?。！？]", first_line, maxsplit=1)[0].strip()
    opening_ok = bool(first_sentence) and len(first_line) <= 160
    starts_strong = bool(_OPENING_BOOST.search(first_sentence))
    starts_clean = not re.match(r"^[\s.!?,;:]+", text)
    opening_score = 40
    if opening_ok:
        opening_score += 30
    if starts_strong:
        opening_score += 20
    if starts_clean:
        opening_score += 10
    results.append(
        check(
            "opening_strength_heuristic",
            "caption_quality",
            "passed" if opening_score >= 70 else "warning",
            score=min(100, opening_score),
            weight=2,
            severity="info" if opening_score >= 70 else "warning",
            evidence={
                "first_line_length": len(first_line),
                "starts_strong_heuristic": starts_strong,
                "starts_clean": starts_clean,
                "note": "Deterministic heuristic — not semantic AI understanding",
            },
            recommendation_key="strengthen_opening" if opening_score < 70 else None,
        )
    )

    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    avg_para = sum(len(p) for p in paragraphs) / max(len(paragraphs), 1)
    para_ok = len(paragraphs) <= 8 and avg_para <= 600
    results.append(
        check(
            "paragraph_readability",
            "caption_quality",
            "passed" if para_ok else "warning",
            score=100 if para_ok else 60,
            weight=1,
            severity="info" if para_ok else "warning",
            evidence={"paragraph_count": len(paragraphs), "avg_paragraph_length": int(avg_para)},
            recommendation_key="split_paragraphs" if not para_ok else None,
        )
    )

    sentences = [s.strip() for s in re.split(r"[.!?。！？]+", text) if s.strip()]
    long_sentences = sum(1 for s in sentences if len(s) > 200)
    sentence_ok = long_sentences == 0
    results.append(
        check(
            "sentence_length",
            "caption_quality",
            "passed" if sentence_ok else "warning",
            score=100 if sentence_ok else max(40, 100 - long_sentences * 20),
            weight=1,
            evidence={"sentence_count": len(sentences), "long_sentences": long_sentences},
            recommendation_key="shorten_sentences" if not sentence_ok else None,
        )
    )

    words = word_tokens(text)
    repetition = 0
    if words:
        from collections import Counter

        counts = Counter(words)
        repetition = sum(1 for w, c in counts.items() if c >= 5 and len(w) > 3)
    results.append(
        check(
            "excessive_repetition",
            "caption_quality",
            "passed" if repetition == 0 else "warning",
            score=100 if repetition == 0 else max(30, 100 - repetition * 25),
            weight=1,
            severity="warning" if repetition else "info",
            evidence={"repeated_word_groups": repetition},
            recommendation_key="reduce_repetition" if repetition else None,
        )
    )

    up_ratio = uppercase_ratio(text)
    up_ok = up_ratio <= 0.45
    results.append(
        check(
            "excessive_uppercase",
            "caption_quality",
            "passed" if up_ok else "warning",
            score=100 if up_ok else max(20, int(100 - up_ratio * 100)),
            weight=1,
            severity="warning" if not up_ok else "info",
            evidence={"uppercase_ratio": round(up_ratio, 3)},
            recommendation_key="reduce_uppercase" if not up_ok else None,
        )
    )

    punct_runs = punctuation_run_score(text)
    results.append(
        check(
            "excessive_punctuation",
            "caption_quality",
            "passed" if punct_runs == 0 else "warning",
            score=100 if punct_runs == 0 else max(40, 100 - punct_runs * 20),
            weight=1,
            evidence={"excessive_runs": punct_runs},
            recommendation_key="reduce_punctuation" if punct_runs else None,
        )
    )

    e_ratio = emoji_ratio(text)
    e_ok = e_ratio <= 0.20
    results.append(
        check(
            "emoji_density",
            "caption_quality",
            "passed" if e_ok else "warning",
            score=100 if e_ok else max(40, int(100 - e_ratio * 200)),
            weight=1,
            evidence={"emoji_ratio": round(e_ratio, 3)},
            recommendation_key="reduce_emoji" if not e_ok else None,
        )
    )

    urls = find_urls(text)
    # Informational presence only — platform fit handled elsewhere
    results.append(
        check(
            "link_presence",
            "caption_quality",
            "passed",
            score=100,
            weight=1,
            evidence={"url_count": len(urls), "has_link": len(urls) > 0},
        )
    )

    return results
