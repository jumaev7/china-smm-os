"""
AI voice dubbing: TTS from translated SRT + ffmpeg audio replace on original video.
Preserves original file; writes sibling .{lang}.dubbed.mp4 (RU / UZ / EN).
"""
import asyncio
import logging
import re
import tempfile
from pathlib import Path

from app.core.config import settings
from app.core.storage import storage
from app.services.ai_service import get_openai
from app.services.voice_script_service import (
    build_voice_scripts,
    compact_for_voiceover,
    estimate_speech_duration,
    prepare_uzbek_tts_text,
)
from app.services.subtitle_service import (
    VOICE_LANG_CODES,
    dubbed_video_extended_path_for,
    dubbed_video_fitted_path_for,
    parse_srt,
    translated_subtitle_path_for,
)

logger = logging.getLogger(__name__)

_SRT_TIME = re.compile(
    r"^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})$"
)

_MAX_TTS_CUES = 45
_TTS_MAX_CHARS = 4000
_DUB_TIMEOUT_SEC = 900.0
_VALID_LANGS = set(VOICE_LANG_CODES)
_GAP_BEFORE_SEC = 0.10  # shorter silence between segments
_TAIL_PADDING_SEC = 0.20  # 200 ms minimum tail after each spoken segment
_ATEMPO_MIN = 1.05  # only speed up when noticeably over slot
_ATEMPO_NORMAL_MAX = 1.15
_ATEMPO_MAX = 1.25
_MIN_SEGMENT_SEC = 0.2
_AUDIO_RATE = 44100

# OpenAI TTS voices (multilingual-capable)
_TTS_VOICE = {
    "ru": "onyx",
    "uz": "nova",
    "en": "alloy",
}

class VoiceProcessingError(Exception):
    """Voice dubbing failed."""

    FITTED_TOO_LONG = (
        "Voiceover is longer than video. Use extended version?"
    )


def _api_key_ok() -> bool:
    key = settings.OPENAI_API_KEY or ""
    return bool(key) and not key.startswith("sk-your") and key != "your-key-here"


def _timestamp_to_seconds(ts: str) -> float:
    hh, mm, rest = ts.split(":")
    ss, ms = rest.split(",")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0


def _cues_with_timing(cues: list[dict]) -> list[dict]:
    timed: list[dict] = []
    for cue in cues:
        m = _SRT_TIME.match(cue["time_line"])
        if not m:
            continue
        text = (cue.get("text") or "").strip()
        if not text:
            continue
        start = _timestamp_to_seconds(m.group(1))
        end = _timestamp_to_seconds(m.group(2))
        if end <= start:
            end = start + 1.0
        timed.append({**cue, "start": start, "end": end, "text": text})
    return timed


async def _tts_mp3(
    text: str,
    lang: str,
    *,
    target_duration_sec: float | None = None,
) -> bytes:
    text = text.strip()[:_TTS_MAX_CHARS]
    if not text:
        return b""
    if lang == "uz":
        text = await prepare_uzbek_tts_text(text, target_duration_sec=target_duration_sec)
        text = text.strip()[:_TTS_MAX_CHARS]
        if not text:
            return b""
    client = get_openai()
    speech = await client.audio.speech.create(
        model="tts-1",
        voice=_TTS_VOICE[lang],
        input=text,
        response_format="mp3",
    )
    if hasattr(speech, "read"):
        return speech.read()
    return speech.content  # type: ignore[attr-defined]


async def _probe_duration(media_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return 60.0
    try:
        return max(0.01, float(stdout.decode().strip()))
    except ValueError:
        return 60.0


async def _make_silence(duration_sec: float, out_path: Path) -> None:
    duration_sec = max(0.01, duration_sec)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r={_AUDIO_RATE}:cl=mono",
        "-t", f"{duration_sec:.3f}",
        "-c:a", "libmp3lame",
        "-q:a", "9",
        str(out_path),
    ]
    await _run_ffmpeg(cmd, "silence")


async def _process_segment_audio(
    src_path: Path,
    out_path: Path,
    target_slot: float,
) -> tuple[float, float, float]:
    """
    Preserve full TTS speech. Speed up gently with atempo when over slot — never trim words.
    Returns (final_duration, original_duration, speed_factor).
    """
    raw_dur = await _probe_duration(src_path)
    if raw_dur <= 0.01:
        raise VoiceProcessingError("TTS segment has zero duration")

    target_slot = max(_MIN_SEGMENT_SEC, target_slot)
    speed = 1.0

    if raw_dur > target_slot * 1.02:
        desired = raw_dur / target_slot
        if desired <= _ATEMPO_NORMAL_MAX:
            speed = max(_ATEMPO_MIN, desired)
        elif desired <= _ATEMPO_MAX:
            speed = desired
        else:
            speed = _ATEMPO_MAX  # keep all speech; schedule will delay next segment

    filters: list[str] = [f"aresample={_AUDIO_RATE}"]
    if speed > 1.001:
        filters.append(f"atempo={speed:.4f}")
    filters.extend([
        "asetpts=PTS-STARTPTS",
        "loudnorm=I=-16:TP=-1.5:LRA=11",
    ])

    cmd = [
        "ffmpeg", "-y",
        "-i", str(src_path),
        "-af", ",".join(filters),
        "-c:a", "libmp3lame",
        "-q:a", "4",
        str(out_path),
    ]
    await _run_ffmpeg(cmd, "process segment")
    final_dur = await _probe_duration(out_path)
    return final_dur, raw_dur, speed


