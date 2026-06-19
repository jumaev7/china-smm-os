"""
Telegram Group Agent — buffer recent group messages and create content from admin instructions.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.storage import storage
from app.models.client import Client
from app.models.content import ContentItem
from app.models.media import MediaFile
from app.models.telegram_buffer import TelegramGroupBufferMessage, TelegramProcessedUpdate
from app.schemas.workflow import WorkflowPrepareRequest
from app.services.context_ai_service import detect_business_context, format_context_marker
from app.services.telegram_instruction_service import (
    TG_GROUP_BUFFER_SOURCE,
    set_admin_instruction,
    set_client_source,
    _append_instruction_history,
)

logger = logging.getLogger(__name__)

BUFFER_MAX_MESSAGES = 50
BUFFER_MAX_HOURS = 24

_CREATE_KEYWORDS = (
    "создай контент", "создай пост", "создать контент", "создать пост", "создай один пост",
    "один пост", "подготовь пост", "подготовь контент", "create content", "prepare post",
    "prepare content", "make post", "собери пост", "собери контент",
)
_ASSEMBLE_KEYWORDS = _CREATE_KEYWORDS + (
    "создай", "создать", "create", "prepare", "подготовь", "make post", "собери", "один пост",
)
_SELECT_KEYWORDS = (
    "выбери", "используй", "только видео", "последн", "перв", "втор", "трет",
    "четверт", "пят", "last video", "first photo", "select", "кроме", "except",
)

BUFFER_WAIT_REPLY = "📥 Materials buffered. Waiting for admin instruction."
BUFFER_REPLY_MEDIA = BUFFER_WAIT_REPLY
BUFFER_REPLY_CLIENT_REQUEST = BUFFER_WAIT_REPLY
BUFFER_REPLY_SUCCESS = "✅ Content created from selected materials."
BUFFER_REPLY_TASK_NOT_FOUND = "⚠️ Task not found for replied message"
ADMIN_ONLY_REPLY = "⚠️ Only admin can manage content tasks."
UNCLEAR_SELECTION_REPLY = (
    "⚠️ Не понял, какие материалы выбрать. Уточните: первое фото, последнее видео и т.д."
)

# Pending selection keyed by client_id (buffer mode, selection without create yet)
_pending_buffer_selection: dict[str, dict[str, Any]] = {}

_PARSE_SYSTEM = """\
Parse an admin instruction for a Telegram group content buffer.
The admin selects client media/text from a numbered list and asks to create a post.

Return ONLY JSON:
{
  "clear": true,
  "create_requested": true,
  "photo_ordinals": [1, 3],
  "video_ordinals": [],
  "text_ordinal": 1,
  "use_client_text_as_description": true,
  "run_prepare": false,
  "reason": "short explanation"
}

