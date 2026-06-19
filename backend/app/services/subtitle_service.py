"""
Subtitle (.srt) generation from Whisper transcript segments.
Saved alongside the video storage path (same stem, .srt extension).
Translated variants: {stem}.cn.srt, .ru.srt, .uz.srt, .en.srt
"""
import logging
import re
from pathlib import Path

from app.core.storage import storage

logger = logging.getLogger(__name__)

TRANSLATED_LANG_CODES = ("cn", "ru", "uz", "en")
VOICE_LANG_CODES = ("ru", "uz", "en")

_SRT_TIME = re.compile(
    r"^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})$"
)


def subtitle_path_for(storage_path: str) -> str:
    """Sibling .srt path next to the media file (original transcript language)."""
    return str(Path(storage_path).with_suffix(".srt"))


def translated_subtitle_path_for(storage_path: str, lang: str) -> str:
    """Translated SRT path, e.g. clients/…/abc.cn.srt"""
    p = Path(storage_path)
    return str(p.parent / f"{p.stem}.{lang}.srt")


def burned_video_path_for(storage_path: str, lang: str) -> str:
    """Hard-subtitled MP4 next to original, e.g. clients/…/abc.ru.subtitled.mp4"""
    p = Path(storage_path)
    return str(p.parent / f"{p.stem}.{lang}.subtitled.mp4")


def dubbed_video_path_for(storage_path: str, lang: str) -> str:
    """Fitted voice-dubbed MP4 (fits original video duration)."""
    return dubbed_video_fitted_path_for(storage_path, lang)


def dubbed_video_fitted_path_for(storage_path: str, lang: str) -> str:
    """Fitted dub: never exceeds original video duration."""
    p = Path(storage_path)
    return str(p.parent / f"{p.stem}.{lang}.dubbed.fitted.mp4")


def dubbed_video_extended_path_for(storage_path: str, lang: str) -> str:
    """Extended dub: may exceed original video duration."""
    p = Path(storage_path)
    return str(p.parent / f"{p.stem}.{lang}.dubbed.extended.mp4")


def dubbed_video_legacy_path_for(storage_path: str, lang: str) -> str:
    """Legacy path from earlier builds."""
    p = Path(storage_path)
    return str(p.parent / f"{p.stem}.{lang}.dubbed.mp4")


def final_video_path_for(
    storage_path: str,
    subtitle_lang: str,
    voice_lang: str | None = None,
    voice_mode: str = "fitted",
) -> str:
    """Combined dubbed + burned-subtitle MP4."""
    p = Path(storage_path)
    if subtitle_lang == "cn":
        return str(p.parent / f"{p.stem}.cn.final.mp4")
    voice = voice_lang or subtitle_lang
    mode = voice_mode if voice_mode in ("fitted", "extended") else "fitted"
    return str(p.parent / f"{p.stem}.final.{subtitle_lang}.{voice}.{mode}.mp4")


def final_video_legacy_path_for(storage_path: str, lang: str) -> str:
    """Legacy combined export path from earlier builds."""
    p = Path(storage_path)
    return str(p.parent / f"{p.stem}.{lang}.final.mp4")


def _format_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_cues(segments: list[dict]) -> list[dict]:
    """Convert Whisper segments to SRT cues with fixed time_line strings."""
    cues: list[dict] = []
    index = 1
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0))
        end = float(seg.get("end", start + 1))
        if end <= start:
            end = start + 1.0
        time_line = f"{_format_srt_time(start)} --> {_format_srt_time(end)}"
        cues.append({"index": index, "time_line": time_line, "text": text})
        index += 1
    return cues


def build_srt_from_cues(cues: list[dict]) -> str:
    """Rebuild SRT preserving cue index and time_line exactly."""
    blocks = [
        f"{cue['index']}\n{cue['time_line']}\n{cue['text']}\n"
        for cue in cues
    ]
    return "\n".join(blocks) + ("\n" if blocks else "")


def build_srt(segments: list[dict]) -> str:
    """Build SubRip content from Whisper segments (original spoken language)."""
    return build_srt_from_cues(segments_to_cues(segments))


def parse_srt(content: str) -> list[dict]:
    """Parse SRT file into cues (index, time_line, text)."""
    cues: list[dict] = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0])
        except ValueError:
            continue
        time_line = lines[1]
        if not _SRT_TIME.match(time_line):
            continue
        text = "\n".join(lines[2:])
        cues.append({"index": index, "time_line": time_line, "text": text})
    return cues


async def save_subtitle_file(storage_path: str, segments: list[dict]) -> str | None:
    """Write .srt next to media file. Returns subtitle key or None."""
    srt_body = build_srt(segments)
    if not srt_body.strip():
        return None
    key = subtitle_path_for(storage_path)
    await storage.save_at_key(key, srt_body.encode("utf-8"))
    logger.info("Subtitles saved: %s (%d cues)", key, len(segments_to_cues(segments)))
    return key


async def save_translated_subtitle_file(
    storage_path: str, lang: str, cues: list[dict]
) -> str | None:
    """Write translated .{lang}.srt; preserves timestamps and numbering."""
    body = build_srt_from_cues(cues)
    if not body.strip():
        return None
    key = translated_subtitle_path_for(storage_path, lang)
    await storage.save_at_key(key, body.encode("utf-8"))
    logger.info("Translated subtitles saved: %s (%s)", key, lang)
    return key


def all_subtitle_paths(storage_path: str) -> list[str]:
    """Original + translated paths for cleanup."""
    paths = [subtitle_path_for(storage_path)]
    paths.extend(translated_subtitle_path_for(storage_path, lang) for lang in TRANSLATED_LANG_CODES)
    return paths


def all_burned_video_paths(storage_path: str) -> list[str]:
    """Generated subtitled MP4 variants for cleanup."""
    return [burned_video_path_for(storage_path, lang) for lang in TRANSLATED_LANG_CODES]


def all_dubbed_video_paths(storage_path: str) -> list[str]:
    paths = []
    for lang in VOICE_LANG_CODES:
        paths.append(dubbed_video_fitted_path_for(storage_path, lang))
        paths.append(dubbed_video_extended_path_for(storage_path, lang))
        paths.append(dubbed_video_legacy_path_for(storage_path, lang))
    return paths


def all_final_video_paths(storage_path: str) -> list[str]:
    paths = [final_video_path_for(storage_path, "cn")]
    for sub in TRANSLATED_LANG_CODES:
        if sub == "cn":
            continue
        paths.append(final_video_legacy_path_for(storage_path, sub))
        for voice in VOICE_LANG_CODES:
            for mode in ("fitted", "extended"):
                paths.append(final_video_path_for(storage_path, sub, voice, mode))
    return paths
