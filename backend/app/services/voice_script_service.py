"""
Compact translated subtitle lines into speakable voiceover scripts.
Does NOT modify SRT files — voice-only preprocessing before TTS.
"""
import logging
import re

from app.core.config import settings
from app.services.ai_service import get_openai

logger = logging.getLogger(__name__)

_CYRILLIC = re.compile(r"[\u0400-\u04FF]")

# Spoken pace limits (characters per second)
_CHARS_PER_SEC_STRICT = {
    "ru": 10.0,
    "uz": 10.0,
    "en": 12.0,
}
_CHARS_PER_SEC_RELAXED = {
    "ru": 11.0,
    "uz": 12.0,
    "en": 13.0,
}

_LANG_LABEL = {
    "ru": "Russian",
    "uz": "Uzbek (Latin script)",
    "en": "English",
}

_UZ_VOICE_RULES = (
    "Uzbek voiceover rules: Latin script ONLY (lotin yozuv). No Cyrillic. "
    "Natural spoken Uzbek — avoid Russian-style sentence structure. "
    "Use simple everyday words; avoid rare or overly formal terms. "
    "Prefer short sentences. Add commas and periods for clear TTS rhythm. "
    "Keep product facts. Simple tech terms: kompyuter, noutbuk, xizmat, kafolat, buyurtma."
)


def _ensure_latin_uzbek(text: str) -> str:
    if not _CYRILLIC.search(text):
        return text.strip()
    logger.warning("Voice script UZ: stripping Cyrillic characters from TTS text")
    cleaned = _CYRILLIC.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _uz_fallback_normalize(text: str) -> str:
    text = _ensure_latin_uzbek(text.strip())
    if not text:
        return text
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    if text and text[-1] not in ".!?":
        text = f"{text}."
    return text


async def prepare_uzbek_tts_text(
    text: str,
    *,
    target_duration_sec: float | None = None,
) -> str:
    """
    Rewrite Uzbek subtitle/voice text for natural AI TTS (Latin, simple phrasing).
    Voice-only — does not modify SRT files.
    """
    text = text.strip()
    if not text:
        return text

    logger.info("[Voiceover UZ] original text: %s", text[:240])

    key = settings.OPENAI_API_KEY or ""
    if not key or key.startswith("sk-your"):
        ready = _uz_fallback_normalize(text)
        logger.info("[Voiceover UZ] TTS-ready text: %s", ready[:240])
        return ready

    duration_note = ""
    if target_duration_sec is not None:
        max_chars = estimate_max_chars(target_duration_sec, "uz", strict=False)
        duration_note = (
            f" Target speaking time: {target_duration_sec:.1f}s (~{max_chars} characters). "
            "Keep phrasing concise. "
        )

    client = get_openai()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You rewrite Uzbek lines for AI text-to-speech voiceover on short social videos. "
                    f"{_UZ_VOICE_RULES} "
                    f"{duration_note}"
                    "Return ONLY the spoken line — no quotes, labels, or explanations."
                ),
            },
            {
                "role": "user",
                "content": f"Make this natural for Uzbek TTS:\n{text}",
            },
        ],
        temperature=0.35,
        max_tokens=220,
    )
    ready = (response.choices[0].message.content or "").strip()
    if not ready:
        ready = _uz_fallback_normalize(text)
    else:
        ready = _uz_fallback_normalize(ready)

    logger.info("[Voiceover UZ] TTS-ready text: %s", ready[:240])
    return ready

def estimate_max_chars(
    target_duration_sec: float,
    lang: str,
    *,
    strict: bool = False,
) -> int:
    """Max characters for natural speech in the time slot."""
    rates = _CHARS_PER_SEC_STRICT if strict else _CHARS_PER_SEC_RELAXED
    rate = rates.get(lang, 10.0)
    margin = 0.85 if strict else 0.92
    return max(5, int(target_duration_sec * rate * margin))


def estimate_speech_duration(text: str, lang: str, *, strict: bool = False) -> float:
    """Rough TTS duration estimate from character count."""
    rates = _CHARS_PER_SEC_STRICT if strict else _CHARS_PER_SEC_RELAXED
    rate = rates.get(lang, 10.0)
    n = len(text.strip())
    if n == 0:
        return 0.0
    return n / rate


def needs_shortening(
    text: str,
    target_duration_sec: float,
    lang: str,
    *,
    strict: bool = False,
) -> bool:
    return len(text.strip()) > estimate_max_chars(target_duration_sec, lang, strict=strict)


