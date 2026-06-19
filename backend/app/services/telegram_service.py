"""
Telegram Bot Webhook Service
Receives media/text from Telegram, saves to media_storage, creates draft ContentItem.

Flow:
  Telegram user sends photo/video/text
  → webhook receives update
  → find client by telegram_id OR create "Unknown Client"
  → download file from Telegram
  → save to media_storage via StorageService
  → create MediaFile DB record
  → create ContentItem (status=draft, source=telegram)
  → return created item id
"""
import logging
import re
import asyncio
import json

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.storage import storage
from app.models.client import Client
from app.models.content import ContentItem
from app.models.media import MediaFile
from app.services.ocr_service import extract_text, describe_image
from app.services.transcription_service import transcribe_video_detailed
from app.services.subtitle_service import save_subtitle_file
from app.services.subtitle_translation_service import generate_translated_subtitles
from app.services.context_ai_service import detect_business_context, format_context_marker
from app.services.telegram_group_agent_service import (
    ADMIN_ONLY_REPLY,
    BUFFER_WAIT_REPLY,
    buffer_group_message,
    claim_update,
    handle_buffer_admin_instruction,
    handle_buffer_reply_instruction,
    has_selection_intent,
    record_buffer_bot_ack,
    is_admin_operator,
    is_buffer_mode,
    resolve_group_workflow_mode,
    should_assemble_from_buffer,
)
from app.services.telegram_instruction_service import (
    TG_GROUP_BUFFER_SOURCE,
    GROUP_TASK_APPLIED_REPLY,
    GROUP_TASK_NO_ACTIVE_REPLY,
    apply_group_instruction,
    attach_client_text_to_recent,
    find_content_for_instruction,
    find_latest_group_content,
    get_active_group_content,
    is_explicit_new_content_request,
    is_task_edit_instruction,
    resolve_and_apply_instruction,
    is_admin_meta_instruction,
)
from app.services.telegram_ingestion_service import TelegramIngestionService
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

_GROUP_REPLY_OK = "✅ Materials received. Content task created for review."
_GROUP_REPLY_FAIL = "⚠️ Materials received, but processing failed. Admin will review."
_GROUP_REPLY_DISABLED = "⚠️ Telegram ingestion is disabled for this group."

_PHOTO_MIME = "image/jpeg"
VIDEO_MIME = "video/mp4"

_VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm")

# Client text waiting for the next group media upload (key = client_id str)
_pending_client_text: dict[str, str] = {}

_CHAT_IGNORE_EXACT = frozenset({
    "здравствуйте", "здравствуй", "привет", "спасибо", "ok", "ок",
    "понял", "понятно", "hello", "hi", "thanks", "thank you",
    "good morning", "доброе утро", "добрый день", "добрый вечер",
})


def _ensure_video_extension(filename: str) -> str:
    if not any(filename.lower().endswith(ext) for ext in _VIDEO_EXTENSIONS):
        return f"{filename}.mp4"
    return filename


def _is_allowed_sender(telegram_user_id: int) -> bool:
    """
    If TELEGRAM_ADMIN_ID is set, only those IDs may send content.
    Empty string = accept everyone.
    """
    allowed_raw = settings.TELEGRAM_ADMIN_ID.strip()
    if not allowed_raw:
        return True
    allowed = {uid.strip() for uid in allowed_raw.split(",") if uid.strip()}
    return str(telegram_user_id) in allowed


def _is_group_chat(chat: dict) -> bool:
    return chat.get("type") in ("group", "supergroup")


def _detect_update_type(update: dict) -> str:
    for key in (
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "callback_query",
        "my_chat_member",
        "chat_member",
    ):
        if key in update:
            return key
    return "unknown"


def _extract_debug_context(update: dict) -> dict:
    update_type = _detect_update_type(update)
    payload = (
        update.get("message")
        or update.get("edited_message")
        or update.get("channel_post")
        or update.get("edited_channel_post")
        or {}
    )
    if update_type == "callback_query":
        payload = update.get("callback_query", {}).get("message") or {}
    chat = payload.get("chat") or {}
    user = payload.get("from") or {}
    text = payload.get("text") or payload.get("caption") or ""
    if update_type == "callback_query":
        text = update.get("callback_query", {}).get("data") or text
    return {
        "update_type": update_type,
        "chat_id": chat.get("id"),
        "chat_type": chat.get("type"),
        "chat_title": chat.get("title") or chat.get("username") or "",
        "from_id": user.get("id"),
        "text": text,
    }


def log_telegram_debug_update(update: dict) -> None:
    ctx = _extract_debug_context(update)
    logger.info("[Telegram Debug] update_type: %s", ctx["update_type"])
    logger.info("[Telegram Debug] chat_id: %s", ctx["chat_id"])
    logger.info("[Telegram Debug] chat_type: %s", ctx["chat_type"])
    logger.info("[Telegram Debug] chat_title: %s", ctx["chat_title"])
    logger.info("[Telegram Debug] from_id: %s", ctx["from_id"])
    logger.info("[Telegram Debug] text: %s", ctx["text"])


def _is_chat_id_command(message: dict) -> bool:
    text = (message.get("text") or "").strip()
    if not text:
        return False
    base = text.split()[0].split("@")[0]
    return base == "/chat_id"


