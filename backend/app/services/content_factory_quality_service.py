"""Content quality scoring for AI Content Factory."""
from __future__ import annotations

import re
from typing import Any


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def _has_cta(text: str) -> bool:
    lower = text.lower()
    cta_markers = (
        "contact", "call", "visit", "learn more", "order", "inquiry",
        "связ", "заказ", "узнай", "подробн", "bog'lan", "buyurtma",
        "联系", "咨询", "订购", "了解",
    )
    return any(m in lower for m in cta_markers)


def _has_hashtags(text: str) -> bool:
    return "#" in text and len(re.findall(r"#\w+", text)) >= 2


def score_content(
    *,
    captions: dict[str, str],
    hashtags: str | None,
    headline: str | None,
    cta: str | None,
    platforms: list[str],
    target_languages: list[str],
    content_category: str | None = None,
) -> dict[str, Any]:
    """Return quality, readability, engagement, completeness scores (0-100) + recommendations."""
    all_text = " ".join(
        v for v in list(captions.values()) + [hashtags or "", headline or "", cta or ""] if v
    )
    words = _word_count(all_text)

    # Quality: structure + CTA + hashtags
    quality = 40
    if headline and len(headline.strip()) >= 10:
        quality += 15
    if cta and len(cta.strip()) >= 8:
        quality += 15
    if hashtags and _has_hashtags(hashtags):
        quality += 15
    if any(_has_cta(v) for v in captions.values()):
        quality += 15
    quality = min(100, quality)

    # Readability: length balance
    readability = 50
    avg_len = sum(len(v) for v in captions.values() if v) / max(len([v for v in captions.values() if v]), 1)
    if 80 <= avg_len <= 400:
        readability += 30
    elif 40 <= avg_len <= 600:
        readability += 15
    if words >= 20:
        readability += 20
    readability = min(100, readability)

    # Engagement: hooks, questions, hashtags
    engagement = 35
    if "?" in all_text:
        engagement += 15
    if hashtags and len(re.findall(r"#\w+", hashtags)) >= 5:
        engagement += 20
    if any(len(v) >= 100 for v in captions.values()):
        engagement += 15
    if len(platforms) >= 2:
        engagement += 15
    engagement = min(100, engagement)

    # Completeness: languages + platforms + fields
    lang_covered = 0
    for lang in target_languages:
        keys = [f"caption_short_{lang}", f"caption_long_{lang}", lang]
        if any(str(captions.get(k) or "").strip() for k in keys):
            lang_covered += 1

    completeness = 20 + lang_covered * (60 // max(len(target_languages), 1))
    if platforms:
        completeness += 10
    if headline:
        completeness += 5
    if cta:
        completeness += 5
    completeness = min(100, completeness)

    recommendations: list[str] = []
    if lang_covered < len(target_languages):
        missing = [
            lang for lang in target_languages
            if not any(
                str(captions.get(k) or "").strip()
                for k in (f"caption_short_{lang}", f"caption_long_{lang}", lang)
            )
        ]
        if missing:
            recommendations.append(f"Add captions for: {', '.join(missing)}")
    if not cta or not _has_cta(all_text):
        recommendations.append("Add a clear call-to-action (contact, inquiry, or visit)")
    if not hashtags or not _has_hashtags(hashtags):
        recommendations.append("Include 5–10 relevant hashtags")
    if not headline:
        recommendations.append("Add a headline for better engagement")
    if content_category == "product_announcement" and "product" not in all_text.lower():
        recommendations.append("Mention product name or model in captions")
    if engagement < 60:
        recommendations.append("Consider adding a question or buyer-focused hook")

    overall = round((quality + readability + engagement + completeness) / 4)

    return {
        "quality_score": quality,
        "readability_score": readability,
        "engagement_score": engagement,
        "completeness_score": completeness,
        "overall_score": overall,
        "recommendations": recommendations,
    }