async def _prepare_scheduled_segments(
    cues: list[dict],
    lang: str,
    tmp_path: Path,
    video_duration: float,
    *,
    mode: str = "extended",
) -> tuple[list[tuple[float, Path, float]], float]:
    """
    Voice scripts → TTS → schedule without overlap.
    Fitted mode: strict cap at video_duration.
    """
    voice_scripts, units, merged_flags = await build_voice_scripts(cues, lang, mode=mode)
    placed: list[tuple[float, Path, float]] = []
    timeline_end = 0.0
    fitted = mode == "fitted"
    gap = 0.08 if fitted else _GAP_BEFORE_SEC
    tail = 0.15 if fitted else _TAIL_PADDING_SEC

    for i, (cue, voice_text) in enumerate(zip(units, voice_scripts)):
        sub_start = cue["start"]
        sub_end = cue["end"]
        original_text = (cue.get("text") or "").strip()
        merged = merged_flags[i] if i < len(merged_flags) else False

        place_at = sub_start
        delayed = False
        if timeline_end > 0:
            min_start = timeline_end + gap
            if place_at < min_start - 0.001:
                place_at = min_start
                delayed = True

        if fitted and place_at >= video_duration - 0.05:
            logger.warning("Voice fitted: skipping segment %d — no room in video", i)
            break

        remaining = video_duration - place_at - tail if fitted else sub_end - place_at
        target_slot = max(_MIN_SEGMENT_SEC, min(sub_end - sub_start, remaining))

        if not voice_text.strip():
            continue

        voice_text_work = voice_text
        final_dur = 0.0
        tts_dur = 0.0
        speed = 1.0
        shortened_again = False
        fitted_path: Path | None = None

        for attempt in range(4):
            mp3_bytes = await _tts_mp3(
                voice_text_work, lang, target_duration_sec=target_slot
            )
            if not mp3_bytes:
                break

            raw_path = tmp_path / f"seg_raw_{i}_{attempt}.mp3"
            raw_path.write_bytes(mp3_bytes)
            seg_fit = tmp_path / f"seg_fit_{i}_{attempt}.mp3"
            final_dur, tts_dur, speed = await _process_segment_audio(
                raw_path, seg_fit, target_slot
            )
            fitted_path = seg_fit

            fits_slot = final_dur <= target_slot * 1.05
            fits_video = place_at + final_dur + tail <= video_duration + 0.02

            if not fitted or (fits_slot and fits_video):
                voice_text = voice_text_work
                break

            shortened_again = True
            tighter = target_slot * (0.85 ** (attempt + 1))
            voice_text_work = await compact_for_voiceover(
                voice_text_work,
                max(_MIN_SEGMENT_SEC, tighter),
                lang,
                strict=True,
                force=True,
            )

        if not fitted_path or final_dur <= 0.01:
            continue

        if fitted and place_at + final_dur + tail > video_duration + 0.02:
            raise VoiceProcessingError(VoiceProcessingError.FITTED_TOO_LONG)

        seg_end = place_at + final_dur
        timeline_end = seg_end + tail
        placed.append((place_at, fitted_path, final_dur))

        est = estimate_speech_duration(voice_text, lang, strict=fitted)
        logger.info(
            "Voice segment %d [%s/%s]: segment_dur=%.2fs orig=%r script=%r "
            "est=%.2fs tts=%.2fs speed=%.3f final=%.2fs placed=%.2f-%.2f "
            "delayed=%s merged=%s shortened_again=%s",
            i,
            lang,
            mode,
            sub_end - sub_start,
            original_text[:60],
            voice_text[:60],
            est,
            tts_dur,
            speed,
            final_dur,
            place_at,
            seg_end,
            delayed,
            merged,
            shortened_again,
        )

    voice_timeline = timeline_end if placed else 0.0
    if fitted and voice_timeline > video_duration + 0.05:
        raise VoiceProcessingError(VoiceProcessingError.FITTED_TOO_LONG)

    return placed, voice_timeline