async def _reply_chat_id_info(chat_id: int | str, chat: dict) -> None:
    chat_type = chat.get("type") or "unknown"
    title = chat.get("title") or chat.get("username") or chat.get("first_name") or "—"
    reply = (
        f"Chat ID: {chat_id}\n"
        f"Chat type: {chat_type}\n"
        f"Title: {title}"
    )
    await _send_telegram_message(chat_id, reply)


async def _send_ingestion_feedback(
    chat_id: int | str,
    *,
    content_item: ContentItem,
    media_count: int,
    caption_detected: bool,
    warnings: list[dict],
    reply_to_message_id: int | None = None,
) -> None:
    dashboard_url = TelegramIngestionService.build_dashboard_url(content_item.id)
    text = TelegramIngestionService.build_feedback_message(
        content_item=content_item,
        media_count=media_count,
        caption_detected=caption_detected,
        warnings=warnings,
        dashboard_url=dashboard_url,
    )
    await _send_telegram_message(chat_id, text, reply_to_message_id=reply_to_message_id)


async def _assemble_album_content(
    db: AsyncSession,
    *,
    client_id,
    group_id: str,
    media_group_id: str,
    chat_id: int | str,
    chat_title: str,
    content_source: str,
) -> dict | None:
    """Assemble buffered album parts into one ContentItem."""
    from uuid import UUID

    parts = await TelegramIngestionService.load_album_parts(db, group_id, media_group_id)
    if not parts:
        return None

    client = await db.get(Client, UUID(str(client_id)))
    if not client:
        return None

    refs = []
    primary_media_id = None
    caption = ""
    for i, part in enumerate(parts):
        if part.caption and not caption:
            caption = part.caption
        refs.append({
            "ordinal": i + 1,
            "message_id": part.message_id,
            "message_type": part.message_type,
            "media_file_id": str(part.media_file_id) if part.media_file_id else None,
            "text": (part.caption or "")[:200],
        })
        if not primary_media_id and part.media_file_id:
            primary_media_id = part.media_file_id

    content_item = ContentItem(
        client_id=client.id,
        media_file_id=primary_media_id,
        platforms=["instagram"],
        status="draft",
        source=content_source,
        internal_notes=caption.strip() or None,
        telegram_group_title=chat_title or None,
        telegram_message_id=parts[0].message_id,
        telegram_buffer_refs=json.dumps(refs, ensure_ascii=False),
        telegram_media_group_id=media_group_id,
    )
    db.add(content_item)
    await db.flush()

    media_file = await db.get(MediaFile, primary_media_id) if primary_media_id else None
    pipeline = await TelegramIngestionService.process_after_create(
        db,
        content_item=content_item,
        client=client,
        caption=caption,
        media_file=media_file,
        selected_media_count=len(refs),
    )
    await TelegramIngestionService.clear_album_parts(db, parts)
    await db.commit()

    await _send_ingestion_feedback(
        chat_id,
        content_item=content_item,
        media_count=len(refs),
        caption_detected=bool(caption.strip()),
        warnings=pipeline.get("warnings") or [],
        reply_to_message_id=parts[-1].message_id,
    )
    return {
        "content_id": str(content_item.id),
        "album": True,
        "media_count": len(refs),
        "status": content_item.status,
    }


def _schedule_album_assembly(
    *,
    client_id,
    group_id: str,
    media_group_id: str,
    chat_id: int | str,
    chat_title: str,
    content_source: str,
) -> None:
    async def _run() -> None:
        try:
            await asyncio.sleep(2.0)
            async with AsyncSessionLocal() as db:
                await _assemble_album_content(
                    db,
                    client_id=client_id,
                    group_id=group_id,
                    media_group_id=media_group_id,
                    chat_id=chat_id,
                    chat_title=chat_title,
                    content_source=content_source,
                )
        except Exception as exc:
            logger.error("[Telegram Album] assembly error: %s", exc, exc_info=True)

    asyncio.create_task(_run())


async def _send_telegram_message(
    chat_id: int | str,
    text: str,
    *,
    reply_to_message_id: int | None = None,
) -> int | None:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or not chat_id:
        return None
    payload: dict = {"chat_id": chat_id, "text": text}
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
            result = body.get("result") or {}
            return result.get("message_id")
    except Exception as exc:
        logger.warning("Telegram: failed to send group reply to %s — %s", chat_id, exc)
    return None


async def _get_file_bytes(file_id: str) -> tuple[bytes, str]:
    """Download a file from Telegram by file_id. Returns (bytes, filename).
    Raises ValueError with a clear message if Telegram cannot serve the file
    (e.g. file > 20 MB — Telegram Bot API limit).
    """
    token = settings.TELEGRAM_BOT_TOKEN
    async with httpx.AsyncClient(timeout=300.0) as client:  # 300s for large video downloads
        logger.info("[Telegram Video] getFile request | file_id: %s", file_id)
        resp = await client.get(f"{TELEGRAM_API}/bot{token}/getFile?file_id={file_id}")
        resp.raise_for_status()
        body = resp.json()
        logger.info("[Telegram Video] getFile result: %s", body)

        if not body.get("ok"):
            logger.error(
                "[Telegram Video] getFile failure: %s",
                body.get("description", "unknown"),
            )
            raise ValueError(f"Telegram getFile failed for file_id={file_id}")

        result = body.get("result") or {}
        file_size = result.get("file_size", 0)
        file_path = result.get("file_path")

        logger.info("[Telegram Video] file_size: %s bytes", file_size if file_size else "unknown")

        if not file_path:
            logger.error(
                "[Telegram Video] failure: file_path missing — file_id=%s file_size=%s",
                file_id, file_size,
            )
            raise ValueError(
                f"Telegram cannot serve file_id={file_id} (size={file_size} bytes). "
                "Files >20 MB cannot be downloaded via Bot API."
            )

        logger.info("[Telegram Video] file_path: %s", file_path)
        filename = file_path.split("/")[-1]

        try:
            dl = await client.get(f"{TELEGRAM_API}/file/bot{token}/{file_path}")
            dl.raise_for_status()
        except Exception as exc:
            logger.error(
                "[Telegram Video] download failure: file_path=%s error=%s",
                file_path, exc, exc_info=True,
            )
            raise

        logger.info(
            "[Telegram Video] download success: %d bytes, filename=%s",
            len(dl.content), filename,
        )
        return dl.content, filename


