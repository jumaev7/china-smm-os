"""
Translate original transcript SRT cues into CN / RU / UZ / EN via OpenAI.

Architecture (NOT line-by-line):
  1. Read ENTIRE transcript → build global context + ASR corrections
  2. One holistic localization pass per target language (full transcript in prompt)
  3. Map results back to cues — timestamps/indices unchanged

Fallback for very long videos: output is split into ranges, but EVERY request
still includes the complete source transcript + context (no blind per-line translation).
"""
import json
import logging

from app.core.config import settings
from app.services.ai_service import get_openai, _extract_json
from app.services.subtitle_service import (
    TRANSLATED_LANG_CODES,
    save_translated_subtitle_file,
    segments_to_cues,
)

logger = logging.getLogger(__name__)

# Single API call for typical social videos; fallback ranges only if transcript is huge
_MAX_SINGLE_PASS_LINES = 180
_MAX_SINGLE_PASS_CHARS = 14_000
_OUTPUT_SEGMENT_LINES = 50  # fallback: output window size, full transcript always in prompt

TRANSLATION_TARGETS = {
    "cn": {
        "label": "CN / Simplified Chinese / 简体中文",
        "style": (
            "Simplified Chinese (简体中文, Mainland CN) only — NEVER Traditional (繁體字). "
            "Natural social/business captions, not dictionary translation."
        ),
    },
    "ru": {
        "label": "Russian",
        "style": (
            "Native Russian social media / business speech. "
            "NOT literal calques (e.g. if the video is about computers/PC shop, use IT/компьютерная тематика — "
            "never nonsense like «игровая машина с видом на море» unless the transcript truly says that)."
        ),
    },
    "uz": {
        "label": "Uzbek",
        "style": (
            "Natural Uzbek in Latin script (o'zbek lotin yozuvi) — "
            "authentic Uzbek, not Russian-style literal translation."
        ),
    },
    "en": {
        "label": "English",
        "style": "Natural marketing/business English for social media.",
    },
}

_EDITOR_SYSTEM = """\
You are a professional subtitle localization editor for short social media videos \
(Chinese businesses, products, Uzbekistan market).

PHASE 1 — Read the ENTIRE source transcript below as one continuous speech.
Understand:
- what the video is really about (topic)
- products / services / business category
- speaker intent (sell, explain, demo, announce)
- fix obvious Whisper/ASR mistakes using context (homophones, wrong words)
- do NOT invent facts, prices, or offers not supported by the speech

PHASE 2 — Return JSON analysis only (no translated lines yet):
{
  "topic": "...",
  "products": ["..."],
  "product_category": "...",
  "speaker_intent": "...",
  "business_meaning": "...",
  "coherent_summary": "2-5 sentences: what the speaker actually means across the FULL video, with ASR fixes applied",
  "domain_glossary": {"misheard phrase": "intended meaning"},
  "asr_caveats": "likely speech recognition errors in this transcript"
}"""

_LOCALIZATION_SYSTEM = """\
You are a professional subtitle localization editor.

You already have:
- CONTEXT ANALYSIS of the full video (topic, products, intent, coherent meaning)
- the COMPLETE source transcript (all subtitle cues in order)

WORKFLOW (mandatory):
1. Read the ENTIRE source transcript and context FIRST — understand the video as a whole.
2. Fix speech-recognition mistakes mentally using context before localizing.
3. Localize the requested subtitle cues into ONE coherent script in the target language.
4. Do NOT translate cues independently word-by-word. Each line must fit the global meaning.

OUTPUT RULES:
- Return JSON only: {"lines": ["...", ...]}
- Exactly the requested number of lines, same order as the cue numbers specified.
- Each string is ONLY the localized subtitle text (no numbers, timestamps, labels).
- Preserve facts from the transcript; do not invent content.
- Keep lines concise enough for on-screen subtitles."""

_LOCALIZATION_USER_TEMPLATE = """\
=== CONTEXT ANALYSIS (from full-video review) ===
Topic: {topic}
Products: {products}
Category: {product_category}
Speaker intent: {speaker_intent}
Business meaning: {business_meaning}
Coherent summary (ASR-corrected): {coherent_summary}
ASR caveats: {asr_caveats}
Domain glossary: {glossary}
=== END CONTEXT ===

=== COMPLETE SOURCE TRANSCRIPT (read entirely — do not skip) ===
{full_transcript}
=== END COMPLETE TRANSCRIPT ===

TARGET LANGUAGE: {target_label}
STYLE: {style}

{output_instruction}

Return JSON: {{"lines": [...]}} with exactly {expected_count} strings."""


def _api_key_ok() -> bool:
    key = settings.OPENAI_API_KEY or ""
    return bool(key) and not key.startswith("sk-your") and key != "your-key-here"


def _format_full_transcript(texts: list[str]) -> str:
    return "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))


def _format_glossary(context: dict) -> str:
    glossary = context.get("domain_glossary") or {}
    if not glossary:
        return "(none)"
    return "\n".join(f"  {k} → {v}" for k, v in glossary.items())


def _fits_single_pass(texts: list[str]) -> bool:
    joined = "\n".join(texts)
    return len(texts) <= _MAX_SINGLE_PASS_LINES and len(joined) <= _MAX_SINGLE_PASS_CHARS


