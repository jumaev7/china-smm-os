"""AI Operator Copilot — suggest actions for operator inbox items."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.schemas.content import PLATFORMS
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.telegram_group_agent_service import (
    _catalogue_client_buffer,
    _heuristic_parse,
    _load_buffer_entries,
    _resolve_selection,
    _scoped_client_entries_for_reply,
)
from app.services.telegram_instruction_service import _parse_schedule_datetime

logger = logging.getLogger(__name__)

_CLIENT_SENDER_ROLES = frozenset({"client"})


async def _get_inbox_entry(
    db: AsyncSession,
    inbox_id: UUID,
) -> TelegramGroupBufferMessage:
    result = await db.execute(
        select(TelegramGroupBufferMessage)
        .options(selectinload(TelegramGroupBufferMessage.client))
        .where(TelegramGroupBufferMessage.id == inbox_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    if entry.sender_role not in _CLIENT_SENDER_ROLES:
        raise HTTPException(status_code=400, detail="Not a client buffer message")
    return entry


OperatorIntent = Literal[
    "create_post",
    "edit_existing",
    "schedule_post",
    "ask_question",
    "unclear",
]

VALID_INTENTS = frozenset({
    "create_post",
    "edit_existing",
    "schedule_post",
    "ask_question",
    "unclear",
})

_SUGGEST_SYSTEM = """\
You are an SMM operator copilot. Analyze a Telegram client inbox item (message + buffered media catalogue)
and recommend the best operator action. Do NOT suggest auto-publishing — admin approval is always required.

Return ONLY JSON:
{
  "intent": "create_post|edit_existing|schedule_post|ask_question|unclear",
  "suggested_action": "short imperative for operator (English or Russian)",
  "suggested_platforms": ["instagram", "telegram", ...],
  "suggested_schedule": "ISO-8601 UTC datetime or null",
  "media_selection": {
    "photo_ordinals": [1],
    "video_ordinals": [],
    "buffer_ids": [],
    "use_all_media": false,
    "use_client_text_as_description": true,
    "summary": "one line: which photos/videos to use"
  },
  "reason": "1-2 sentences why"
}