async def _find_or_create_client(db: AsyncSession, telegram_user_id: int, sender_name: str) -> Client:
    """
    Look up client by telegram_id.
    If not found, create a placeholder "Unknown Client (tg:<id>)".
    """
    tg_id_str = str(telegram_user_id)
    result = await db.execute(
        select(Client).where(Client.telegram_id == tg_id_str)
    )
    client = result.scalar_one_or_none()
    if client:
        logger.info("Telegram: matched sender %s to client '%s'", tg_id_str, client.company_name)
        return client

    # Create placeholder client
    company = f"{sender_name} (Telegram)" if sender_name else f"Unknown Client (tg:{tg_id_str})"
    client = Client(
        company_name=company,
        source_language="zh",
        business_category="other",
        content_style="casual",
        status="active",
        notes=f"Auto-created from Telegram sender ID {tg_id_str}. Link to a real client in Settings.",
        telegram_id=tg_id_str,
    )
    db.add(client)
    await db.flush()  # get the id without committing
    logger.info("Telegram: created placeholder client '%s' for sender %s", company, tg_id_str)
    return client


async def _find_or_create_client_for_group(
    db: AsyncSession,
    chat_id: int,
    chat_title: str,
) -> Client:
    """Match client by telegram_group_id (multiple id formats) or create a temporary group client."""
    title = (chat_title or f"Group {chat_id}").strip()
    group_variants = _group_id_variants(chat_id)

    for group_id in group_variants:
        result = await db.execute(
            select(Client).where(Client.telegram_group_id == group_id)
        )
        client = result.scalar_one_or_none()
        if client:
            if title and client.telegram_group_title != title:
                client.telegram_group_title = title
            await db.flush()
            logger.info(
                "Telegram Group: matched chat.id=%s (stored=%s) to client '%s' mode=%s",
                chat_id,
                group_id,
                client.company_name,
                getattr(client, "telegram_workflow_mode", "auto_create_from_media"),
            )
            return client

    group_id = str(chat_id)
    company = f"Telegram Group: {title}"
    client = Client(
        company_name=company,
        source_language="zh",
        business_category="other",
        content_style="casual",
        status="active",
        notes=(
            f"Auto-created from Telegram group chat.id={group_id}. "
            "Link to a real client or set brand profile in the dashboard."
        ),
        telegram_group_id=group_id,
        telegram_group_title=title,
        telegram_workflow_mode="admin_controlled_buffer",
    )
    db.add(client)
    await db.flush()
    logger.info(
        "Telegram Group: created placeholder client '%s' for chat.id=%s",
        company,
        group_id,
    )
    return client


def _group_id_variants(chat_id: int) -> list[str]:
    """Match group id stored in UI with or without -100 prefix."""
    primary = str(chat_id)
    variants = [primary]
    if primary.startswith("-100"):
        rest = primary[4:]
        if rest:
            variants.append(rest)
            variants.append(f"-{rest}")
    elif primary.startswith("-"):
        variants.append(primary.lstrip("-"))
    else:
        variants.append(f"-{primary}")
        variants.append(f"-100{primary}")
    return list(dict.fromkeys(variants))


def _group_role(telegram_user_id: int, message: dict, *, buffer_mode: bool = False) -> str:
    """admin = operator; client = everyone else."""
    if buffer_mode:
        role = "admin" if is_admin_operator(telegram_user_id) else "client"
        logger.info("[Group Agent] sender_role: %s", role)
        logger.info("[Group Agent] admin_only: true")
        return role

    text = _message_text(message)
    allowed_raw = settings.TELEGRAM_ADMIN_ID.strip()
    if not allowed_raw:
        if _has_bot_mention(message, text):
            return "admin"
        return "client"
    return "admin" if _is_allowed_sender(telegram_user_id) else "client"


def _is_client_content_request(text: str) -> bool:
    lower = (text or "").lower()
    return any(p in lower for p in (
        "сделайте пост", "сделай пост", "опублик", "publish", "скидк", "discount",
        "завтра", "tomorrow", "нужен пост", "create post",
    ))


def _log_group_intent(
    role: str,
    intent_type: str,
    action: str,
    target_content_id: str | None = None,
) -> None:
    logger.info("[Telegram Group Intent] role: %s", role)
    logger.info("[Telegram Group Intent] type: %s", intent_type)
    logger.info("[Telegram Group Intent] action: %s", action)
    logger.info("[Telegram Group Intent] target_content_id: %s", target_content_id or "none")


def _is_ignorable_chat(text: str) -> bool:
    lower = re.sub(r"\s+", " ", (text or "").lower().strip())
    if not lower:
        return True
    if lower in _CHAT_IGNORE_EXACT:
        return True
    return bool(re.match(
        r"^(здравствуйте|здравствуй|привет|спасибо|ok|ок|понял|понятно|hello|hi)\b",
        lower,
    )) and len(lower) < 80


