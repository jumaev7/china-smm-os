"""
Video Transcription Service
Extracts audio from video bytes using ffmpeg, transcribes with OpenAI Whisper,
and optionally translates Chinese speech to English for AI caption generation.

Requirements: ffmpeg installed (added to Dockerfile).
No new Python dependencies — uses existing openai SDK.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from io import BytesIO

from app.core.config import settings

logger = logging.getLogger(__name__)

# Whisper API file size limit
_WHISPER_MAX_BYTES = 24 * 1024 * 1024  # 24 MB (leave 1 MB margin under 25 MB)


@dataclass
class TranscriptionResult:
    """Source text for AI notes plus timed segments for .srt (original language)."""
    source_text: str = ""
    language: str = ""
    segments: list[dict] = field(default_factory=list)


def _api_key_ok() -> bool:
    key = settings.OPENAI_API_KEY or ""
    return bool(key) and not key.startswith("sk-your")


async def _extract_audio(video_bytes: bytes) -> bytes:
    """
    Use ffmpeg to strip audio from video bytes.
    Runs in a subprocess via asyncio so it doesn't block the event loop.
    Returns mp3 bytes, or b"" if extraction fails.
    """
    cmd = [
        "ffmpeg",
        "-i", "pipe:0",        # read video from stdin
        "-vn",                  # drop video stream
        "-acodec", "libmp3lame",
        "-q:a", "5",            # medium quality (~80 kbps) — sufficient for speech
        "-f", "mp3",
        "pipe:1",               # write mp3 to stdout
        "-loglevel", "error",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=video_bytes),
            timeout=60.0,
        )
        if proc.returncode != 0:
            logger.warning(
                "ffmpeg audio extraction failed (rc=%d): %s",
                proc.returncode, stderr.decode(errors="replace")[:200],
            )
            return b""
        logger.info(
            "Audio extraction: %d video bytes → %d audio bytes",
            len(video_bytes), len(stdout),
        )
        return stdout
    except asyncio.TimeoutError:
        logger.warning("ffmpeg audio extraction timed out")
        return b""
    except Exception as exc:
        logger.warning("ffmpeg audio extraction error: %s", exc)
        return b""


def _parse_whisper_segments(response) -> list[dict]:
    raw = getattr(response, "segments", None) or []
    segments: list[dict] = []
    for seg in raw:
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        start = float(getattr(seg, "start", 0) or 0)
        end = float(getattr(seg, "end", start + 1) or start + 1)
        segments.append({"start": start, "end": end, "text": text})
    return segments


def _fallback_segment(text: str) -> list[dict]:
    words = len(text.split())
    duration = max(5.0, words * 0.4)
    return [{"start": 0.0, "end": duration, "text": text}]


async def _whisper_transcribe(audio_bytes: bytes) -> tuple[str, str, list[dict]]:
    """
    Call OpenAI Whisper API.
    Returns (transcript_text, detected_language_code, segments).
    Uses 'verbose_json' response format for language and timed cues.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60.0)

    audio_file = BytesIO(audio_bytes)
    audio_file.name = "audio.mp3"

    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        response_format="verbose_json",
    )

    text = (getattr(response, "text", "") or "").strip()
    lang = (getattr(response, "language", "") or "").strip().lower()
    segments = _parse_whisper_segments(response)
    if not segments and text:
        segments = _fallback_segment(text)
    return text, lang, segments


async def _translate_to_english(chinese_text: str) -> str:
    """
    Translate Chinese transcript to English for use as AI source text.
    The AI generation pipeline already handles multilingual source text,
    but an explicit translation improves caption quality.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {
                "role": "user",
                "content": (
                    "Translate this Chinese text to English. "
                    "Return ONLY the translation, no commentary:\n\n"
                    f"{chinese_text}"
                ),
            }
        ],
        max_tokens=300,
        temperature=0,
    )
    return (response.choices[0].message.content or "").strip()


async def transcribe_video_detailed(video_bytes: bytes) -> TranscriptionResult:
    """
    Transcribe video; returns source text and original-language segments for .srt.
    Never raises.
    """
    empty = TranscriptionResult()
    if not video_bytes:
        return empty

    if not _api_key_ok():
        logger.info("transcribe_video: no API key — skipping transcription")
        return empty

    logger.info("Video transcription started — %d bytes", len(video_bytes))

    audio_bytes = await _extract_audio(video_bytes)
    if not audio_bytes:
        logger.info("Video transcription: audio extraction returned empty — skipping")
        return empty

    if len(audio_bytes) > _WHISPER_MAX_BYTES:
        logger.warning(
            "Audio too large for Whisper (%d bytes > %d) — skipping",
            len(audio_bytes), _WHISPER_MAX_BYTES,
        )
        return empty

    try:
        transcript, lang, segments = await _whisper_transcribe(audio_bytes)
    except Exception as exc:
        logger.warning("Video transcription: Whisper call failed (%s) — skipping", exc)
        return empty

    if not transcript:
        logger.info("Video transcription complete — no speech detected")
        return empty

    logger.info(
        "Video transcription complete — lang=%s, %d chars, %d segments: %s…",
        lang, len(transcript), len(segments), transcript[:80],
    )

    source_text = transcript
    if lang in ("zh", "chinese", "mandarin", "cantonese"):
        try:
            english = await _translate_to_english(transcript)
            if english:
                source_text = f"{transcript} → {english}"
                logger.info("Video transcription: Chinese translated to English")
        except Exception as exc:
            logger.warning(
                "Video transcription: translation failed (%s) — using raw transcript", exc
            )

    return TranscriptionResult(
        source_text=source_text,
        language=lang,
        segments=segments,
    )


async def transcribe_video(video_bytes: bytes) -> str:
    """Source text only (backward compatible)."""
    return (await transcribe_video_detailed(video_bytes)).source_text
