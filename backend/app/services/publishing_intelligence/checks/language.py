"""Language and translation-readiness checks (deterministic readiness only)."""
from __future__ import annotations

import re

from app.services.publishing_intelligence.checks._helpers import check, primary_caption
from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext

_SUPPORTED_LOCALES = frozenset({"en", "ru", "uz", "zh"})
_PLACEHOLDERS = (
    "todo",
    "tbd",
    "xxx",
    "placeholder",
    "lorem ipsum",
    "test translation",
    "перевод здесь",
    "[translate]",
    "{{",
)

_CYRILLIC = re.compile(r"[\u0400-\u04FF]")
_LATIN = re.compile(r"[A-Za-z]")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _script_counts(text: str) -> dict[str, int]:
    return {
        "cyrillic": len(_CYRILLIC.findall(text)),
        "latin": len(_LATIN.findall(text)),
        "cjk": len(_CJK.findall(text)),
    }


def run_language_checks(ctx: ReviewContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    text = primary_caption(ctx)
    captions = ctx.captions

    if not text.strip() and not captions:
        for key in (
            "language_present",
            "language_matches_selected_locale",
            "mixed_script_ratio",
            "empty_translation",
            "translation_language_mismatch",
            "translation_completeness",
            "unsupported_language",
            "excessive_untranslated_segments",
        ):
            cat = "translation_readiness" if "translation" in key or key == "excessive_untranslated_segments" else "language_quality"
            if key in ("empty_translation", "translation_language_mismatch", "translation_completeness", "excessive_untranslated_segments"):
                cat = "translation_readiness"
            results.append(check(key, cat, "not_applicable", evidence={"reason": "no_caption"}))
        return results

    results.append(
        check(
            "language_present",
            "language_quality",
            "passed" if ctx.primary_language else "warning",
            score=100 if ctx.primary_language else 50,
            weight=2,
            evidence={"primary_language": ctx.primary_language, "available": sorted(captions.keys())},
            recommendation_key="set_primary_language" if not ctx.primary_language else None,
        )
    )

    if ctx.primary_language and ctx.primary_language not in _SUPPORTED_LOCALES:
        results.append(
            check(
                "unsupported_language",
                "language_quality",
                "warning",
                score=40,
                weight=2,
                severity="warning",
                evidence={"language": ctx.primary_language, "supported": sorted(_SUPPORTED_LOCALES)},
                recommendation_key="use_supported_language",
            )
        )
    else:
        results.append(
            check(
                "unsupported_language",
                "language_quality",
                "passed",
                score=100,
                weight=1,
                evidence={"language": ctx.primary_language},
            )
        )

    # Script match heuristic for primary language
    counts = _script_counts(text)
    total_scripts = sum(counts.values()) or 1
    match_ok = True
    if ctx.primary_language == "ru" and counts["cyrillic"] / total_scripts < 0.3:
        match_ok = False
    if ctx.primary_language == "zh" and counts["cjk"] / total_scripts < 0.2:
        match_ok = False
    if ctx.primary_language in {"en", "uz"} and counts["latin"] / total_scripts < 0.3:
        match_ok = False
    results.append(
        check(
            "language_matches_selected_locale",
            "language_quality",
            "passed" if match_ok else "warning",
            score=100 if match_ok else 55,
            weight=2,
            evidence={"script_counts": counts, "primary_language": ctx.primary_language},
            recommendation_key="align_caption_language" if not match_ok else None,
        )
    )

    nonzero = [v for v in counts.values() if v > 0]
    mixed = len(nonzero) >= 2 and min(nonzero) / total_scripts > 0.25
    results.append(
        check(
            "mixed_script_ratio",
            "language_quality",
            "warning" if mixed else "passed",
            score=60 if mixed else 100,
            weight=1,
            evidence={"script_counts": counts, "mixed": mixed},
            recommendation_key="review_mixed_scripts" if mixed else None,
        )
    )

    # Translation readiness across caption languages
    langs = sorted(captions.keys())
    empty_langs = [lang for lang, val in captions.items() if not (val or "").strip()]
    # Also consider expected project languages when multiple platforms / multi-caption present
    filled = {lang: (captions.get(lang) or "").strip() for lang in langs if (captions.get(lang) or "").strip()}

    if len(filled) <= 1:
        for key in (
            "empty_translation",
            "translation_language_mismatch",
            "translation_completeness",
            "excessive_untranslated_segments",
        ):
            results.append(
                check(
                    key,
                    "translation_readiness",
                    "not_applicable",
                    evidence={"reason": "single_or_no_translation_set", "note": "Readiness only — not semantic quality"},
                )
            )
        return results

    results.append(
        check(
            "empty_translation",
            "translation_readiness",
            "failed" if empty_langs else "passed",
            score=0 if empty_langs else 100,
            weight=2,
            severity="error" if empty_langs else "info",
            evidence={"empty_languages": empty_langs},
            recommendation_key="complete_missing_translation" if empty_langs else None,
            recommendation_params={"languages": empty_langs} if empty_langs else None,
        )
    )

    # Unchanged source copied into another language
    values = list(filled.values())
    unchanged_pairs = []
    langs_filled = list(filled.keys())
    for i, a in enumerate(langs_filled):
        for b in langs_filled[i + 1 :]:
            if filled[a] == filled[b] and len(filled[a]) >= 20:
                unchanged_pairs.append(f"{a}={b}")
    results.append(
        check(
            "translation_language_mismatch",
            "translation_readiness",
            "warning" if unchanged_pairs else "passed",
            score=40 if unchanged_pairs else 100,
            weight=2,
            evidence={"identical_pairs": unchanged_pairs, "note": "Source copied into target is readiness issue"},
            recommendation_key="translate_copied_source" if unchanged_pairs else None,
        )
    )

    # Completeness: relative length across translations
    lengths = {k: len(v) for k, v in filled.items()}
    max_len = max(lengths.values()) if lengths else 1
    incomplete = [k for k, ln in lengths.items() if ln < max_len * 0.35 and max_len >= 40]
    results.append(
        check(
            "translation_completeness",
            "translation_readiness",
            "warning" if incomplete else "passed",
            score=55 if incomplete else 100,
            weight=2,
            evidence={"lengths": lengths, "incomplete": incomplete},
            recommendation_key="complete_missing_translation" if incomplete else None,
        )
    )

    placeholder_hits = []
    for lang, val in filled.items():
        low = val.lower()
        if any(p in low for p in _PLACEHOLDERS):
            placeholder_hits.append(lang)
    results.append(
        check(
            "excessive_untranslated_segments",
            "translation_readiness",
            "failed" if placeholder_hits else "passed",
            score=20 if placeholder_hits else 100,
            weight=2,
            severity="error" if placeholder_hits else "info",
            evidence={"placeholder_languages": placeholder_hits},
            recommendation_key="remove_translation_placeholders" if placeholder_hits else None,
        )
    )
    return results