def _message_text(message: dict) -> str:
    return (message.get("text") or message.get("caption") or "").strip()


def _has_bot_mention(message: dict, text: str) -> bool:
    entities = message.get("entities") or []
    for ent in entities:
        if ent.get("type") in ("mention", "bot_command"):
            return True
    return text.startswith("@")


def _strip_bot_mention(message: dict, text: str) -> str:
    entities = message.get("entities") or []
    for ent in entities:
        if ent.get("type") == "mention" and ent.get("offset", 0) == 0:
            return text[ent["offset"] + ent["length"]:].strip()
    if text.startswith("@"):
        parts = text.split(" ", 1)
        return parts[1].strip() if len(parts) > 1 else ""
    return text


async def _create_content_from_telegram_message(
    db: AsyncSession,
    message: dict,
    client: Client,
    *,
    content_source: str,
    chat_title: str,
    is_group: bool,
    pending_client_text: str | None = None,
) -> dict:
    """Download media (if any), build notes, create ContentItem. Used by group + private."""
    if is_group and resolve_group_workflow_mode(client) == "admin_controlled_buffer":
        logger.info("[Group Agent] skipped_content_creation: blocked (_create_content_from_telegram_message)")
        logger.info("[Group Agent] created_content_count: 0")
        raise RuntimeError("admin_controlled_buffer blocks immediate ContentItem creation")

    caption: str = message.get("caption", "") or message.get("text", "") or ""
    photo_list = message.get("photo")
    video = message.get("video")
    video_note = message.get("video_note")
    document = message.get("document")

    media_record: MediaFile | None = None
    ocr_text: str = ""
    raw: bytes = b""
    transcript: str = ""

    if photo_list or video or video_note or document:
        try:
            if photo_list:
                file_id = photo_list[-1]["file_id"]
                mime = _PHOTO_MIME
                folder = f"clients/{client.id}/telegram"
                raw, fname = await _get_file_bytes(file_id)
                fname = fname if fname.endswith((".jpg", ".jpeg")) else f"{fname}.jpg"
                file_type = "image"
            elif video:
                file_id = video["file_id"]
                mime = video.get("mime_type") or VIDEO_MIME
                folder = f"clients/{client.id}/telegram"
                raw, fname = await _get_file_bytes(file_id)
                fname = _ensure_video_extension(fname)
                file_type = "video"
            elif video_note:
                file_id = video_note["file_id"]
                mime = VIDEO_MIME
                folder = f"clients/{client.id}/telegram"
                raw, fname = await _get_file_bytes(file_id)
                fname = _ensure_video_extension(fname)
                file_type = "video"
            else:
                file_id = document["file_id"]
                mime = document.get("mime_type", "application/octet-stream")
                folder = f"clients/{client.id}/telegram"
                file_type = "image" if mime.startswith("image/") else "video"
                raw, fname = await _get_file_bytes(file_id)
                fname = document.get("file_name", fname)
                if file_type == "video":
                    fname = _ensure_video_extension(fname)

            if not raw:
                raise ValueError(f"Empty download for file_id {file_id}")

            storage_key = await storage.save_file(raw, fname, folder)
            media_record = MediaFile(
                client_id=client.id,
                original_filename=fname,
                file_type=file_type,
                mime_type=mime,
                storage_path=storage_key,
                thumbnail_path=None,
                file_size=len(raw),
            )
            db.add(media_record)
            await db.flush()

            if file_type == "image":
                ocr_text = await extract_text(raw)

        except Exception as exc:
            exc_str = str(exc)
            logger.error("[Telegram] failed to download/save media — %s", exc_str, exc_info=True)
            if "20 MB" in exc_str or "cannot serve" in exc_str:
                caption = f"[Video too large for Telegram Bot API (>20MB)]\n{caption}".strip()
            if is_group:
                raise

    if not caption.strip() and media_record and media_record.file_type == "image":
        try:
            ai_description = await describe_image(raw, business_category=client.business_category)
            if ai_description:
                caption = ai_description
        except Exception as exc:
            logger.warning("Telegram: describe_image failed (%s)", exc)

    if media_record and media_record.file_type == "video" and raw:
        try:
            tx = await transcribe_video_detailed(raw)
            transcript = tx.source_text
            if tx.segments and media_record:
                sub_key = await save_subtitle_file(media_record.storage_path, tx.segments)
                if sub_key:
                    await generate_translated_subtitles(media_record.storage_path, tx.segments)
        except Exception as exc:
            logger.warning("Telegram: transcription error (%s)", exc)

    notes_parts: list[str] = []
    if pending_client_text and pending_client_text.strip():
        notes_parts.append(pending_client_text.strip())
    if caption.strip() and not is_admin_meta_instruction(caption):
        notes_parts.append(caption.strip())
    if ocr_text.strip():
        notes_parts.append(f"[OCR]: {ocr_text.strip()}" if notes_parts else ocr_text.strip())
    if transcript.strip():
        notes_parts.append(f"[Transcript]: {transcript.strip()}")
    internal_notes = "\n".join(notes_parts) if notes_parts else None

    image_description = caption.strip() if caption.strip().startswith("Detected:") else ""
    try:
        ctx = await detect_business_context(
            client=client,
            source_text=caption.strip() or pending_client_text or None,
            internal_notes=internal_notes,
            image_description=image_description or None,
            media_file_type=media_record.file_type if media_record else None,
            image_bytes=raw if media_record and media_record.file_type == "image" and raw else None,
        )
        if float(ctx.get("confidence", 0)) >= 0.5:
            marker = format_context_marker(ctx)
            internal_notes = f"{internal_notes}\n{marker}".strip() if internal_notes else marker
    except Exception as exc:
        logger.warning("[Context AI] telegram ingest failed: %s", exc)

    message_id = message.get("message_id")
    media_group_id = message.get("media_group_id")

    if media_group_id and is_group and media_record:
        group_id = str(message.get("chat", {}).get("id", ""))
        msg_type = "photo" if photo_list else "video" if (video or video_note) else "document"
        queued = await TelegramIngestionService.queue_album_part(
            db,
            client=client,
            group_id=group_id,
            media_group_id=str(media_group_id),
            message_id=int(message_id),
            media_file_id=media_record.id,
            caption=caption.strip() or None,
            message_type=msg_type,
        )
        await db.commit()
        if queued:
            _schedule_album_assembly(
                client_id=client.id,
                group_id=group_id,
                media_group_id=str(media_group_id),
                chat_id=group_id,
                chat_title=chat_title,
                content_source=content_source,
            )
        return {
            "album_pending": True,
            "media_group_id": str(media_group_id),
            "client_id": str(client.id),
            "is_group": True,
            "processing_ok": True,
        }

    if message_id is not None or media_record:
        dup = await TelegramIngestionService.find_duplicate_content(
            db,
            client.id,
            int(message_id) if message_id is not None else None,
            media_record.id if media_record else None,
        )
        if dup:
            logger.info("[Telegram] duplicate content skipped: %s", dup.id)
            return {
                "duplicate": True,
                "content_id": str(dup.id),
                "client_id": str(client.id),
                "is_group": is_group,
                "processing_ok": True,
            }

    content_item = ContentItem(
        client_id=client.id,
        media_file_id=media_record.id if media_record else None,
        platforms=["instagram"],
        status="draft",
        source=content_source,
        internal_notes=internal_notes,
        telegram_group_title=chat_title if is_group else None,
        telegram_message_id=message_id,
    )
    db.add(content_item)
    await db.flush()

    pipeline = await TelegramIngestionService.process_after_create(
        db,
        content_item=content_item,
        client=client,
        caption=caption,
        media_file=media_record,
        message=message,
        selected_media_count=1,
    )
    await db.commit()

    return {
        "content_id": str(content_item.id),
        "client_id": str(client.id),
        "client_name": client.company_name,
        "source": content_source,
        "has_media": bool(media_record),
        "caption": caption[:100] if caption else None,
        "processing_ok": True,
        "is_group": is_group,
        "status": content_item.status,
        "classification": pipeline.get("classification"),
        "warnings": pipeline.get("warnings") or [],
        "content_item": content_item,
    }