def _merge_short_cues(cues: list[dict], lang: str) -> tuple[list[dict], list[bool]]:
    """
    Merge consecutive cues when individual slots are too tight for speech.
    Returns (merged cues, merged_flags per output cue).
    """
    if not cues:
        return [], []

    merged: list[dict] = []
    merged_flags: list[bool] = []

    i = 0
    while i < len(cues):
        cue = cues[i]
        slot = max(0.2, float(cue["end"]) - float(cue["start"]))
        text = (cue.get("text") or "").strip()

        should_merge = (
            i + 1 < len(cues)
            and (
                slot < 1.0
                or len(text) > estimate_max_chars(slot, lang, strict=True) * 1.5
            )
        )
        if should_merge:
            nxt = cues[i + 1]
            combined = {
                **cue,
                "start": cue["start"],
                "end": nxt["end"],
                "text": f"{text} {nxt.get('text', '').strip()}".strip(),
            }
            merged.append(combined)
            merged_flags.append(True)
            i += 2
        else:
            merged.append(cue)
            merged_flags.append(False)
            i += 1

    return merged, merged_flags


async def compact_for_voiceover(
    text: str,
    target_duration_sec: float,
    lang: str,
    *,
    strict: bool = False,
    force: bool = False,
) -> str:
    """
    Shorten text for spoken delivery when literal subtitle line is too long.
    Preserves meaning and product facts; returns original if already short enough.
    """
    text = text.strip()
    if not text:
        return text

    max_chars = estimate_max_chars(target_duration_sec, lang, strict=strict)
    if not force and len(text) <= max_chars:
        return text

    key = settings.OPENAI_API_KEY or ""
    if not key or key.startswith("sk-your"):
        logger.warning("Voice script: no API key — using original text (may run long)")
        return text

    label = _LANG_LABEL.get(lang, lang)
    approx_words = max(2, int(target_duration_sec * (1.8 if strict else 2.2)))

    strict_note = (
        "This MUST fit in the time slot when spoken aloud. Use very short phrasing. "
        if strict
        else ""
    )
    uz_note = f"{_UZ_VOICE_RULES} " if lang == "uz" else ""

    client = get_openai()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    f"You write compact spoken {label} for short social-media video voiceover. "
                    f"{strict_note}"
                    f"{uz_note}"
                    "This is VOICEOVER script — NOT on-screen subtitles. "
                    "Preserve core meaning and product facts. Remove filler. "
                    "Do NOT translate word-for-word. Sound natural when spoken. "
                    "Return ONLY the spoken line, no quotes or labels."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Available speaking time: {target_duration_sec:.1f}s "
                    f"(max ~{max_chars} characters, ~{approx_words} words).\n\n"
                    f"Rewrite shorter for voiceover:\n{text}"
                ),
            },
        ],
        temperature=0.3,
        max_tokens=180,
    )
    shortened = (response.choices[0].message.content or "").strip()
    if not shortened:
        return text
    if lang == "uz":
        shortened = _uz_fallback_normalize(shortened)
    return shortened


async def build_voice_scripts(
    cues: list[dict],
    lang: str,
    *,
    mode: str = "extended",
) -> tuple[list[str], list[dict], list[bool]]:
    """
    Build voiceover scripts (separate from subtitle text).
    Returns (scripts, units, merged_flags).
    """
    if mode == "fitted":
        units, merged_flags = _merge_short_cues(cues, lang)
        strict = True
        force_compact = True
    else:
        units, merged_flags = cues, [False] * len(cues)
        strict = False
        force_compact = False

    scripts: list[str] = []
    for i, cue in enumerate(units):
        target = max(0.2, float(cue["end"]) - float(cue["start"]))
        original = (cue.get("text") or "").strip()

        if force_compact or needs_shortening(original, target, lang, strict=strict):
            voice_text = await compact_for_voiceover(
                original, target, lang, strict=strict, force=force_compact
            )
        else:
            voice_text = original

        est = estimate_speech_duration(voice_text, lang, strict=strict)
        logger.info(
            "Voice script %d [%s/%s]: segment=%.2fs orig=%r voice=%r "
            "orig_len=%d voice_len=%d est_speech=%.2fs merged=%s",
            i,
            lang,
            mode,
            target,
            original[:80],
            voice_text[:80],
            len(original),
            len(voice_text),
            est,
            merged_flags[i] if i < len(merged_flags) else False,
        )
        scripts.append(voice_text)

    return scripts, units, merged_flags