Rules:
- photo_ordinals / video_ordinals are 1-based indices within CLIENT photos/videos only
- text_ordinal is 1-based among CLIENT text-only messages
- run_prepare=true when admin says подготовь/prepare/prepare everything
- clear=false if you cannot determine which media to use
- "первое и третье фото" → photo_ordinals [1, 3]
- "последнее видео" → last video ordinal in the videos list
- "используй сообщение клиента" → use_client_text_as_description true, pick latest text if not specified
"""


def resolve_group_workflow_mode(client: Client) -> str:
    """Resolve workflow mode for a Telegram group client."""
    raw = getattr(client, "telegram_workflow_mode", None)
    if raw and str(raw).strip() == "admin_controlled_buffer":
        return "admin_controlled_buffer"
    if raw and str(raw).strip() == "auto_create_from_media":
        return "auto_create_from_media"
    if settings.TELEGRAM_GROUP_DEFAULT_BUFFER:
        logger.info(
            "[Group Agent] workflow_mode: missing — default admin_controlled_buffer (test default)",
        )
        return "admin_controlled_buffer"
    return "auto_create_from_media"


def is_buffer_mode(client: Client) -> bool:
    mode = resolve_group_workflow_mode(client)
    enabled = mode == "admin_controlled_buffer"
    logger.info("[Group Agent] workflow_mode: %s", mode)
    logger.info("[Group Agent] buffering_only: %s", enabled)
    return enabled


def is_admin_operator(telegram_user_id: int) -> bool:
    allowed_raw = settings.TELEGRAM_ADMIN_ID.strip()
    if not allowed_raw:
        return False
    allowed = {uid.strip() for uid in allowed_raw.split(",") if uid.strip()}
    return str(telegram_user_id) in allowed


def has_selection_intent(text: str) -> bool:
    lower = (text or "").lower().strip()
    if not lower:
        return False
    if any(k in lower for k in _SELECT_KEYWORDS):
        if any(w in lower for w in ("фото", "видео", "video", "photo", "сообщен", "media", "текст", "text")):
            return True
    if "только видео" in lower or "only video" in lower:
        return True
    if "последн" in lower and "видео" in lower:
        return True
    return False


def should_assemble_from_buffer(text: str) -> bool:
    """True when admin wants to create/assemble content from buffer (not edit-only)."""
    lower = (text or "").lower().strip()
    if not lower:
        return False
    if any(k in lower for k in _ASSEMBLE_KEYWORDS):
        return True
    # Selection + client wishes/description → assemble one post
    if has_selection_intent(lower) and any(
        w in lower for w in ("пожелан", "учти", "клиент", "описание", "client", "wish")
    ):
        return True
    # Explicit "create one post" patterns without full keyword match
    if "один пост" in lower or "one post" in lower or "только один" in lower:
        return True
    if "как клиент" in lower and any(w in lower for w in ("создай", "пост", "контент", "create")):
        return True
    if any(w in lower for w in ("сделай", "сделать", "оформи")) and any(
        w in lower for w in (
            "как клиент", "клиент", "попросил", "стиль", "премиум", "коротк",
            "пост", "контент", "luxury", "premium", "формальн",
        )
    ):
        return True
    return False


def is_buffer_reply_create_instruction(text: str) -> bool:
    """Admin replied to a buffered message — treat as draft/create intent."""
    lower = (text or "").lower().strip()
    if not lower:
        return False
    if should_assemble_from_buffer(text):
        return True
    return any(p in lower for p in (
        "как клиент", "клиент попросил", "попросил", "премиум", "premium", "luxury",
        "коротк", "стиль", "сделай", "сделать", "оформи", "подготовь", "формальн",
        "делов", "эмодзи", "emoji", "подпис", "caption", "контент", "пост",
    ))


def buffer_draft_dashboard_reply(content_id: UUID) -> str:
    base = (settings.PUBLIC_APP_URL or "http://localhost:3000").rstrip("/")
    return f"✅ Draft created\nOpen in dashboard: {base}/content/{content_id}"


def is_buffer_create_instruction(text: str) -> bool:
    """Alias: admin wants buffer agent to assemble content."""
    return should_assemble_from_buffer(text)


async def claim_update(db: AsyncSession, update_id: int | None) -> bool:
    """Return False if this update_id was already processed."""
    if update_id is None:
        return True
    existing = await db.get(TelegramProcessedUpdate, update_id)
    if existing:
        logger.info("[Group Agent] duplicate update_id=%s — skipped", update_id)
        return False
    db.add(TelegramProcessedUpdate(update_id=update_id))
    await db.flush()
    return True


def _message_type(message: dict) -> str:
    if message.get("photo"):
        return "photo"
    if message.get("video") or message.get("video_note"):
        return "video"
    if message.get("document"):
        return "document"
    return "text"


def _message_datetime(message: dict) -> datetime:
    ts = message.get("date")
    if ts:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return datetime.now(timezone.utc)


async def _download_message_media(
    db: AsyncSession,
    client: Client,
    message: dict,
) -> tuple[MediaFile | None, str]:
    from app.services.telegram_service import (
        VIDEO_MIME,
        _PHOTO_MIME,
        _ensure_video_extension,
        _get_file_bytes,
    )

    photo_list = message.get("photo")
    video = message.get("video")
    video_note = message.get("video_note")
    document = message.get("document")
    caption = (message.get("caption") or message.get("text") or "").strip()

    if not (photo_list or video or video_note or document):
        return None, caption

    try:
        if photo_list:
            file_id = photo_list[-1]["file_id"]
            mime = _PHOTO_MIME
            raw, fname = await _get_file_bytes(file_id)
            fname = fname if fname.endswith((".jpg", ".jpeg")) else f"{fname}.jpg"
            file_type = "image"
        elif video:
            file_id = video["file_id"]
            mime = video.get("mime_type") or VIDEO_MIME
            raw, fname = await _get_file_bytes(file_id)
            fname = _ensure_video_extension(fname)
            file_type = "video"
        elif video_note:
            file_id = video_note["file_id"]
            mime = VIDEO_MIME
            raw, fname = await _get_file_bytes(file_id)
            fname = _ensure_video_extension(fname)
            file_type = "video"
        else:
            file_id = document["file_id"]
            mime = document.get("mime_type", "application/octet-stream")
            file_type = "image" if mime.startswith("image/") else "video"
            raw, fname = await _get_file_bytes(file_id)
            fname = document.get("file_name", fname)
            if file_type == "video":
                fname = _ensure_video_extension(fname)

        if not raw:
            return None, caption

        folder = f"clients/{client.id}/telegram/buffer"
        storage_key = await storage.save_file(raw, fname, folder)
        media = MediaFile(
            client_id=client.id,
            original_filename=fname,
            file_type=file_type,
            mime_type=mime,
            storage_path=storage_key,
            thumbnail_path=None,
            file_size=len(raw),
        )
        db.add(media)
        await db.flush()
        return media, caption
    except Exception as exc:
        logger.warning("[Group Agent] media download failed: %s", exc)
        return None, caption


async def buffer_group_message(
    db: AsyncSession,
    *,
    client: Client,
    group_id: str,
    message: dict,
    sender_role: str,
    sender_id: str,
) -> TelegramGroupBufferMessage | None:
    msg_id = message.get("message_id")
    if msg_id is None:
        return None

    existing = await db.execute(
        select(TelegramGroupBufferMessage).where(
            TelegramGroupBufferMessage.group_id == group_id,
            TelegramGroupBufferMessage.message_id == msg_id,
        )
    )
    if existing.scalar_one_or_none():
        logger.debug("[Group Agent] duplicate buffer message group=%s msg=%s", group_id, msg_id)
        return None

    msg_type = _message_type(message)
    text = (message.get("text") or message.get("caption") or "").strip()
    media: MediaFile | None = None
    storage_path: str | None = None
    telegram_file_id: str | None = None

    if msg_type != "text":
        media, text_from_media = await _download_message_media(db, client, message)
        if text_from_media and not text:
            text = text_from_media
        if media:
            storage_path = media.storage_path
            telegram_file_id = (
                (message.get("photo") or [{}])[-1].get("file_id")
                if message.get("photo")
                else (message.get("video") or {}).get("file_id")
                or (message.get("video_note") or {}).get("file_id")
                or (message.get("document") or {}).get("file_id")
            )

    entry = TelegramGroupBufferMessage(
        client_id=client.id,
        group_id=group_id,
        message_id=msg_id,
        sender_id=sender_id,
        sender_role=sender_role,
        message_type=msg_type if msg_type != "document" else (
            "photo" if media and media.file_type == "image" else "video"
        ),
        telegram_file_id=telegram_file_id,
        media_file_id=media.id if media else None,
        storage_path=storage_path,
        text=text or None,
        message_at=_message_datetime(message),
    )
    db.add(entry)
    await db.flush()
    await _trim_buffer(db, group_id)

    logger.info(
        "[Group Agent] buffered: group=%s msg=%s role=%s type=%s media=%s",
        group_id, msg_id, sender_role, entry.message_type, bool(media),
    )
    return entry


async def _trim_buffer(db: AsyncSession, group_id: str) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=BUFFER_MAX_HOURS)
    await db.execute(
        delete(TelegramGroupBufferMessage).where(
            TelegramGroupBufferMessage.group_id == group_id,
            TelegramGroupBufferMessage.message_at < cutoff,
        )
    )
    result = await db.execute(
        select(TelegramGroupBufferMessage.id)
        .where(TelegramGroupBufferMessage.group_id == group_id)
        .order_by(TelegramGroupBufferMessage.message_at.desc())
        .offset(BUFFER_MAX_MESSAGES)
    )
    stale_ids = [row[0] for row in result.all()]
    if stale_ids:
        await db.execute(
            delete(TelegramGroupBufferMessage).where(
                TelegramGroupBufferMessage.id.in_(stale_ids)
            )
        )


async def find_buffer_message_by_telegram_id(
    db: AsyncSession,
    client_id: UUID,
    group_id: str,
    message_id: int,
) -> TelegramGroupBufferMessage | None:
    result = await db.execute(
        select(TelegramGroupBufferMessage).where(
            TelegramGroupBufferMessage.client_id == client_id,
            TelegramGroupBufferMessage.group_id == group_id,
            TelegramGroupBufferMessage.message_id == message_id,
        )
    )
    return result.scalar_one_or_none()


def _client_entries_for_bot_anchor(
    entries: list[TelegramGroupBufferMessage],
    anchor: TelegramGroupBufferMessage,
) -> list[TelegramGroupBufferMessage]:
    prior_bots = [
        e for e in entries
        if e.sender_role == "bot" and e.message_at < anchor.message_at
    ]
    cutoff = prior_bots[-1].message_at if prior_bots else None
    batch: list[TelegramGroupBufferMessage] = []
    for e in entries:
        if e.sender_role != "client":
            continue
        if e.message_at > anchor.message_at:
            continue
        if cutoff is not None and e.message_at <= cutoff:
            continue
        batch.append(e)
    return batch


def _scoped_client_entries_for_reply(
    entries: list[TelegramGroupBufferMessage],
    anchor: TelegramGroupBufferMessage | None,
) -> list[TelegramGroupBufferMessage]:
    if anchor is None:
        return [e for e in entries if e.sender_role == "client"]
    if anchor.sender_role == "bot":
        return _client_entries_for_bot_anchor(entries, anchor)
    if anchor.sender_role == "client":
        if anchor.media_file_id or anchor.message_type in ("photo", "video"):
            return [anchor]
        return [e for e in entries if e.sender_role == "client" and e.message_at >= anchor.message_at]
    return [e for e in entries if e.sender_role == "client" and e.message_at >= anchor.message_at]


async def resolve_buffer_task_from_reply(
    db: AsyncSession,
    *,
    client_id: UUID,
    group_id: str,
    reply_to_message: dict,
) -> tuple[list[TelegramGroupBufferMessage], TelegramGroupBufferMessage | None]:
    replied_id = reply_to_message.get("message_id")
    logger.info(
        "[Telegram Buffer] reply detected: group=%s reply_to=%s",
        group_id, replied_id,
    )
    entries = await _load_buffer_entries(db, client_id, group_id)
    anchor: TelegramGroupBufferMessage | None = None
    if replied_id is not None:
        anchor = await find_buffer_message_by_telegram_id(
            db, client_id, group_id, int(replied_id),
        )
    task_entries = _scoped_client_entries_for_reply(entries, anchor)
    if anchor:
        logger.info(
            "[Telegram Buffer] task linked: anchor_msg=%s role=%s client_entries=%d",
            anchor.message_id, anchor.sender_role, len(task_entries),
        )
    elif task_entries:
        logger.info(
            "[Telegram Buffer] task linked: fallback recent client_entries=%d",
            len(task_entries),
        )
    return task_entries, anchor


async def record_buffer_bot_ack(
    db: AsyncSession,
    *,
    client: Client,
    group_id: str,
    bot_message_id: int,
    reply_anchor_message_id: int,
) -> None:
    existing = await find_buffer_message_by_telegram_id(
        db, client.id, group_id, bot_message_id,
    )
    if existing:
        return
    db.add(TelegramGroupBufferMessage(
        client_id=client.id,
        group_id=group_id,
        message_id=bot_message_id,
        sender_id="bot",
        sender_role="bot",
        message_type="text",
        text=json.dumps({
            "kind": "buffer_ack",
            "reply_anchor": reply_anchor_message_id,
        }, ensure_ascii=False),
        message_at=datetime.now(timezone.utc),
    ))
    await db.flush()


def _apply_reply_instruction_defaults(
    parsed: dict[str, Any],
    catalogue: dict[str, Any],
    instruction: str,
) -> dict[str, Any]:
    lower = (instruction or "").lower()
    parsed["create_requested"] = True
    if any(p in lower for p in (
        "как клиент", "клиент попросил", "попросил", "пожелан", "учти",
        "client text", "сообщение клиента", "как описание",
    )):
        parsed["use_client_text_as_description"] = True
    photos = catalogue["photos"]
    videos = catalogue["videos"]
    texts = catalogue["texts"]
    if not parsed.get("photo_ordinals") and photos:
        parsed["photo_ordinals"] = list(range(1, len(photos) + 1))
    if not parsed.get("video_ordinals") and videos and not parsed.get("photo_ordinals"):
        parsed["video_ordinals"] = list(range(1, len(videos) + 1))
    if parsed.get("use_client_text_as_description") and texts and not parsed.get("text_ordinal"):
        parsed["text_ordinal"] = len(texts)
    parsed["clear"] = bool(
        parsed.get("photo_ordinals")
        or parsed.get("video_ordinals")
        or (parsed.get("use_client_text_as_description") and texts)
    )
    if not parsed["clear"] and (photos or videos):
        parsed["clear"] = True
    return parsed


async def _load_buffer_entries(db: AsyncSession, client_id: UUID, group_id: str) -> list[TelegramGroupBufferMessage]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=BUFFER_MAX_HOURS)
    result = await db.execute(
        select(TelegramGroupBufferMessage)
        .where(
            TelegramGroupBufferMessage.client_id == client_id,
            TelegramGroupBufferMessage.group_id == group_id,
            TelegramGroupBufferMessage.message_at >= cutoff,
        )
        .order_by(TelegramGroupBufferMessage.message_at.asc())
        .limit(BUFFER_MAX_MESSAGES)
    )
    return list(result.scalars())


def _catalogue_client_buffer(entries: list[TelegramGroupBufferMessage]) -> dict[str, Any]:
    photos: list[dict] = []
    videos: list[dict] = []
    texts: list[dict] = []
    for entry in entries:
        if entry.sender_role != "client":
            continue
        base = {
            "buffer_id": str(entry.id),
            "message_id": entry.message_id,
            "text": (entry.text or "")[:200],
        }
        if entry.message_type == "photo" and entry.media_file_id:
            photos.append({**base, "ordinal": len(photos) + 1})
        elif entry.message_type == "video" and entry.media_file_id:
            videos.append({**base, "ordinal": len(videos) + 1})
        elif entry.message_type == "text" and (entry.text or "").strip():
            texts.append({**base, "ordinal": len(texts) + 1})
    return {"photos": photos, "videos": videos, "texts": texts}


def _heuristic_parse(instruction: str, catalogue: dict[str, Any]) -> dict[str, Any]:
    lower = instruction.lower()
    photos = catalogue["photos"]
    videos = catalogue["videos"]
    texts = catalogue["texts"]

    photo_ordinals: list[int] = []
    video_ordinals: list[int] = []
    text_ordinal: int | None = None
    use_client_text = any(p in lower for p in (
        "сообщение клиента", "client message", "как описание", "as description",
        "используй текст", "use client", "текст клиента", "пожелан", "учти",
        "client text", "client wish", "как клиент", "клиент попросил", "попросил",
    ))
    run_prepare = any(p in lower for p in ("подготовь", "prepare", "prepare everything"))
    create_requested = should_assemble_from_buffer(instruction)

    ord_map = {
        "перв": 1, "first": 1, "1": 1,
        "втор": 2, "second": 2, "2": 2,
        "трет": 3, "third": 3, "3": 3,
        "четверт": 4, "fourth": 4, "4": 4,
    }
    exclude_second = ("кроме втор" in lower or "except second" in lower
                      or "all except second" in lower or "кроме 2" in lower)

    if "фото" in lower or "photo" in lower:
        if exclude_second and len(photos) > 1:
            photo_ordinals = [i for i in range(1, len(photos) + 1) if i != 2]
        else:
            for key, num in ord_map.items():
                if key in lower and num <= len(photos):
                    if num not in photo_ordinals:
                        photo_ordinals.append(num)
            photo_ordinals.sort()
        if "все фото" in lower or "all photos" in lower:
            photo_ordinals = list(range(1, len(photos) + 1))
            if exclude_second and 2 in photo_ordinals:
                photo_ordinals.remove(2)

    if ("последн" in lower or "last" in lower) and ("видео" in lower or "video" in lower) and videos:
        video_ordinals = [len(videos)]
    elif ("только видео" in lower or "only video" in lower) and videos:
        video_ordinals = [len(videos)]
    elif "видео" in lower and videos and not photo_ordinals:
        video_ordinals = [len(videos)]

    if use_client_text and texts:
        text_ordinal = len(texts)
    elif texts and not photo_ordinals and not video_ordinals and "создай" in lower:
        text_ordinal = len(texts)

    if "текст клиента" in lower or "client text" in lower:
        use_client_text = True
        if texts:
            text_ordinal = len(texts)

    clear = bool(photo_ordinals or video_ordinals)
    if use_client_text and texts:
        clear = True
        if not text_ordinal:
            text_ordinal = len(texts)

    if not create_requested:
        clear = False

    if create_requested and not clear:
        if photos and len(photos) == 1:
            photo_ordinals = [1]
            clear = True
        elif videos and len(videos) == 1:
            video_ordinals = [1]
            clear = True

    if create_requested and texts and text_ordinal is None:
        text_ordinal = len(texts)

    return {
        "clear": clear,
        "create_requested": create_requested,
        "photo_ordinals": photo_ordinals,
        "video_ordinals": video_ordinals,
        "text_ordinal": text_ordinal,
        "use_client_text_as_description": use_client_text,
        "run_prepare": run_prepare,
        "reason": "heuristic",
    }


async def _parse_buffer_instruction(
    instruction: str,
    catalogue: dict[str, Any],
) -> dict[str, Any]:
    if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
        return _heuristic_parse(instruction, catalogue)

    from app.services.ai_service import get_openai, _extract_json, _validate_api_key

    try:
        _validate_api_key()
        openai = get_openai()
        user_block = (
            f"ADMIN INSTRUCTION:\n{instruction}\n\n"
            f"CLIENT PHOTOS:\n{json.dumps(catalogue['photos'], ensure_ascii=False)}\n\n"
            f"CLIENT VIDEOS:\n{json.dumps(catalogue['videos'], ensure_ascii=False)}\n\n"
            f"CLIENT TEXTS:\n{json.dumps(catalogue['texts'], ensure_ascii=False)}"
        )
        response = await openai.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _PARSE_SYSTEM},
                {"role": "user", "content": user_block},
            ],
            temperature=0.1,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(response.choices[0].message.content or "{}")
        if "create_requested" not in parsed:
            parsed["create_requested"] = should_assemble_from_buffer(instruction)
        if not parsed.get("clear"):
            fallback = _heuristic_parse(instruction, catalogue)
            if fallback.get("clear"):
                return fallback
        return parsed
    except Exception as exc:
        logger.warning("[Group Agent] AI parse failed (%s) — heuristic", exc)
        return _heuristic_parse(instruction, catalogue)


def _resolve_selection(
    entries: list[TelegramGroupBufferMessage],
    parsed: dict[str, Any],
) -> tuple[list[TelegramGroupBufferMessage], str | None]:
    catalogue = _catalogue_client_buffer(entries)
    selected: list[TelegramGroupBufferMessage] = []
    entry_by_id = {str(e.id): e for e in entries}

    for ordinal in parsed.get("photo_ordinals") or []:
        for p in catalogue["photos"]:
            if p["ordinal"] == int(ordinal):
                entry = entry_by_id.get(p["buffer_id"])
                if entry and entry not in selected:
                    selected.append(entry)

    for ordinal in parsed.get("video_ordinals") or []:
        for v in catalogue["videos"]:
            if v["ordinal"] == int(ordinal):
                entry = entry_by_id.get(v["buffer_id"])
                if entry and entry not in selected:
                    selected.append(entry)

    source_text: str | None = None
    text_ord = parsed.get("text_ordinal")
    if text_ord:
        for t in catalogue["texts"]:
            if t["ordinal"] == int(text_ord):
                entry = entry_by_id.get(t["buffer_id"])
                if entry and entry.text:
                    source_text = entry.text.strip()
                break

    if parsed.get("use_client_text_as_description") and not source_text:
        client_texts = [e for e in entries if e.sender_role == "client" and e.message_type == "text" and e.text]
        if client_texts:
            source_text = client_texts[-1].text.strip()

    if not source_text:
        for entry in selected:
            if entry.text and entry.sender_role == "client":
                source_text = entry.text.strip()
                break

    return selected, source_text


async def _maybe_generate_captions(
    db: AsyncSession,
    *,
    client: Client,
    item: ContentItem,
    source_text: str | None,
    instruction: str,
    force: bool = False,
) -> ContentItem:
    lower = (instruction or "").lower()
    wants_captions = force or any(k in lower for k in (
        "подпис", "caption", "сгенериру", "generate", "текст пост", "контент",
        "сделай", "сделать", "оформи", "стиль", "премиум", "premium", "luxury",
        "коротк", "как клиент", "попросил", "формальн", "делов",
    )) or any(k in lower for k in ("создай пост", "create post", "создай контент"))
    if not wants_captions:
        return item

    from app.services.ai_service import generate_content
    from app.services.brand_profile import brand_profile_from_client
    from app.services.context_ai_service import build_context_signals
    from app.services.content_service import ContentService
    from app.services.telegram_instruction_service import build_generation_context_hint, extract_admin_instruction

    context_signals = await build_context_signals(
        db, client=client, item=item, source_text=source_text,
    )
    generated = await generate_content(
        company_name=client.company_name,
        business_category=client.business_category,
        content_style=client.content_style,
        source_language=client.source_language or "zh",
        source_text=source_text,
        context_hint=build_generation_context_hint(extract_admin_instruction(item.internal_notes)),
        client_notes=client.notes,
        brand_profile=brand_profile_from_client(client),
        context_signals=context_signals,
    )
    return await ContentService.apply_generated(db, item.id, generated)


async def mark_buffer_entries_linked(
    db: AsyncSession,
    entries: list[TelegramGroupBufferMessage],
    content_id: UUID,
) -> None:
    """Mark buffer rows as used in operator inbox after content creation."""
    for entry in entries:
        entry.inbox_status = "used"
        entry.linked_content_id = content_id
    await db.flush()


async def create_content_from_buffer_selection(
    db: AsyncSession,
    *,
    client: Client,
    group_id: str,
    chat_title: str,
    instruction: str,
    admin_name: str,
    selected: list[TelegramGroupBufferMessage],
    source_text: str | None,
    admin_message_id: int | None,
    run_prepare: bool,
    content_source: str | None = None,
) -> ContentItem:
    if not selected:
        raise ValueError("No media selected")

    client_id = client.id
    resolved_source = content_source or TG_GROUP_BUFFER_SOURCE
    logger.info("[Group Agent] source: %s", resolved_source)

    primary = next((e for e in selected if e.media_file_id), selected[0])
    refs = []
    for i, entry in enumerate(selected):
        refs.append({
            "ordinal": i + 1,
            "message_id": entry.message_id,
            "message_type": entry.message_type,
            "media_file_id": str(entry.media_file_id) if entry.media_file_id else None,
            "text": (entry.text or "")[:200],
        })

    photo_indexes = [
        i + 1 for i, e in enumerate(selected) if e.message_type == "photo"
    ]
    logger.info("[Group Agent] selected photo indexes: %s", photo_indexes)

    internal_notes_parts: list[str] = []
    if source_text:
        internal_notes_parts.append(source_text)
    set_client_source_notes = source_text or ""

    content_item = ContentItem(
        client_id=client_id,
        media_file_id=primary.media_file_id,
        platforms=["instagram"],
        status="draft",
        source=resolved_source,
        internal_notes=internal_notes_parts[0] if internal_notes_parts else None,
        telegram_group_title=chat_title,
        telegram_message_id=admin_message_id or primary.message_id,
        telegram_buffer_refs=json.dumps(refs, ensure_ascii=False),
    )
    try:
        db.add(content_item)
        await db.flush()

        if set_client_source_notes:
            set_client_source(content_item, set_client_source_notes)
        set_admin_instruction(content_item, instruction)
        _append_instruction_history(
            content_item, instruction, "Content created from group buffer", admin_name, status="applied",
        )

        if primary.media_file_id:
            try:
                from app.core.storage import storage as st
                raw = await st.read_file_bytes(primary.storage_path) if primary.storage_path else b""
                ctx = await detect_business_context(
                    client=client,
                    source_text=source_text,
                    internal_notes=content_item.internal_notes,
                    media_file_type="image" if primary.message_type == "photo" else "video",
                    image_bytes=raw if primary.message_type == "photo" and raw else None,
                )
                if float(ctx.get("confidence", 0)) >= 0.5:
                    marker = format_context_marker(ctx)
                    notes = content_item.internal_notes or ""
                    content_item.internal_notes = f"{notes}\n{marker}".strip() if notes else marker
            except Exception as exc:
                logger.warning("[Group Agent] context detection failed: %s", exc)

        from app.services.telegram_ingestion_service import TelegramIngestionService
        primary_media = await db.get(MediaFile, primary.media_file_id) if primary.media_file_id else None
        await TelegramIngestionService.process_after_create(
            db,
            content_item=content_item,
            client=client,
            caption=source_text,
            media_file=primary_media,
            selected_media_count=len(refs),
        )

        await db.commit()
        await db.refresh(content_item)
    except Exception as exc:
        await db.rollback()
        logger.error("[Group Agent] db_error: %s", exc, exc_info=True)
        raise

    logger.info("[Group Agent] created_content_id: %s", content_item.id)
    client.telegram_active_content_id = content_item.id
    await db.commit()
    logger.info("[Group Task Memory] active_content_id: %s", content_item.id)

    content_item = await _maybe_generate_captions(
        db, client=client, item=content_item, source_text=source_text, instruction=instruction,
    )

    logger.info("[Group Agent] assembled content: content_id=%s refs=%d", content_item.id, len(refs))
    logger.info("[Group Agent] created_content_count: 1")

    if run_prepare and content_item.media_file_id:
        from app.services.workflow_service import start_workflow
        await start_workflow(
            content_item.id,
            WorkflowPrepareRequest(source_text=source_text),
        )

    await mark_buffer_entries_linked(db, selected, content_item.id)
    await db.commit()

    return content_item


async def handle_buffer_reply_instruction(
    db: AsyncSession,
    *,
    client: Client,
    group_id: str,
    chat_title: str,
    instruction: str,
    admin_name: str,
    admin_message_id: int | None,
    reply_to_message: dict,
) -> tuple[str, str, ContentItem | None]:
    """
    Bind admin reply to a buffered Telegram message and create a draft.
    Returns (outcome, reply_text, item) where outcome is created | not_found | skip.
    """
    from app.services.telegram_instruction_service import find_content_for_instruction

    existing = await find_content_for_instruction(db, client.id, reply_to_message)
    if existing:
        return "skip", "", None

    if not is_buffer_reply_create_instruction(instruction):
        return "skip", "", None

    task_entries, anchor = await resolve_buffer_task_from_reply(
        db,
        client_id=client.id,
        group_id=group_id,
        reply_to_message=reply_to_message,
    )
    catalogue = _catalogue_client_buffer(task_entries)
    has_materials = bool(catalogue["photos"] or catalogue["videos"] or catalogue["texts"])
    if not has_materials:
        logger.info(
            "[Telegram Buffer] task not found: reply_to=%s anchor=%s",
            reply_to_message.get("message_id"),
            anchor.message_id if anchor else None,
        )
        return "not_found", BUFFER_REPLY_TASK_NOT_FOUND, None

    parsed = await _parse_buffer_instruction(instruction, catalogue)
    parsed = _apply_reply_instruction_defaults(parsed, catalogue, instruction)

    selected, source_text = _resolve_selection(task_entries, parsed)
    if not selected:
        selected = [e for e in task_entries if e.media_file_id]
    if not selected and task_entries:
        selected = [task_entries[-1]]
    if not source_text:
        client_texts = [
            e for e in task_entries
            if e.sender_role == "client" and e.message_type == "text" and (e.text or "").strip()
        ]
        if client_texts:
            source_text = client_texts[-1].text.strip()

    if not selected:
        return "not_found", BUFFER_REPLY_TASK_NOT_FOUND, None

    try:
        item = await create_content_from_buffer_selection(
            db,
            client=client,
            group_id=group_id,
            chat_title=chat_title,
            instruction=instruction,
            admin_name=admin_name,
            selected=selected,
            source_text=source_text,
            admin_message_id=admin_message_id,
            run_prepare=bool(parsed.get("run_prepare")),
        )
        item = await _maybe_generate_captions(
            db,
            client=client,
            item=item,
            source_text=source_text,
            instruction=instruction,
            force=True,
        )
    except Exception as exc:
        await db.rollback()
        logger.error("[Telegram Buffer] draft create failed: %s", exc, exc_info=True)
        return "not_found", "⚠️ Не удалось создать черновик. Попробуйте ещё раз.", None

    logger.info("[Telegram Buffer] draft created: content_id=%s", item.id)
    return "created", buffer_draft_dashboard_reply(item.id), item


async def handle_buffer_admin_instruction(
    db: AsyncSession,
    *,
    client: Client,
    group_id: str,
    chat_id: int,
    chat_title: str,
    instruction: str,
    admin_name: str,
    admin_message_id: int | None,
) -> tuple[bool, str, ContentItem | None]:
    client_id = client.id
    logger.info("[Group Agent] admin_create_requested: true")
    logger.info("[Group Agent] create requested: instruction=%s", instruction[:120])

    entries = await _load_buffer_entries(db, client_id, group_id)
    catalogue = _catalogue_client_buffer(entries)
    if not catalogue["photos"] and not catalogue["videos"] and not catalogue["texts"]:
        return False, "⚠️ В буфере нет материалов от клиента. Попросите клиента отправить фото/видео.", None

    parsed = await _parse_buffer_instruction(instruction, catalogue)
    if not parsed.get("create_requested") and not should_assemble_from_buffer(instruction):
        return False, (
            "📋 Укажите команду создать пост, например: «создай один пост из выбранных материалов»."
        ), None

    if not parsed.get("clear"):
        return False, UNCLEAR_SELECTION_REPLY, None

    selected, source_text = _resolve_selection(entries, parsed)
    if not selected:
        return False, UNCLEAR_SELECTION_REPLY, None

    try:
        item = await create_content_from_buffer_selection(
            db,
            client=client,
            group_id=group_id,
            chat_title=chat_title,
            instruction=instruction,
            admin_name=admin_name,
            selected=selected,
            source_text=source_text,
            admin_message_id=admin_message_id,
            run_prepare=bool(parsed.get("run_prepare")),
        )
    except Exception as exc:
        await db.rollback()
        logger.error("[Group Agent] db_error: %s", exc, exc_info=True)
        return False, "⚠️ Не удалось создать контент. Попробуйте ещё раз.", None

    logger.info("[Group Agent] created_content_id: %s", item.id)
    return True, BUFFER_REPLY_SUCCESS, item
