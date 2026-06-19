"""
One-click content preparation workflow — sequential steps with in-memory progress.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.storage import storage
from app.models.client import Client
from app.models.content import ContentItem
from app.schemas.workflow import WorkflowPrepareRequest, WorkflowStepId
from app.services.ai_service import generate_content, get_openai, _validate_api_key
from app.services.brand_profile import brand_profile_from_client
from app.services.context_ai_service import build_context_signals
from app.services.content_service import ContentService
from app.services.telegram_instruction_service import extract_client_source_text
from app.services.subtitle_service import (
    TRANSLATED_LANG_CODES,
    parse_srt,
    save_subtitle_file,
    subtitle_path_for,
    translated_subtitle_path_for,
)
from app.services.subtitle_translation_service import generate_translated_subtitles
from app.services.transcription_service import transcribe_video_detailed

logger = logging.getLogger(__name__)

WORKFLOW_STEPS: list[tuple[WorkflowStepId, str]] = [
    ("subtitles", "Subtitles"),
    ("translations", "Translations"),
    ("captions", "Captions"),
    ("hashtags", "Hashtags"),
    ("post_time", "Post time"),
    ("voice", "Voiceover"),
    ("export", "Final export"),
    ("status", "Ready for approval"),
]

_workflows: dict[str, dict] = {}
_workflow_lock = asyncio.Lock()

_SRT_RANGE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})$"
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _empty_progress(content_id: UUID) -> dict:
    return {
        "content_id": str(content_id),
        "status": "idle",
        "current_step": None,
        "steps": [
            {"id": sid, "label": label, "status": "pending", "error": None,
             "started_at": None, "finished_at": None}
            for sid, label in WORKFLOW_STEPS
        ],
        "started_at": None,
        "finished_at": None,
        "message": "",
        "can_retry": False,
        "options": None,
        "_segments": None,
    }


def get_progress(content_id: UUID) -> dict:
    key = str(content_id)
    state = _workflows.get(key)
    if not state:
        return _empty_progress(content_id)
    return _public_state(state)


def _public_state(state: dict) -> dict:
    return {
        "content_id": state["content_id"],
        "status": state["status"],
        "current_step": state["current_step"],
        "steps": [
            {k: v for k, v in step.items()}
            for step in state["steps"]
        ],
        "started_at": state["started_at"],
        "finished_at": state["finished_at"],
        "message": state["message"],
        "can_retry": state["can_retry"],
    }


def _step_index(step_id: WorkflowStepId) -> int:
    return next(i for i, (sid, _) in enumerate(WORKFLOW_STEPS) if sid == step_id)


def _set_step(state: dict, step_id: WorkflowStepId, *, status: str, error: str | None = None) -> None:
    idx = _step_index(step_id)
    step = state["steps"][idx]
    now = _utcnow()
    if status == "running":
        step["started_at"] = now
        step["error"] = None
    if status in ("completed", "failed", "skipped"):
        step["finished_at"] = now
        if error:
            step["error"] = error
    step["status"] = status
    logger.info(
        "[Workflow] finished: step=%s content_id=%s status=%s%s",
        step_id,
        state["content_id"],
        status,
        f" error={error}" if error else "",
    )


def _ts_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _cues_to_segments(cues: list[dict]) -> list[dict]:
    segments: list[dict] = []
    for cue in cues:
        match = _SRT_RANGE.match(cue["time_line"])
        if not match:
            continue
        g = match.groups()
        start = _ts_to_seconds(g[0], g[1], g[2], g[3])
        end = _ts_to_seconds(g[4], g[5], g[6], g[7])
        segments.append({"start": start, "end": end, "text": cue["text"]})
    return segments


def _extract_source_text(item: ContentItem) -> str | None:
    text = extract_client_source_text(item.internal_notes)
    return text or None


def _append_internal_note(item: ContentItem, marker: str, value: str) -> None:
    notes = item.internal_notes or ""
    line = f"{marker} {value}".strip()
    if marker in notes:
        parts = notes.split("\n")
        parts = [line if p.startswith(marker) else p for p in parts]
        if not any(p.startswith(marker) for p in parts):
            parts.append(line)
        item.internal_notes = "\n".join(parts).strip()
    else:
        item.internal_notes = f"{notes}\n{line}".strip() if notes else line


async def _suggest_posting_time(client: Client, item: ContentItem) -> str:
    if settings.DEMO_MODE:
        return "Wed 18:00–20:00 Tashkent (Asia/Tashkent) — Instagram / TikTok peak"

    _validate_api_key()
    openai = get_openai()
    prompt = (
        f"Business: {client.company_name} ({client.business_category})\n"
        f"Platforms: {', '.join(item.platforms or ['instagram'])}\n"
        f"Caption RU: {(item.caption_short_ru or '')[:200]}\n\n"
        "Suggest the best posting time for Instagram/TikTok in Uzbekistan (Tashkent timezone). "
        "Return JSON only: {\"suggestion\": \"short human-readable recommendation\"}"
    )
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "You are a social media scheduling expert for Uzbekistan."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        max_tokens=200,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)
    return (data.get("suggestion") or "Weekday 18:00–20:00 Tashkent time").strip()


async def _step_subtitles(db: AsyncSession, item: ContentItem, state: dict) -> None:
    if not item.media_file or item.media_file.file_type != "video":
        raise ValueError("Not a video — subtitles skipped")

    sp = item.media_file.storage_path
    if storage.exists(subtitle_path_for(sp)):
        srt_bytes = await storage.read_file_bytes(subtitle_path_for(sp))
        cues = parse_srt(srt_bytes.decode("utf-8", errors="replace"))
        state["_segments"] = _cues_to_segments(cues)
        return

    raw = await storage.read_file_bytes(sp)
    tx = await transcribe_video_detailed(raw)
    if not tx.segments:
        raise ValueError("No speech detected in video")

    state["_segments"] = tx.segments
    sub_key = await save_subtitle_file(sp, tx.segments)
    if not sub_key:
        raise ValueError("Failed to save subtitle file")

    if tx.source_text:
        _append_internal_note(item, "[Transcript]:", tx.source_text.strip())
        await db.commit()


async def _step_translations(db: AsyncSession, item: ContentItem, state: dict) -> None:
    if not item.media_file or item.media_file.file_type != "video":
        raise ValueError("Not a video — translations skipped")

    sp = item.media_file.storage_path
    missing = [
        lang for lang in TRANSLATED_LANG_CODES
        if not storage.exists(translated_subtitle_path_for(sp, lang))
    ]
    if not missing:
        return

    segments = state.get("_segments")
    if not segments and storage.exists(subtitle_path_for(sp)):
        srt_bytes = await storage.read_file_bytes(subtitle_path_for(sp))
        segments = _cues_to_segments(parse_srt(srt_bytes.decode("utf-8", errors="replace")))
    if not segments:
        raise ValueError("No subtitle segments available for translation")

    await generate_translated_subtitles(sp, segments)


async def _step_captions(db: AsyncSession, item: ContentItem, state: dict, options: WorkflowPrepareRequest) -> None:
    result = await db.execute(select(Client).where(Client.id == item.client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise ValueError("Client not found")

    source_text = options.source_text or _extract_source_text(item)
    source_lang = options.source_language or client.source_language or "zh"
    context_signals = await build_context_signals(
        db, client=client, item=item, source_text=source_text,
    )

    from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
    kb_block = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, context="content_generation",
    )

    generated = await generate_content(
        company_name=client.company_name,
        business_category=client.business_category,
        content_style=client.content_style,
        source_language=source_lang,
        source_text=source_text,
        context_hint=options.context_hint,
        client_notes=client.notes,
        brand_profile=brand_profile_from_client(client),
        context_signals=context_signals,
        knowledge_base_block=kb_block or None,
    )
    await ContentService.apply_generated(db, item.id, generated)


async def _step_hashtags(db: AsyncSession, item: ContentItem, state: dict, options: WorkflowPrepareRequest) -> None:
    item = await ContentService.get(db, item.id)
    if item.hashtags and item.hashtags.strip():
        return

    result = await db.execute(select(Client).where(Client.id == item.client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise ValueError("Client not found")

    source_text = options.source_text or _extract_source_text(item)
    context_signals = await build_context_signals(
        db, client=client, item=item, source_text=source_text,
    )

    generated = await generate_content(
        company_name=client.company_name,
        business_category=client.business_category,
        content_style=client.content_style,
        source_language=options.source_language or client.source_language or "zh",
        source_text=source_text,
        context_hint=options.context_hint,
        client_notes=client.notes,
        brand_profile=brand_profile_from_client(client),
        context_signals=context_signals,
    )
    item = await ContentService.get(db, item.id)
    item.hashtags = generated.hashtags
    await db.commit()


async def _step_post_time(db: AsyncSession, item: ContentItem, state: dict) -> None:
    result = await db.execute(select(Client).where(Client.id == item.client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise ValueError("Client not found")

    item = await ContentService.get(db, item.id)
    suggestion = await _suggest_posting_time(client, item)
    _append_internal_note(item, "[Suggested post time]:", suggestion)
    await db.commit()


async def _step_voice(db: AsyncSession, item: ContentItem, state: dict, options: WorkflowPrepareRequest) -> None:
    if not item.media_file or item.media_file.file_type != "video":
        raise ValueError("Not a video — voiceover skipped")

    await ContentService.generate_voiceover(
        db, item.id, options.voice_lang, mode=options.voice_mode,
    )


async def _step_export(db: AsyncSession, item: ContentItem, state: dict, options: WorkflowPrepareRequest) -> None:
    if not item.media_file or item.media_file.file_type != "video":
        raise ValueError("Not a video — export skipped")

    await ContentService.generate_final_export(
        db,
        item.id,
        options.subtitle_lang,
        options.voice_lang,
        options.voice_mode,
    )


async def _step_status(db: AsyncSession, item: ContentItem, state: dict) -> None:
    await ContentService.mark_ready_for_approval(db, item.id)


async def _run_step(
    db: AsyncSession,
    item: ContentItem,
    state: dict,
    step_id: WorkflowStepId,
    options: WorkflowPrepareRequest,
) -> None:
    logger.info("[Workflow] step: %s content_id=%s", step_id, state["content_id"])
    handlers = {
        "subtitles": lambda: _step_subtitles(db, item, state),
        "translations": lambda: _step_translations(db, item, state),
        "captions": lambda: _step_captions(db, item, state, options),
        "hashtags": lambda: _step_hashtags(db, item, state, options),
        "post_time": lambda: _step_post_time(db, item, state),
        "voice": lambda: _step_voice(db, item, state, options),
        "export": lambda: _step_export(db, item, state, options),
        "status": lambda: _step_status(db, item, state),
    }
    await handlers[step_id]()


async def _execute_workflow(content_id: UUID, options: WorkflowPrepareRequest, from_step: WorkflowStepId | None = None) -> None:
    key = str(content_id)
    state = _workflows[key]
    start_idx = _step_index(from_step) if from_step else 0

    try:
        async with AsyncSessionLocal() as db:
            item = await ContentService.get(db, content_id)

            for idx in range(start_idx, len(WORKFLOW_STEPS)):
                step_id, _ = WORKFLOW_STEPS[idx]
                state["current_step"] = step_id
                _set_step(state, step_id, status="running")

                try:
                    item = await ContentService.get(db, content_id)
                    await _run_step(db, item, state, step_id, options)
                    _set_step(state, step_id, status="completed")
                except ValueError as exc:
                    msg = str(exc)
                    if "skipped" in msg.lower():
                        _set_step(state, step_id, status="skipped", error=msg)
                    else:
                        _set_step(state, step_id, status="failed", error=msg)
                except Exception as exc:
                    _set_step(state, step_id, status="failed", error=str(exc)[:500])
                    logger.warning(
                        "[Workflow] step failed: %s content_id=%s — %s",
                        step_id, content_id, exc, exc_info=True,
                    )

            failed = [s for s in state["steps"] if s["status"] == "failed"]
            state["current_step"] = None
            state["finished_at"] = _utcnow()
            state["can_retry"] = bool(failed)

            if failed:
                state["status"] = "failed"
                state["message"] = f"Completed with {len(failed)} failed step(s)"
            else:
                state["status"] = "completed"
                state["message"] = "Everything ready"
                state["can_retry"] = False

            logger.info("[Workflow] finished: content_id=%s status=%s", content_id, state["status"])
    except Exception as exc:
        state["status"] = "failed"
        state["current_step"] = None
        state["finished_at"] = _utcnow()
        state["message"] = str(exc)[:200]
        state["can_retry"] = True
        logger.error("[Workflow] finished: content_id=%s fatal error=%s", content_id, exc, exc_info=True)


async def start_workflow(content_id: UUID, options: WorkflowPrepareRequest) -> dict:
    key = str(content_id)
    async with _workflow_lock:
        existing = _workflows.get(key)
        if existing and existing["status"] == "running":
            return _public_state(existing)

        state = _empty_progress(content_id)
        state["status"] = "running"
        state["started_at"] = _utcnow()
        state["message"] = "Preparing..."
        state["options"] = options.model_dump()
        _workflows[key] = state

    logger.info("[Workflow] started: content_id=%s", content_id)
    asyncio.create_task(_execute_workflow(content_id, options))
    return _public_state(state)


async def retry_workflow(content_id: UUID, step: WorkflowStepId | None = None) -> dict:
    key = str(content_id)
    async with _workflow_lock:
        state = _workflows.get(key)
        if not state or state["status"] == "running":
            raise ValueError("No workflow to retry or workflow already running")

        options_data = state.get("options") or {}
        options = WorkflowPrepareRequest(**options_data)

        if step:
            from_idx = _step_index(step)
        else:
            failed_ids = [s["id"] for s in state["steps"] if s["status"] == "failed"]
            if not failed_ids:
                raise ValueError("No failed steps to retry")
            from_idx = _step_index(failed_ids[0])

        for i, (sid, _) in enumerate(WORKFLOW_STEPS):
            if i >= from_idx:
                state["steps"][i] = {
                    "id": sid,
                    "label": WORKFLOW_STEPS[i][1],
                    "status": "pending",
                    "error": None,
                    "started_at": None,
                    "finished_at": None,
                }

        state["status"] = "running"
        state["current_step"] = None
        state["finished_at"] = None
        state["message"] = "Preparing..."
        state["can_retry"] = False
        from_step = WORKFLOW_STEPS[from_idx][0]

    logger.info("[Workflow] started: content_id=%s retry_from=%s", content_id, from_step)
    asyncio.create_task(_execute_workflow(content_id, options, from_step=from_step))
    return _public_state(state)
