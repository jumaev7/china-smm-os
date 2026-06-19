"""
Burn subtitles into video with ffmpeg.
Preserves original media; writes sibling .{lang}.subtitled.mp4 / .final.mp4 files.
"""
import asyncio
import logging
import tempfile
from pathlib import Path

from app.core.storage import storage
from app.services.subtitle_service import (
    TRANSLATED_LANG_CODES,
    VOICE_LANG_CODES,
    burned_video_path_for,
    dubbed_video_extended_path_for,
    dubbed_video_fitted_path_for,
    dubbed_video_legacy_path_for,
    final_video_legacy_path_for,
    final_video_path_for,
    translated_subtitle_path_for,
)

logger = logging.getLogger(__name__)

_BURN_TIMEOUT_SEC = 600.0
_VALID_LANGS = set(TRANSLATED_LANG_CODES)


class VideoProcessingError(Exception):
    """ffmpeg burn-in failed."""


async def _run_ffmpeg(cmd: list[str], label: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        _stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_BURN_TIMEOUT_SEC
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise VideoProcessingError(f"{label}: ffmpeg timed out") from exc
    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[:800]
        raise VideoProcessingError(f"{label}: {err}")


async def _burn_subtitles_onto_file(
    video_storage_path: str,
    srt_storage_path: str,
    output_key: str,
) -> str:
    """Burn SRT onto a video file; save to output_key (does not touch source)."""
    if not storage.exists(srt_storage_path):
        raise VideoProcessingError(f"Subtitle file not found: {srt_storage_path}")

    video_bytes = await storage.read_file_bytes(video_storage_path)
    srt_bytes = await storage.read_file_bytes(srt_storage_path)

    suffix = Path(video_storage_path).suffix.lower() or ".mp4"
    if suffix not in (".mp4", ".mov", ".webm", ".mkv"):
        suffix = ".mp4"

    with tempfile.TemporaryDirectory(prefix="burn_subs_") as tmp:
        tmp_path = Path(tmp)
        input_video = tmp_path / f"input{suffix}"
        subs_file = tmp_path / "subs.srt"
        output_file = tmp_path / "output.mp4"

        input_video.write_bytes(video_bytes)
        subs_file.write_bytes(srt_bytes)

        vf = f"subtitles={subs_file}:charenc=UTF-8"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_video),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_file),
        ]
        await _run_ffmpeg(cmd, "burn subtitles")

        if not output_file.is_file() or output_file.stat().st_size == 0:
            raise VideoProcessingError("ffmpeg produced empty output file")

        out_bytes = output_file.read_bytes()

    if storage.exists(output_key):
        logger.info("Replacing existing burned output %s", output_key)
        await storage.delete_file(output_key)
    await storage.save_at_key(output_key, out_bytes)
    logger.info("Burn subtitles done — %s (%d bytes)", output_key, len(out_bytes))
    return output_key


async def burn_subtitles_into_video(
    video_storage_path: str,
    lang: str,
) -> str:
    """
    Burn translated SRT (lang) into original video.
    Saves as burned_video_path_for(...); original is preserved.
    """
    if lang not in _VALID_LANGS:
        raise VideoProcessingError(f"Unsupported subtitle language: {lang}")

    srt_key = translated_subtitle_path_for(video_storage_path, lang)
    output_key = burned_video_path_for(video_storage_path, lang)

    logger.info(
        "ffmpeg burn subtitles start — video=%s lang=%s → %s",
        video_storage_path, lang, output_key,
    )
    return await _burn_subtitles_onto_file(video_storage_path, srt_key, output_key)


async def generate_final_video(
    video_storage_path: str,
    subtitle_lang: str,
    voice_lang: str = "ru",
    voice_mode: str = "fitted",
) -> str:
    """
    Combined export: burned subtitles + dubbed voice (RU/UZ/EN) or original audio (CN).
    Subtitle, voice, and dub mode are selected independently.
    """
    subtitle_lang = subtitle_lang.strip().lower()
    voice_lang = voice_lang.strip().lower()
    voice_mode = (voice_mode or "fitted").strip().lower()

    logger.info("[Final Export] subtitle: %s", subtitle_lang)
    logger.info(
        "[Final Export] voice: %s",
        "original" if subtitle_lang == "cn" else voice_lang,
    )
    logger.info(
        "[Final Export] mode: %s",
        "n/a" if subtitle_lang == "cn" else voice_mode,
    )

    if subtitle_lang not in _VALID_LANGS:
        raise VideoProcessingError(f"Unsupported subtitle language: {subtitle_lang}")
    if subtitle_lang != "cn":
        if voice_lang not in VOICE_LANG_CODES:
            raise VideoProcessingError(f"Unsupported voice language: {voice_lang}")
        if voice_mode not in ("fitted", "extended"):
            raise VideoProcessingError(f"Unsupported voice mode: {voice_mode}")

    srt_key = translated_subtitle_path_for(video_storage_path, subtitle_lang)
    if not storage.exists(srt_key):
        raise VideoProcessingError(
            f"Subtitle file not found for language: {subtitle_lang}. Generate subtitles first."
        )

    output_key = final_video_path_for(
        video_storage_path, subtitle_lang, voice_lang, voice_mode
    )

    if subtitle_lang == "cn":
        video_source = video_storage_path
    else:
        if voice_mode == "extended":
            dubbed_key = dubbed_video_extended_path_for(video_storage_path, voice_lang)
        else:
            dubbed_key = dubbed_video_fitted_path_for(video_storage_path, voice_lang)
            if not storage.exists(dubbed_key):
                legacy_key = dubbed_video_legacy_path_for(video_storage_path, voice_lang)
                if storage.exists(legacy_key):
                    dubbed_key = legacy_key

        if not storage.exists(dubbed_key):
            logger.info(
                "Final video: generating missing %s dub for voice=%s",
                voice_mode,
                voice_lang,
            )
            from app.services.voice_service import generate_dubbed_video
            await generate_dubbed_video(
                video_storage_path, voice_lang, mode=voice_mode
            )
            dubbed_key = (
                dubbed_video_extended_path_for(video_storage_path, voice_lang)
                if voice_mode == "extended"
                else dubbed_video_fitted_path_for(video_storage_path, voice_lang)
            )
        video_source = dubbed_key

    logger.info(
        "Final video start — source=%s subtitle=%s voice=%s mode=%s → %s",
        video_source,
        subtitle_lang,
        voice_lang,
        voice_mode,
        output_key,
    )
    return await _burn_subtitles_onto_file(video_source, srt_key, output_key)