Rules:
- create_post: client sent publishable material (photos/video + caption)
- edit_existing: client asks to change an existing draft/post (правки, измени, edit, update)
- schedule_post: client mentions when to publish (завтра, в 18:00, schedule, Monday)
- ask_question: client asks a question without clear publish intent
- unclear: not enough info
- photo_ordinals/video_ordinals are 1-based within CLIENT photos/videos in catalogue
- buffer_ids: use catalogue buffer_id strings when specific files are meant
- use_all_media true when client sent an album or "все фото"
- suggested_platforms subset of: instagram, facebook, tiktok, telegram, linkedin
- Never set run_prepare or publishing flags
"""


def _normalize_platforms(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return ["instagram"]
    out: list[str] = []
    for p in raw:
        key = str(p).lower().strip()
        if key in PLATFORMS and key not in out:
            out.append(key)
    return out or ["instagram"]


def _normalize_intent(raw: Any) -> str:
    key = str(raw or "unclear").lower().strip()
    return key if key in VALID_INTENTS else "unclear"


def _normalize_media_selection(raw: Any, catalogue: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    photos = catalogue.get("photos") or []
    videos = catalogue.get("videos") or []
    photo_ordinals = [
        int(x) for x in (raw.get("photo_ordinals") or [])
        if isinstance(x, (int, float)) and 1 <= int(x) <= max(len(photos), 1)
    ]
    video_ordinals = [
        int(x) for x in (raw.get("video_ordinals") or [])
        if isinstance(x, (int, float)) and 1 <= int(x) <= max(len(videos), 1)
    ]
    buffer_ids = [str(x) for x in (raw.get("buffer_ids") or []) if x]
    use_all = bool(raw.get("use_all_media"))
    if not photo_ordinals and not video_ordinals and not buffer_ids:
        if len(photos) == 1:
            photo_ordinals = [1]
        elif len(videos) == 1:
            video_ordinals = [1]
        elif photos or videos:
            use_all = True
    return {
        "photo_ordinals": photo_ordinals,
        "video_ordinals": video_ordinals,
        "buffer_ids": buffer_ids,
        "use_all_media": use_all,
        "use_client_text_as_description": bool(
            raw.get("use_client_text_as_description", True),
        ),
        "summary": (raw.get("summary") or "")[:300] or None,
    }


def _heuristic_inbox_suggest(
    *,
    text: str,
    catalogue: dict[str, Any],
    client: Client | None,
    has_active_content: bool,
) -> dict[str, Any]:
    lower = (text or "").lower().strip()
    photos = catalogue.get("photos") or []
    videos = catalogue.get("videos") or []

    intent: OperatorIntent = "create_post"
    if any(p in lower for p in (
        "?", "как ", "сколько", "можно ли", "why ", "how ", "when ", "что такое",
    )) and not any(p in lower for p in ("опублик", "пост", "post", "вылож")):
        intent = "ask_question"
    elif any(p in lower for p in (
        "измени", "исправ", "правк", "обнови", "edit", "update", "change",
    )) and has_active_content:
        intent = "edit_existing"
    elif _parse_schedule_datetime(text):
        intent = "schedule_post"
    elif not photos and not videos and len(lower) < 20:
        intent = "unclear"
    elif not photos and not videos:
        intent = "ask_question" if "?" in lower else "unclear"

    parsed = _heuristic_parse(text or "создай пост из материалов клиента", catalogue)
    media = _normalize_media_selection(
        {
            "photo_ordinals": parsed.get("photo_ordinals"),
            "video_ordinals": parsed.get("video_ordinals"),
            "use_client_text_as_description": parsed.get("use_client_text_as_description"),
            "use_all_media": not parsed.get("photo_ordinals") and not parsed.get("video_ordinals"),
        },
        catalogue,
    )

    schedule_dt = _parse_schedule_datetime(text)
    schedule_iso = schedule_dt.isoformat() if schedule_dt else None

    platforms: list[str] = ["instagram"]
    if "telegram" in lower or "телеграм" in lower or "тг" in lower:
        platforms.append("telegram")
    if "instagram" in lower or "инстаграм" in lower or "инста" in lower:
        platforms = ["instagram"] + [p for p in platforms if p != "instagram"]
    if "facebook" in lower or "фейсбук" in lower:
        platforms.append("facebook")
    if "tiktok" in lower or "тикток" in lower:
        platforms.append("tiktok")
    platforms = _normalize_platforms(platforms)

    if intent == "edit_existing":
        action = "Update active draft with client feedback (no auto-publish)"
    elif intent == "schedule_post":
        action = "Create draft and set suggested schedule (admin approves before publish)"
    elif intent == "ask_question":
        action = "Reply to client or clarify before creating content"
    elif intent == "unclear":
        action = "Review materials and ask client for details"
    else:
        action = "Create draft from selected client media"

    reason = parsed.get("reason") or "Rule-based analysis of client message and buffer catalogue"
    if intent == "schedule_post" and schedule_iso:
        reason = f"Schedule mentioned in message ({schedule_iso}). {reason}"

    active_id = None
    if client and client.telegram_active_content_id:
        active_id = str(client.telegram_active_content_id)

    return {
        "intent": intent,
        "suggested_action": action,
        "suggested_platforms": platforms,
        "suggested_schedule": schedule_iso,
        "media_selection": media,
        "reason": reason[:500],
        "active_content_id": active_id,
        "source": "fallback",
    }


async def _ai_inbox_suggest(
    *,
    db: AsyncSession,
    text: str,
    catalogue: dict[str, Any],
    client: Client | None,
    has_active_content: bool,
) -> dict[str, Any]:
    _validate_api_key()
    openai = get_openai()
    company = client.company_name if client else "Unknown"
    active_line = ""
    if has_active_content and client and client.telegram_active_content_id:
        active_line = f"Active draft content_id: {client.telegram_active_content_id}\n"

    user_block = (
        f"CLIENT: {company}\n"
        f"{active_line}"
        f"INBOX MESSAGE:\n{(text or '(no text)')[:2000]}\n\n"
        f"PHOTOS:\n{json.dumps(catalogue['photos'], ensure_ascii=False)}\n\n"
        f"VIDEOS:\n{json.dumps(catalogue['videos'], ensure_ascii=False)}\n\n"
        f"TEXTS:\n{json.dumps(catalogue['texts'], ensure_ascii=False)}"
    )
    if client:
        from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
        kb_block = await ClientKnowledgeBaseService.build_prompt_block(
            db, client.id, context="operator_ai",
        )
        if kb_block:
            user_block = f"{user_block}\n\n{kb_block}"
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SUGGEST_SYSTEM},
            {"role": "user", "content": user_block},
        ],
        temperature=0.2,
        max_tokens=500,
        response_format={"type": "json_object"},
    )
    raw = _extract_json(response.choices[0].message.content or "{}")
    intent = _normalize_intent(raw.get("intent"))
    schedule = raw.get("suggested_schedule")
    schedule_iso: str | None = None
    if schedule:
        try:
            if isinstance(schedule, str):
                dt = datetime.fromisoformat(schedule.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                schedule_iso = dt.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError):
            schedule_iso = None
    if not schedule_iso:
        dt = _parse_schedule_datetime(text)
        if dt:
            schedule_iso = dt.isoformat()
    if intent == "schedule_post" and not schedule_iso:
        dt = _parse_schedule_datetime(text)
        if dt:
            schedule_iso = dt.isoformat()

    media = _normalize_media_selection(raw.get("media_selection"), catalogue)
    active_id = raw.get("active_content_id")
    if not active_id and client and client.telegram_active_content_id:
        active_id = str(client.telegram_active_content_id)

    return {
        "intent": intent,
        "suggested_action": (raw.get("suggested_action") or "Review inbox item")[:300],
        "suggested_platforms": _normalize_platforms(raw.get("suggested_platforms")),
        "suggested_schedule": schedule_iso,
        "media_selection": media,
        "reason": (raw.get("reason") or "AI suggestion")[:500],
        "active_content_id": str(active_id) if active_id else None,
        "source": "ai",
    }


def resolve_media_from_suggestion(
    entries: list[TelegramGroupBufferMessage],
    media_selection: dict[str, Any],
) -> tuple[list[TelegramGroupBufferMessage], str | None]:
    entry_by_id = {str(e.id): e for e in entries}
    buffer_ids = media_selection.get("buffer_ids") or []
    selected: list[TelegramGroupBufferMessage] = []

    for bid in buffer_ids:
        entry = entry_by_id.get(str(bid))
        if entry and entry not in selected:
            selected.append(entry)

    if media_selection.get("use_all_media"):
        for e in entries:
            if e.sender_role == "client" and e.media_file_id and e not in selected:
                selected.append(e)

    if not selected:
        parsed = {
            "photo_ordinals": media_selection.get("photo_ordinals") or [],
            "video_ordinals": media_selection.get("video_ordinals") or [],
            "text_ordinal": media_selection.get("text_ordinal"),
            "use_client_text_as_description": media_selection.get(
                "use_client_text_as_description", True,
            ),
        }
        selected, source_text = _resolve_selection(entries, parsed)
        if selected:
            return selected, source_text

    source_text: str | None = None
    if media_selection.get("use_client_text_as_description"):
        client_texts = [
            e for e in entries
            if e.sender_role == "client" and e.message_type == "text" and (e.text or "").strip()
        ]
        if client_texts:
            source_text = client_texts[-1].text.strip()

    if not source_text:
        for entry in selected:
            if entry.text and (entry.text or "").strip():
                source_text = entry.text.strip()
                break

    return selected, source_text


def can_apply_suggestion(suggestion: dict[str, Any]) -> bool:
    intent = suggestion.get("intent")
    if intent in ("ask_question", "unclear"):
        return False
    if intent == "edit_existing":
        return bool(suggestion.get("active_content_id"))
    return True


def load_cached_suggestion(entry: TelegramGroupBufferMessage) -> dict[str, Any] | None:
    raw = entry.ai_suggestion_json
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data["cached"] = True
        if entry.ai_suggested_at:
            data["cached_at"] = entry.ai_suggested_at.isoformat()
        return data
    return None


class OperatorAiService:
    @staticmethod
    async def suggest_for_inbox(
        db: AsyncSession,
        inbox_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        entry = await _get_inbox_entry(db, inbox_id)
        if not force_refresh:
            cached = load_cached_suggestion(entry)
            if cached:
                logger.info("[Operator AI] suggest: inbox=%s cached=true", inbox_id)
                return cached

        client = entry.client
        group_entries = await _load_buffer_entries(db, entry.client_id, entry.group_id)
        scope = _scoped_client_entries_for_reply(group_entries, entry)
        catalogue = _catalogue_client_buffer(scope)
        text = (entry.text or "").strip()
        if not text:
            for e in scope:
                if e.text and (e.text or "").strip():
                    text = e.text.strip()
                    break

        has_active = bool(client and client.telegram_active_content_id)

        if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
            suggestion = _heuristic_inbox_suggest(
                text=text,
                catalogue=catalogue,
                client=client,
                has_active_content=has_active,
            )
            logger.info(
                "[Operator AI] fallback: inbox=%s intent=%s",
                inbox_id,
                suggestion.get("intent"),
            )
        else:
            try:
                suggestion = await _ai_inbox_suggest(
                    db=db,
                    text=text,
                    catalogue=catalogue,
                    client=client,
                    has_active_content=has_active,
                )
                logger.info(
                    "[Operator AI] suggest: inbox=%s intent=%s source=ai",
                    inbox_id,
                    suggestion.get("intent"),
                )
            except Exception as exc:
                logger.warning(
                    "[Operator AI] fallback: inbox=%s error=%s",
                    inbox_id,
                    exc,
                )
                suggestion = _heuristic_inbox_suggest(
                    text=text,
                    catalogue=catalogue,
                    client=client,
                    has_active_content=has_active,
                )

        suggestion["inbox_id"] = str(inbox_id)
        suggestion["cached"] = False
        entry.ai_suggestion_json = json.dumps(suggestion, ensure_ascii=False)
        entry.ai_suggested_at = datetime.now(timezone.utc)
        await db.commit()

        suggestion["cached"] = True
        suggestion["cached_at"] = entry.ai_suggested_at.isoformat()
        return suggestion

    @staticmethod
    def get_cached_or_raise(entry: TelegramGroupBufferMessage) -> dict[str, Any]:
        cached = load_cached_suggestion(entry)
        if not cached:
            raise HTTPException(
                status_code=400,
                detail="No AI suggestion — call ai-suggest first",
            )
        return cached