async def _analyze_transcript_context(texts: list[str]) -> dict:
    """Phase 1: holistic read of entire transcript."""
    full_transcript = _format_full_transcript(texts)
    openai = get_openai()
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _EDITOR_SYSTEM},
            {
                "role": "user",
                "content": (
                    "Analyze this complete video transcript (all cues in order):\n\n"
                    f"{full_transcript}"
                ),
            },
        ],
        temperature=0.2,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    context = _extract_json(response.choices[0].message.content or "")
    logger.info(
        "Subtitle holistic context — topic=%s | category=%s",
        (context.get("topic") or "")[:80],
        (context.get("product_category") or "")[:80],
    )
    return context


def _build_user_prompt(
    *,
    context: dict,
    texts: list[str],
    lang_code: str,
    cue_numbers: list[int],
    output_instruction: str,
) -> str:
    cfg = TRANSLATION_TARGETS[lang_code]
    products = context.get("products") or []
    if isinstance(products, list):
        products_str = ", ".join(str(p) for p in products)
    else:
        products_str = str(products)

    return _LOCALIZATION_USER_TEMPLATE.format(
        topic=context.get("topic", ""),
        products=products_str,
        product_category=context.get("product_category", ""),
        speaker_intent=context.get("speaker_intent", ""),
        business_meaning=context.get("business_meaning", ""),
        coherent_summary=context.get("coherent_summary", context.get("translator_brief", "")),
        asr_caveats=context.get("asr_caveats", ""),
        glossary=_format_glossary(context),
        full_transcript=_format_full_transcript(texts),
        target_label=cfg["label"],
        style=cfg["style"],
        output_instruction=output_instruction,
        expected_count=len(cue_numbers),
    )


async def _call_localization(
    user_msg: str,
    expected_count: int,
    lang_code: str,
) -> list[str]:
    openai = get_openai()
    max_tokens = min(16_384, 400 + expected_count * 100)
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _LOCALIZATION_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.4,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    data = _extract_json(response.choices[0].message.content or "")
    lines = data.get("lines") or []
    if len(lines) != expected_count:
        raise ValueError(
            f"Holistic translation mismatch for {lang_code}: "
            f"expected {expected_count}, got {len(lines)}"
        )
    return [str(t).strip() for t in lines]


async def _translate_texts_holistic(
    texts: list[str],
    lang_code: str,
    context: dict,
) -> list[str]:
    """Localize all cues using full-transcript understanding (one or few calls, never blind per-line)."""
    n = len(texts)
    if n == 0:
        return []

    if _fits_single_pass(texts):
        instruction = (
            f"Localize ALL {n} subtitle cues (numbers 1–{n}) in ONE coherent pass "
            f"after reading the complete transcript above. "
            "Do not translate each cue in isolation."
        )
        user_msg = _build_user_prompt(
            context=context,
            texts=texts,
            lang_code=lang_code,
            cue_numbers=list(range(1, n + 1)),
            output_instruction=instruction,
        )
        return await _call_localization(user_msg, n, lang_code)

    # Very long transcript: multiple output windows, but full transcript + context every time
    logger.info(
        "Subtitle holistic fallback — %d lines, segment output with full transcript context",
        n,
    )
    all_out: list[str] = []
    for offset in range(0, n, _OUTPUT_SEGMENT_LINES):
        end = min(offset + _OUTPUT_SEGMENT_LINES, n)
        cue_nums = list(range(offset + 1, end + 1))
        instruction = (
            f"You have read the COMPLETE source transcript above (all {n} cues). "
            f"Now output localized text ONLY for cues {offset + 1}–{end}, "
            f"consistent with the whole video meaning — not independent literal lines. "
            f"Return exactly {end - offset} strings in order for cues {offset + 1} through {end}."
        )
        user_msg = _build_user_prompt(
            context=context,
            texts=texts,
            lang_code=lang_code,
            cue_numbers=cue_nums,
            output_instruction=instruction,
        )
        segment = await _call_localization(user_msg, end - offset, lang_code)
        all_out.extend(segment)

    return all_out


async def _translate_cues(
    cues: list[dict],
    lang_code: str,
    context: dict,
) -> list[dict]:
    texts = [c["text"] for c in cues]
    translated = await _translate_texts_holistic(texts, lang_code, context)
    return [
        {**cue, "text": translated[i]}
        for i, cue in enumerate(cues)
    ]


def _fallback_context(texts: list[str]) -> dict:
    return {
        "topic": "unknown",
        "products": [],
        "product_category": "unknown",
        "speaker_intent": "promotional or informational",
        "business_meaning": " ".join(texts)[:800],
        "coherent_summary": "\n".join(texts),
        "domain_glossary": {},
        "asr_caveats": "",
    }


async def generate_translated_subtitles(
    storage_path: str, segments: list[dict]
) -> dict[str, str]:
    saved: dict[str, str] = {}
    if not segments:
        return saved

    if not _api_key_ok():
        logger.info("subtitle translation: no API key — skipping")
        return saved

    cues = segments_to_cues(segments)
    if not cues:
        return saved

    texts = [c["text"] for c in cues]
    try:
        context = await _analyze_transcript_context(texts)
    except Exception as exc:
        logger.warning("subtitle context analysis failed (%s) — fallback context", exc)
        context = _fallback_context(texts)

    for lang_code in TRANSLATED_LANG_CODES:
        try:
            translated_cues = await _translate_cues(cues, lang_code, context)
            key = await save_translated_subtitle_file(storage_path, lang_code, translated_cues)
            if key:
                saved[lang_code] = key
                logger.info("Holistic subtitles saved: %s (%s)", key, lang_code)
        except Exception as exc:
            logger.warning(
                "subtitle translation failed for %s (%s) — continuing",
                lang_code, exc,
            )

    return saved