async def _handle_group_admin_instruction(
    db: AsyncSession,
    message: dict,
    chat_id: int,
    chat_title: str,
    telegram_user_id: int,
    sender_name: str,
    text: str,
    client: Client | None = None,
) -> dict:
    if client is None:
        client = await _find_or_create_client_for_group(db, chat_id, chat_title)
    client_id_str = str(client.id)
    instruction = _strip_bot_mention(message, text) or text
    admin_name = sender_name or str(telegram_user_id)
    buffer_enabled = is_buffer_mode(client)

    if buffer_enabled:
        if not is_admin_operator(telegram_user_id):
            if _has_bot_mention(message, text):
                await _send_telegram_message(chat_id, ADMIN_ONLY_REPLY)
            return {
                "instruction": False,
                "forbidden": True,
                "is_group": True,
            }

        reply_to = message.get("reply_to_message")
        if reply_to:
            outcome, reply, item = await handle_buffer_reply_instruction(
                db,
                client=client,
                group_id=str(chat_id),
                chat_title=chat_title,
                instruction=instruction,
                admin_name=admin_name,
                admin_message_id=message.get("message_id"),
                reply_to_message=reply_to,
            )
            if outcome in ("created", "not_found"):
                await _send_telegram_message(chat_id, reply)
                return {
                    "buffer_agent": True,
                    "buffer_reply": True,
                    "created": outcome == "created",
                    "reply": reply,
                    "client_id": client_id_str,
                    "is_group": True,
                    "content_id": str(item.id) if item else None,
                }

        explicit_new = is_explicit_new_content_request(instruction)
        active = await get_active_group_content(db, client)
        wants_create = should_assemble_from_buffer(instruction)

        if explicit_new or (wants_create and not active):
            ok, reply, item = await handle_buffer_admin_instruction(
                db,
                client=client,
                group_id=str(chat_id),
                chat_id=chat_id,
                chat_title=chat_title,
                instruction=instruction,
                admin_name=admin_name,
                admin_message_id=message.get("message_id"),
            )
            await _send_telegram_message(chat_id, reply)
            return {
                "buffer_agent": True,
                "created": ok,
                "reply": reply,
                "client_id": client_id_str,
                "is_group": True,
                "content_id": str(item.id) if item else None,
            }

        if wants_create and active and not explicit_new:
            logger.info("[Group Task Memory] action: apply_to_active (skipped_new_create)")
            target = active
        elif has_selection_intent(instruction) and not active and not is_task_edit_instruction(instruction):
            await _send_telegram_message(
                chat_id,
                "📋 Выбор понятен. Добавьте «создай пост» или «создай контент» для сборки.",
            )
            return {"selection_only": True, "is_group": True}
        else:
            target = active
            if message.get("reply_to_message"):
                replied = await find_content_for_instruction(
                    db, client.id, message.get("reply_to_message"),
                )
                if replied and replied.source in (TG_GROUP_BUFFER_SOURCE, "telegram_group"):
                    if replied.status in ("draft", "ready", "ready_for_approval"):
                        target = replied

        if not target:
            await _send_telegram_message(chat_id, GROUP_TASK_NO_ACTIVE_REPLY)
            return {"instruction": False, "no_content": True, "is_group": True}

        target_id = str(target.id)
        logger.info("[Group Task Memory] active_content_id: %s", target_id)
        logger.info("[Group Task Memory] action: apply_instruction")
        _log_group_intent("admin", "ADMIN_INSTRUCTION", "apply_instruction", target_id)
        try:
            await apply_group_instruction(
                db,
                client=client,
                content_item=target,
                instruction=instruction,
                admin_name=admin_name,
                reply_to_message=message.get("reply_to_message"),
            )
            found = True
            reply_text = GROUP_TASK_APPLIED_REPLY
            logger.info("[Group Task Memory] instruction_applied: true")
        except Exception as exc:
            logger.error("[Telegram Instruction] buffer edit failed: %s", exc, exc_info=True)
            found = False
            reply_text = "⚠️ Не удалось применить инструкцию. Попробуйте ещё раз или откройте сайт."
        await _send_telegram_message(chat_id, reply_text)
        return {
            "instruction": True,
            "applied": found,
            "reply": reply_text,
            "client_id": client_id_str,
            "is_group": True,
            "content_id": target_id,
        }

    target = await find_latest_group_content(db, client.id, within_minutes=30)
    if message.get("reply_to_message"):
        target = await find_content_for_instruction(db, client.id, message.get("reply_to_message"))
    target_id = str(target.id) if target else None

    _log_group_intent("admin", "ADMIN_INSTRUCTION", "apply_instruction", target_id)

    found, reply_text = await resolve_and_apply_instruction(
        db,
        client=client,
        instruction=instruction,
        admin_name=admin_name,
        reply_to_message=message.get("reply_to_message"),
    )
    if found:
        await _send_telegram_message(chat_id, "✅ Инструкция применена.")
    else:
        await _send_telegram_message(chat_id, reply_text)

    return {
        "instruction": True,
        "applied": found,
        "reply": reply_text,
        "client_id": client_id_str,
        "is_group": True,
        "content_id": target_id,
    }