async def _concat_voice_timeline(
    placed: list[tuple[float, Path, float]],
    video_duration: float,
    voice_out: Path,
    tmp_path: Path,
    *,
    cap_to_video: bool = False,
) -> float:
    """Build non-overlapping voice track; optionally cap at video duration."""
    if not placed:
        raise VoiceProcessingError("No voice segments to mix")

    parts: list[Path] = []
    timeline = 0.0
    part_idx = 0

    for place_at, seg_path, dur in placed:
        gap = place_at - timeline
        if gap >= 0.03:
            silence_path = tmp_path / f"gap_{part_idx}.mp3"
            await _make_silence(gap, silence_path)
            parts.append(silence_path)
            part_idx += 1
        parts.append(seg_path)
        timeline = place_at + dur

    audio_duration = timeline
    if cap_to_video:
        audio_duration = min(timeline, video_duration)
    elif audio_duration < video_duration:
        tail = video_duration - timeline
        if tail >= 0.03:
            silence_path = tmp_path / f"tail_{part_idx}.mp3"
            await _make_silence(tail, silence_path)
            parts.append(silence_path)
        audio_duration = video_duration
    elif audio_duration > video_duration + 0.05:
        logger.info(
            "Voice track extends beyond video by %.2fs (video=%.2fs audio=%.2fs)",
            audio_duration - video_duration,
            video_duration,
            audio_duration,
        )

    list_file = tmp_path / "concat.txt"
    lines = []
    for p in parts:
        escaped = str(p).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    concat_mp3 = tmp_path / "voice_concat.mp3"
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c:a", "libmp3lame",
        "-q:a", "4",
        str(concat_mp3),
    ]
    await _run_ffmpeg(cmd_concat, "voice concat")

    # Loudness only — do not trim speech to video length
    cmd_norm = [
        "ffmpeg", "-y",
        "-i", str(concat_mp3),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a", "libmp3lame",
        "-q:a", "4",
        str(voice_out),
    ]
    await _run_ffmpeg(cmd_norm, "voice normalize")
    return max(audio_duration, await _probe_duration(voice_out))


async def _run_ffmpeg(cmd: list[str], label: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        _stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_DUB_TIMEOUT_SEC
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise VoiceProcessingError(f"{label}: ffmpeg timed out") from exc
    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[:800]
        raise VoiceProcessingError(f"{label}: {err}")


async def _build_voice_mp3_timed(
    cues: list[dict],
    lang: str,
    tmp_path: Path,
    video_duration: float,
    *,
    mode: str = "extended",
) -> tuple[Path, float]:
    """Schedule TTS; returns (voice mp3 path, output duration)."""
    placed, _ = await _prepare_scheduled_segments(
        cues, lang, tmp_path, video_duration, mode=mode
    )
    if not placed:
        raise VoiceProcessingError("No speakable subtitle lines")

    voice_out = tmp_path / "voice.mp3"
    cap = mode == "fitted"
    audio_duration = await _concat_voice_timeline(
        placed, video_duration, voice_out, tmp_path, cap_to_video=cap
    )
    if cap:
        audio_duration = min(audio_duration, video_duration)
    return voice_out, audio_duration


async def _build_voice_mp3_full(cues: list[dict], lang: str, tmp_path: Path) -> Path:
    """Single TTS pass for long scripts — replaces entire audio track."""
    script = " ".join(c["text"] for c in cues).strip()
    if not script:
        raise VoiceProcessingError("Empty subtitle script")
    mp3_bytes = await _tts_mp3(script, lang)
    if not mp3_bytes:
        raise VoiceProcessingError("TTS returned empty audio")
    voice_out = tmp_path / "voice.mp3"
    voice_out.write_bytes(mp3_bytes)
    return voice_out


async def _probe_storage_duration(storage_key: str) -> float | None:
    if not storage.exists(storage_key):
        return None
    data = await storage.read_file_bytes(storage_key)
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        return await _probe_duration(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


async def _mux_video_audio(
    video_path: Path,
    voice_path: Path,
    output_path: Path,
    output_duration: float,
    *,
    extend_video: bool = False,
    mix_original: bool = False,
) -> float:
    """Replace audio with dubbed track; optionally freeze-extend video for longer audio."""
    source_video_dur = await _probe_duration(video_path)
    pad_video = extend_video and output_duration > source_video_dur + 0.05

    if mix_original:
        filter_audio = (
            "[0:a]volume=0.15[orig];[1:a]volume=1.0[dub];"
            "[orig][dub]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(voice_path),
            "-filter_complex", filter_audio,
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path),
        ]
    elif pad_video:
        pad_sec = output_duration - source_video_dur
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(voice_path),
            "-filter_complex",
            f"[0:v]tpad=stop_mode=clone:stop_duration={pad_sec:.3f}[vout]",
            "-map", "[vout]",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{output_duration:.3f}",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(voice_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{output_duration:.3f}",
            "-movflags", "+faststart",
            str(output_path),
        ]
    await _run_ffmpeg(cmd, "mux dubbed video")
    return await _probe_duration(output_path)


