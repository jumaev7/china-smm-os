"""Shared helpers for publishing review checks."""
from __future__ import annotations

import re
from typing import Any

from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def primary_caption(ctx: ReviewContext) -> str:
    if ctx.primary_language and ctx.captions.get(ctx.primary_language):
        return ctx.captions[ctx.primary_language]
    for lang in ("en", "ru", "uz", "zh"):
        if ctx.captions.get(lang):
            return ctx.captions[lang]
    if ctx.captions:
        return next(iter(ctx.captions.values()))
    return ""


def combined_caption_text(ctx: ReviewContext) -> str:
    return "\n".join(ctx.captions[k] for k in sorted(ctx.captions.keys()) if ctx.captions[k])


def check(
    key: str,
    category: str,
    status: str,
    *,
    score: int | None = None,
    weight: int = 1,
    severity: str = "info",
    evidence: dict[str, Any] | None = None,
    recommendation_key: str | None = None,
    recommendation_params: dict[str, Any] | None = None,
) -> CheckResult:
    return CheckResult(
        check_key=key,
        category=category,
        status=status,
        severity=severity,
        score=score,
        weight=weight,
        evidence=evidence or {},
        recommendation_key=recommendation_key,
        recommendation_params=recommendation_params,
    )


def emoji_ratio(text: str) -> float:
    if not text:
        return 0.0
    emojis = _EMOJI_RE.findall(text)
    emoji_chars = sum(len(e) for e in emojis)
    return emoji_chars / max(len(text), 1)


def find_urls(text: str) -> list[str]:
    return _URL_RE.findall(text or "")


def word_tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def uppercase_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def punctuation_run_score(text: str) -> int:
    """Return count of excessive punctuation runs (!!! ??? ,,,)."""
    return len(re.findall(r"[!?]{3,}|\.{4,}|,{3,}", text or ""))