async def _process_group_message_buffer_only(
    db: AsyncSession,
    message: dict,
    chat_id: int,
    chat_title: str,
    telegram_user_id: int,
    sender_name: str,
    client: Client,
) -> dict:
    """admin_controlled_buffer — buffer ingest only; never create ContentItem here."""
    role = _group_role(telegram_user_id, message, buffer_mode=True)
    text = _message_text(message)
    has_media = bool(
        message.get("photo") or message.get("video")
        or message.get("video_note") or message.get("document")
    )
    has_bot_mention = _has_bot_mention(message, text)
    is_reply = bool(message.get("reply_to_message"))

    logger.info("[Group Agent] skipped_content_creation: true")
    logger.info("[Group Agent] created_content_count: 0")
    logger.info("[Group Agent] waiting_for_admin: true")

    if not has_media and text and _is_ignorable_chat(text):
        _log_group_intent(role, "CHAT_MESSAGE", "ignore")
        return {"ignored": True, "is_group": True, "buffer_mode": True}

    if role != "admin" and has_bot_mention and not has_media:
        await _send_telegram_message(chat_id, ADMIN_ONLY_REPLY)
        return {"forbidden": True, "is_group": True, "buffer_mode": True}

    buffered_entry = await buffer_group_message(
        db,
        client=client,
        group_id=str(chat_id),
        message=message,
        sender_role=role,
        sender_id=str(telegram_user_id),
    )
    await db.commit()

    account_manager_replied = False
    if role == "client" and buffered_entry:
        from app.services.media_request_service import MediaRequestService
        from app.services.account_manager_service import AccountManagerService
        from app.services.operator_auto_draft_service import OperatorAutoDraftService

        try:
            fulfilled = await MediaRequestService.try_fulfill_from_buffer(
                db, buffered_entry, client,
            )
            am_result = await AccountManagerService.process_client_message(
                db,
                entry=buffered_entry,
                client=client,
                chat_id=chat_id,
                message=message,
                has_media=has_media,
                media_request_fulfilled=fulfilled,
            )
            account_manager_replied = bool(am_result.get("reply_sent"))

            if not fulfilled and am_result.get("should_auto_draft"):
                await OperatorAutoDraftService.try_auto_draft(db, buffered_entry, client)

            await db.refresh(buffered_entry)
            if not am_result.get("skipped"):
                from app.services.operator_task_service import OperatorTaskService
                await OperatorTaskService.upsert_from_telegram_inbox(
                    db, buffered_entry, client,
                )

            await db.commit()
        except Exception as exc:
            logger.warning(
                "[Account Manager] buffer hook error: inbox=%s %s",
                buffered_entry.id,
                exc,
                exc_info=True,
            )
            await db.rollback()

    if role == "admin" and not has_media and (has_bot_mention or is_reply):
        return await _handle_group_admin_instruction(
            db, message, chat_id, chat_title, telegram_user_id, sender_name, text, client=client,
        )

    if role == "admin" and not has_media:
        _log_group_intent(role, "CHAT_MESSAGE", "ignore")
        return {"ignored": True, "is_group": True, "buffer_mode": True}

    client_msg_id = message.get("message_id")
    if not account_manager_replied:
        bot_msg_id = await _send_telegram_message(
            chat_id,
            BUFFER_WAIT_REPLY,
            reply_to_message_id=int(client_msg_id) if client_msg_id is not None else None,
        )
        if bot_msg_id is not None and client_msg_id is not None:
            await record_buffer_bot_ack(
                db,
                client=client,
                group_id=str(chat_id),
                bot_message_id=int(bot_msg_id),
                reply_anchor_message_id=int(client_msg_id),
            )
            await db.commit()
    _log_group_intent(role, "CLIENT_CONTENT", "buffer")
    return {"buffered": True, "is_group": True, "buffer_mode": True}