async def generate_dubbed_video(
    video_storage_path: str,
    lang: str,
    *,
    mode: str = "fitted",
) -> str:
    """
    Build dubbed MP4 from translated SRT + voice scripts + TTS.
    mode: 'fitted' (≤ video duration) or 'extended' (may extend).
    """
    mode = (mode or "fitted").strip().lower()
    if lang not in _VALID_LANGS:
        raise VoiceProcessingError(f"Unsupported voice language: {lang}")
    if mode not in ("fitted", "extended"):
        raise VoiceProcessingError(f"Unsupported voice mode: {mode}")

    logger.info("[Voiceover] mode received: %s", mode)

    if not _api_key_ok():
        raise VoiceProcessingError("OpenAI API key not configured")

    srt_key = translated_subtitle_path_for(video_storage_path, lang)
    if not storage.exists(srt_key):
        raise VoiceProcessingError(f"Subtitle file not found: {lang}")

    output_key = (
        dubbed_video_fitted_path_for(video_storage_path, lang)
        if mode == "fitted"
        else dubbed_video_extended_path_for(video_storage_path, lang)
    )
    srt_content = (await storage.read_file_bytes(srt_key)).decode("utf-8")
    cues = _cues_with_timing(parse_srt(srt_content))
    if not cues:
        raise VoiceProcessingError("No timed subtitles to dub")

    video_bytes = await storage.read_file_bytes(video_storage_path)
    suffix = Path(video_storage_path).suffix.lower() or ".mp4"
    if suffix not in (".mp4", ".mov", ".webm", ".mkv"):
        suffix = ".mp4"

    logger.info("[Voiceover] output path: %s", output_key)
    logger.info(
        "Voice dubbing start — video=%s lang=%s mode=%s cues=%d → %s",
        video_storage_path, lang, mode, len(cues), output_key,
    )

    try:
        with tempfile.TemporaryDirectory(prefix="voice_dub_") as tmp:
            tmp_path = Path(tmp)
            input_video = tmp_path / f"input{suffix}"
            output_video = tmp_path / "output.mp4"
            input_video.write_bytes(video_bytes)
            duration = await _probe_duration(input_video)
            output_duration = duration

            if len(cues) <= _MAX_TTS_CUES:
                voice_mp3, audio_duration = await _build_voice_mp3_timed(
                    cues, lang, tmp_path, duration, mode=mode
                )
                if mode == "fitted":
                    output_duration = duration
                    if audio_duration > duration + 0.05:
                        raise VoiceProcessingError(VoiceProcessingError.FITTED_TOO_LONG)
                else:
                    output_duration = max(duration, audio_duration)
            else:
                logger.info("Voice dubbing: %d cues — using full-script TTS", len(cues))
                voice_mp3 = await _build_voice_mp3_full(cues, lang, tmp_path)
                audio_duration = await _probe_duration(voice_mp3)
                if mode == "fitted" and audio_duration > duration:
                    raise VoiceProcessingError(VoiceProcessingError.FITTED_TOO_LONG)
                output_duration = duration if mode == "fitted" else max(duration, audio_duration)

            mux_duration = await _mux_video_audio(
                input_video,
                voice_mp3,
                output_video,
                output_duration,
                extend_video=(mode == "extended"),
                mix_original=False,
            )
            if mode == "fitted" and mux_duration > duration + 0.15:
                raise VoiceProcessingError(VoiceProcessingError.FITTED_TOO_LONG)

            if not output_video.is_file() or output_video.stat().st_size == 0:
                raise VoiceProcessingError("Dubbed video file is empty")

            out_bytes = output_video.read_bytes()

        # Safe regeneration: overwrite previous dubbed file at the same key
        if storage.exists(output_key):
            logger.info("Voice dubbing: replacing existing %s", output_key)
            await storage.delete_file(output_key)
        await storage.save_at_key(output_key, out_bytes)

        fitted_key = dubbed_video_fitted_path_for(video_storage_path, lang)
        extended_key = dubbed_video_extended_path_for(video_storage_path, lang)
        fitted_dur = await _probe_storage_duration(fitted_key)
        extended_dur = await _probe_storage_duration(extended_key)
        if fitted_dur is not None:
            logger.info("[Voiceover] fitted duration: %.3fs", fitted_dur)
        if extended_dur is not None:
            logger.info("[Voiceover] extended duration: %.3fs", extended_dur)

    except VoiceProcessingError:
        raise
    except Exception as exc:
        logger.error(
            "Voice dubbing failed — video=%s lang=%s: %s",
            video_storage_path, lang, exc, exc_info=True,
        )
        raise VoiceProcessingError(str(exc)) from exc

    logger.info("Voice dubbing done — %s", output_key)
    return output_key