async def _process_group_message_auto(
    db: AsyncSession,
    message: dict,
    chat_id: int,
    chat_title: str,
    telegram_user_id: int,
    sender_name: str,
    client: Client,
) -> dict:
    """auto_create_from_media — legacy group behavior."""
    role = _group_role(telegram_user_id, message, buffer_mode=False)
    text = _message_text(message)
    has_media = bool(
        message.get("photo") or message.get("video")
        or message.get("video_note") or message.get("document")
    )
    has_bot_mention = _has_bot_mention(message, text)
    is_reply = bool(message.get("reply_to_message"))

    if not has_media and text and _is_ignorable_chat(text):
        _log_group_intent(role, "CHAT_MESSAGE", "ignore")
        return {"ignored": True, "is_group": True}

    if role == "admin" and not has_media and (has_bot_mention or is_reply):
        return await _handle_group_admin_instruction(
            db, message, chat_id, chat_title, telegram_user_id, sender_name, text, client=client,
        )

    if role == "admin" and not has_media:
        _log_group_intent(role, "CHAT_MESSAGE", "ignore")
        return {"ignored": True, "is_group": True}

    if has_media:
        pending = _pending_client_text.pop(str(client.id), None)
        try:
            result = await _create_content_from_telegram_message(
                db,
                message,
                client,
                content_source="telegram_group",
                chat_title=chat_title,
                is_group=True,
                pending_client_text=pending,
            )
        except Exception as exc:
            await db.rollback()
            logger.error("Telegram group media failed: %s", exc, exc_info=True)
            await _send_telegram_message(chat_id, _GROUP_REPLY_FAIL)
            return {"processing_ok": False, "is_group": True, "error": str(exc)[:200]}

        if result.get("album_pending"):
            _log_group_intent(role, "CLIENT_CONTENT", "album_buffer", result.get("media_group_id"))
            return result

        if result.get("duplicate"):
            await _send_telegram_message(
                chat_id,
                "Content already received ✅\nDuplicate skipped.",
                reply_to_message_id=message.get("message_id"),
            )
            return result

        _log_group_intent(role, "CLIENT_CONTENT", "create_content", result.get("content_id"))
        content_item = result.pop("content_item", None)
        if content_item:
            media_count = len(json.loads(content_item.telegram_buffer_refs)) if content_item.telegram_buffer_refs else (1 if result.get("has_media") else 0)
            await _send_ingestion_feedback(
                chat_id,
                content_item=content_item,
                media_count=max(media_count, 1 if result.get("has_media") else 0),
                caption_detected=bool(result.get("caption")),
                warnings=result.get("warnings") or [],
                reply_to_message_id=message.get("message_id"),
            )
        else:
            await _send_telegram_message(chat_id, _GROUP_REPLY_OK)
        return result

    if role == "client" and text and not _is_ignorable_chat(text):
        try:
            result = await _create_content_from_telegram_message(
                db,
                message,
                client,
                content_source="telegram_group",
                chat_title=chat_title,
                is_group=True,
            )
            if result.get("duplicate"):
                return result
            content_item = result.pop("content_item", None)
            if content_item:
                await _send_ingestion_feedback(
                    chat_id,
                    content_item=content_item,
                    media_count=0,
                    caption_detected=True,
                    warnings=result.get("warnings") or [],
                    reply_to_message_id=message.get("message_id"),
                )
            _log_group_intent(role, "CLIENT_CONTENT", "create_text_content", result.get("content_id"))
            return result
        except Exception as exc:
            logger.warning("Telegram group text-only create failed: %s", exc)
            attached = await attach_client_text_to_recent(db, client.id, text, within_minutes=10)
            if attached:
                _log_group_intent(role, "CLIENT_CONTENT", "attach_client_text", str(attached.id))
            else:
                _pending_client_text[str(client.id)] = text
                _log_group_intent(role, "CLIENT_CONTENT", "store_pending")
            return {"pending_client_text": True, "is_group": True}

    _log_group_intent(role, "CHAT_MESSAGE", "ignore")
    return {"ignored": True, "is_group": True}


async def _process_group_message(
    db: AsyncSession,
    message: dict,
    chat_id: int,
    chat_title: str,
    telegram_user_id: int,
    sender_name: str,
) -> dict | None:
    """Group/supergroup ingestion — route by workflow_mode before any ContentItem creation."""
    settings_row = await TelegramIngestionService.get_settings(db)
    if not TelegramIngestionService.is_ingestion_enabled(settings_row):
        logger.info("[Telegram] ingestion disabled — skipping group message")
        return {"ignored": True, "ingestion_disabled": True, "is_group": True}

    if not TelegramIngestionService.is_group_allowed(chat_id, settings_row):
        logger.warning("[Telegram] group %s not in allowed list", chat_id)
        await _send_telegram_message(chat_id, _GROUP_REPLY_DISABLED)
        return {"forbidden": True, "group_not_allowed": True, "is_group": True}

    client = await _find_or_create_client_for_group(db, chat_id, chat_title)
    await TelegramIngestionService.apply_tenant_to_client(db, client, settings_row)
    await db.commit()

    try:
        from app.services.communication_service import CommunicationHubService
        await CommunicationHubService.store_telegram_group_message(
            db,
            client=client,
            chat_id=chat_id,
            chat_title=chat_title,
            message=message,
            sender_name=sender_name,
            telegram_user_id=telegram_user_id,
        )
    except Exception as exc:
        logger.debug("Communication Hub telegram copy skipped: %s", exc)

    workflow_mode = resolve_group_workflow_mode(client)
    logger.info("[Group Agent] workflow_mode: %s", workflow_mode)
    logger.info("[Group Agent] buffering_only: %s", workflow_mode == "admin_controlled_buffer")

    if workflow_mode == "admin_controlled_buffer":
        return await _process_group_message_buffer_only(
            db, message, chat_id, chat_title, telegram_user_id, sender_name, client,
        )

    return await _process_group_message_auto(
        db, message, chat_id, chat_title, telegram_user_id, sender_name, client,
    )


async def process_update(db: AsyncSession, update: dict) -> dict | None:
    """
    Main entry point. Receives a raw Telegram update dict, processes it,
    returns a summary dict or None if ignored.
    """
    update_id = update.get("update_id")
    if not await claim_update(db, update_id):
        return {"duplicate": True, "update_id": update_id}
    await db.commit()

    if "callback_query" in update:
        from app.services.client_review_telegram_service import ClientReviewTelegramService
        try:
            result = await ClientReviewTelegramService.handle_callback(
                db, update["callback_query"],
            )
            await db.commit()
            return result or {"callback_handled": True}
        except Exception as exc:
            await db.rollback()
            logger.error("Telegram: callback_query failed — %s", exc, exc_info=True)
            return {"callback_error": str(exc)[:200]}

    message = update.get("message") or update.get("channel_post")
    if not message:
        logger.debug("Telegram: update has no message — skipping")
        return None

    chat = message.get("chat", {})
    chat_id = chat.get("id", 0)
    user = message.get("from") or {}
    telegram_user_id: int = user.get("id") or chat_id
    feedback_text = (message.get("text") or message.get("caption") or "").strip()
    has_media = bool(
        message.get("photo") or message.get("video") or message.get("document"),
    )

    if feedback_text and not has_media:
        from app.services.client_review_telegram_service import (
            ClientReviewTelegramService,
            has_pending_feedback,
        )
        if has_pending_feedback(telegram_user_id):
            try:
                result = await ClientReviewTelegramService.handle_feedback_message(
                    db,
                    telegram_user_id,
                    feedback_text,
                    reply_chat_id=chat_id,
                )
                await db.commit()
                if result:
                    return {"client_review_feedback": True, **result}
            except Exception as exc:
                await db.rollback()
                logger.error("Telegram: client feedback failed — %s", exc, exc_info=True)

    if _is_chat_id_command(message):
        await _reply_chat_id_info(chat_id, chat)
        return {"chat_id_command": True, "chat_id": chat_id}

    chat_title: str = (chat.get("title") or "").strip()
    is_group = _is_group_chat(chat)
    sender_first = user.get("first_name", "") or chat_title
    sender_last = user.get("last_name", "")
    sender_name = f"{sender_first} {sender_last}".strip()

    if is_group:
        logger.info(
            "[Telegram Group] chat.id=%s chat.title=%r sender=%s",
            chat_id,
            chat_title,
            sender_name or telegram_user_id,
        )
        return await _process_group_message(
            db, message, chat_id, chat_title, telegram_user_id, sender_name,
        )

    if not _is_allowed_sender(telegram_user_id):
        logger.warning(
            "Telegram: rejected message from unauthorized sender %s", telegram_user_id
        )
        return None

    caption: str = message.get("caption", "") or message.get("text", "") or ""
    has_media = bool(
        message.get("photo") or message.get("video")
        or message.get("video_note") or message.get("document")
    )
    if not has_media and not caption.strip():
        logger.debug("Telegram: empty message (no media, no text) — skipping")
        return None

    logger.info(
        "Telegram: received private message from %s (id=%s) — media=%s text=%s",
        sender_name, telegram_user_id, has_media, bool(caption),
    )

    try:
        client = await _find_or_create_client(db, telegram_user_id, sender_name)
        settings_row = await TelegramIngestionService.get_settings(db)
        if not TelegramIngestionService.is_ingestion_enabled(settings_row):
            return {"ignored": True, "ingestion_disabled": True}
        await TelegramIngestionService.apply_tenant_to_client(db, client, settings_row)
        result = await _create_content_from_telegram_message(
            db,
            message,
            client,
            content_source="telegram",
            chat_title="",
            is_group=False,
        )
        result.pop("content_item", None)
        return result
    except Exception as exc:
        await db.rollback()
        logger.error("Telegram: processing failed — %s", exc, exc_info=True)
        return {
            "processing_ok": False,
            "is_group": False,
            "error": str(exc)[:200],
        }
