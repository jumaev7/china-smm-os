"""Telegram client review preview — send after admin approve, handle inline buttons."""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.storage import storage
from app.models.client import Client
from app.models.content import ContentItem
from app.models.media import MediaFile
from app.services.content_review_service import INTAKE_GROUP_NOT_LINKED, _review_url
from app.services.content_service import ContentService

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

_PLATFORM_BADGES = {
    "instagram": "📸 Instagram",
    "facebook": "👥 Facebook",
    "tiktok": "🎵 TikTok",
    "telegram": "✈️ Telegram",
    "linkedin": "💼 LinkedIn",
}

# telegram_user_id -> content_id awaiting feedback text
_pending_feedback: dict[str, str] = {}


def register_pending_feedback(telegram_user_id: int | str, content_id: UUID) -> None:
    _pending_feedback[str(telegram_user_id)] = str(content_id)


def pop_pending_feedback(telegram_user_id: int | str) -> str | None:
    return _pending_feedback.pop(str(telegram_user_id), None)


def has_pending_feedback(telegram_user_id: int | str) -> bool:
    return str(telegram_user_id) in _pending_feedback


def _parse_callback_data(data: str) -> tuple[str, str] | None:
    """Return (action, token) for cr:a:TOKEN / cr:c:TOKEN / cr:j:TOKEN."""
    if not data or not data.startswith("cr:"):
        return None
    parts = data.split(":", 2)
    if len(parts) != 3:
        return None
    action = parts[1]
    if action not in ("a", "c", "j"):
        return None
    return action, parts[2]


def _resolve_review_chat_id(client: Client) -> str | None:
    """Client review previews go to the intake group only (not publish destination)."""
    group_id = (client.telegram_group_id or "").strip()
    return group_id or None


def _platform_badges(platforms: list[str]) -> str:
    if not platforms:
        return "—"
    labels = [_PLATFORM_BADGES.get(p, p.title()) for p in platforms]
    return " · ".join(labels)


def _primary_caption(item: ContentItem) -> str:
    """RU caption first, then other languages."""
    for short_attr, long_attr in (
        ("caption_short_ru", "caption_long_ru"),
        ("caption_short_uz", "caption_long_uz"),
        ("caption_short_en", "caption_long_en"),
    ):
        body = (getattr(item, long_attr) or getattr(item, short_attr) or "").strip()
        if body:
            return body[:800] + ("…" if len(body) > 800 else "")
    return "—"


def _format_schedule(scheduled_for: datetime | None) -> str:
    if not scheduled_for:
        return "Not scheduled yet"
    dt = scheduled_for
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(settings.DISPLAY_TIMEZONE)
        local = dt.astimezone(tz)
        return f"{local.strftime('%d.%m.%Y %H:%M')} ({settings.DISPLAY_TIMEZONE})"
    except Exception:
        return dt.strftime("%d.%m.%Y %H:%M UTC")


def _review_keyboard(token: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"cr:a:{token}"},
            {"text": "✏️ Request changes", "callback_data": f"cr:c:{token}"},
            {"text": "❌ Reject", "callback_data": f"cr:j:{token}"},
        ]]
    }


async def _api_post(
    method: str,
    *,
    json_payload: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
) -> tuple[dict | None, str | None]:
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    if not token:
        return None, "TELEGRAM_BOT_TOKEN is not configured"
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            if files:
                resp = await client.post(url, data=data, files=files)
            else:
                resp = await client.post(url, json=json_payload)
            resp.raise_for_status()
            body = resp.json()
            if not body.get("ok"):
                desc = body.get("description") or str(body)
                logger.warning("Telegram API %s failed: %s", method, desc)
                return None, desc
            return body.get("result"), None
    except Exception as exc:
        logger.warning("Telegram API %s error: %s", method, exc)
        return None, str(exc)


async def send_telegram_message(
    chat_id: int | str,
    text: str,
    *,
    reply_markup: dict | None = None,
) -> tuple[bool, str | None]:
    payload: dict = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    result, err = await _api_post("sendMessage", json_payload=payload)
    return (result is not None, err)


async def _send_media_group(
    chat_id: int | str,
    media_files: list[MediaFile],
    *,
    caption: str | None = None,
) -> tuple[bool, str | None]:
    media_payload = []
    files: dict = {}
    for idx, mf in enumerate(media_files[:10]):
        attach_name = f"file{idx}"
        is_video = mf.file_type == "video"
        media_payload.append({
            "type": "video" if is_video else "photo",
            "media": f"attach://{attach_name}",
            **({"caption": caption[:1024]} if idx == 0 and caption else {}),
        })
        data_bytes = await storage.read_file_bytes(mf.storage_path)
        filename = mf.original_filename or f"media{idx}"
        files[attach_name] = (filename, data_bytes, mf.mime_type or "application/octet-stream")

    token = settings.TELEGRAM_BOT_TOKEN.strip()
    if not token:
        return False, "TELEGRAM_BOT_TOKEN is not configured"
    url = f"{TELEGRAM_API}/bot{token}/sendMediaGroup"
    form = {"chat_id": str(chat_id), "media": json.dumps(media_payload)}
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(url, data=form, files=files)
            resp.raise_for_status()
            body = resp.json()
            if not body.get("ok"):
                desc = body.get("description") or str(body)
                return False, desc
            return True, None
    except Exception as exc:
        logger.warning("Telegram sendMediaGroup failed: %s", exc)
        return False, str(exc)


async def answer_callback_query(callback_query_id: str, text: str = "") -> None:
    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]
    await _api_post("answerCallbackQuery", json_payload=payload)


async def notify_admins(text: str) -> None:
    admin_raw = settings.TELEGRAM_ADMIN_ID.strip()
    if not admin_raw:
        return
    for admin_id in admin_raw.split(","):
        admin_id = admin_id.strip()
        if admin_id:
            await send_telegram_message(admin_id, text)


async def _resolve_media_files(db: AsyncSession, item: ContentItem) -> list[MediaFile]:
    selected = await ContentService.build_selected_media(db, item)
    files: list[MediaFile] = []
    seen: set[str] = set()
    for entry in selected:
        mf_id = entry.get("media_file_id")
        if not mf_id or mf_id in seen:
            continue
        seen.add(mf_id)
        mf = await db.get(MediaFile, UUID(str(mf_id)))
        if mf:
            files.append(mf)
    if not files and item.media_file:
        files.append(item.media_file)
    return files


async def _send_media_file(
    chat_id: int | str,
    mf: MediaFile,
    *,
    caption: str | None = None,
    reply_markup: dict | None = None,
) -> tuple[bool, str | None]:
    data_bytes = await storage.read_file_bytes(mf.storage_path)
    filename = mf.original_filename or "media"
    is_video = mf.file_type == "video"
    method = "sendVideo" if is_video else "sendPhoto"
    field = "video" if is_video else "photo"
    form: dict = {"chat_id": str(chat_id)}
    if caption:
        form["caption"] = caption[:1024]
    if reply_markup:
        form["reply_markup"] = json.dumps(reply_markup)
    result, err = await _api_post(
        method,
        data=form,
        files={field: (filename, data_bytes, mf.mime_type or "application/octet-stream")},
    )
    return (result is not None, err)


def build_preview_text(item: ContentItem, client: Client, *, review_token: str) -> str:
    caption = _primary_caption(item)
    hashtags = (item.hashtags or "").strip() or "—"
    review_link = _review_url(review_token)
    return (
        f"📋 Content preview — {client.company_name}\n"
        f"📬 Client review (intake group)\n\n"
        f"🗓 Scheduled: {_format_schedule(item.scheduled_for)}\n"
        f"📱 Platforms: {_platform_badges(item.platforms or [])}\n\n"
        f"📝 Caption (RU / best available):\n{caption}\n\n"
        f"#️⃣ Hashtags:\n{hashtags}\n\n"
        f"🔗 Web review link:\n{review_link}\n\n"
        f"Please review and choose an action:"
    )


def _callback_reply_chat_id(callback_query: dict) -> int | str | None:
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("id") is not None:
        return chat.get("id")
    from_user = callback_query.get("from") or {}
    return from_user.get("id")


class ClientReviewTelegramService:
    @staticmethod
    async def send_client_preview(db: AsyncSession, item: ContentItem) -> tuple[bool, str | None]:
        """Send preview to client's linked Telegram intake group."""
        if not settings.TELEGRAM_BOT_TOKEN.strip():
            return False, "TELEGRAM_BOT_TOKEN is not configured"

        result = await db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.client), selectinload(ContentItem.media_file))
            .where(ContentItem.id == item.id)
        )
        item = result.scalar_one()
        client: Client = item.client
        chat_id = _resolve_review_chat_id(client)
        logger.info(
            "[Client Review] telegram_group_id: %s",
            chat_id or "(missing)",
        )
        if not chat_id:
            return False, INTAKE_GROUP_NOT_LINKED

        if not item.review_token:
            item.review_token = secrets.token_urlsafe(32)
            await db.flush()

        token = item.review_token
        text = build_preview_text(item, client, review_token=token)
        keyboard = _review_keyboard(token)
        media_files = await _resolve_media_files(db, item)

        images = [mf for mf in media_files if mf.file_type != "video"]
        videos = [mf for mf in media_files if mf.file_type == "video"]

        last_error: str | None = None

        if len(images) > 1:
            ok, err = await _send_media_group(chat_id, images, caption=text[:1024])
            if not ok:
                return False, err or "Telegram sendMediaGroup failed"
            ok, err = await send_telegram_message(chat_id, text, reply_markup=keyboard)
            if not ok:
                return False, err or "Telegram sendMessage failed"
        elif len(images) == 1 and not videos:
            ok, err = await _send_media_file(chat_id, images[0], caption=text[:1024], reply_markup=keyboard)
            if not ok:
                return False, err or "Telegram sendPhoto failed"
            if len(text) > 1024:
                ok, err = await send_telegram_message(chat_id, text[1024:], reply_markup=keyboard)
                if not ok:
                    last_error = err
        elif videos:
            ok, err = await _send_media_file(chat_id, videos[0], caption=text[:1024], reply_markup=keyboard)
            if not ok:
                return False, err or "Telegram sendVideo failed"
            if len(text) > 1024:
                ok, err = await send_telegram_message(chat_id, text[1024:], reply_markup=keyboard)
                if not ok:
                    last_error = err
            for extra in images:
                await _send_media_file(chat_id, extra)
        else:
            ok, err = await send_telegram_message(chat_id, text, reply_markup=keyboard)
            if not ok:
                return False, err or "Telegram sendMessage failed"

        if last_error:
            return False, last_error

        logger.info("[Client Review] preview sent: content=%s", item.id)
        return True, None

    @staticmethod
    async def handle_callback(db: AsyncSession, callback_query: dict) -> dict | None:
        data = callback_query.get("data") or ""
        parsed = _parse_callback_data(data)
        if not parsed:
            return None

        action, token = parsed
        cq_id = callback_query.get("id", "")
        from_user = callback_query.get("from") or {}
        telegram_user_id = from_user.get("id")
        reply_chat = _callback_reply_chat_id(callback_query)

        from app.services.content_review_service import ContentReviewService

        if action == "a":
            await ContentReviewService.client_approve(db, token, via="telegram")
            await answer_callback_query(cq_id, "Approved")
            if reply_chat is not None:
                await send_telegram_message(reply_chat, "✅ Approved")
            return {"client_review": "approved"}

        if action == "c":
            result = await db.execute(
                select(ContentItem).where(ContentItem.review_token == token)
            )
            item = result.scalar_one_or_none()
            if not item:
                await answer_callback_query(cq_id, "Review link expired")
                return None
            if telegram_user_id:
                register_pending_feedback(telegram_user_id, item.id)
            await answer_callback_query(cq_id, "Describe changes…")
            if reply_chat is not None:
                await send_telegram_message(
                    reply_chat,
                    "✏️ Please describe what you'd like changed (reply in this chat):",
                )
            return {"client_review": "awaiting_feedback", "content_id": str(item.id)}

        if action == "j":
            await ContentReviewService.client_reject(db, token, via="telegram")
            await answer_callback_query(cq_id, "Rejected")
            if reply_chat is not None:
                await send_telegram_message(reply_chat, "❌ Rejected — the team has been notified.")
            return {"client_review": "rejected"}

        return None

    @staticmethod
    async def handle_feedback_message(
        db: AsyncSession,
        telegram_user_id: int,
        text: str,
        *,
        reply_chat_id: int | str | None = None,
    ) -> dict | None:
        content_id_str = pop_pending_feedback(telegram_user_id)
        if not content_id_str:
            return None

        from app.services.content_review_service import ContentReviewService

        result = await db.execute(
            select(ContentItem).where(ContentItem.id == UUID(content_id_str))
        )
        item = result.scalar_one_or_none()
        if not item or not item.review_token:
            return None

        response = await ContentReviewService.client_request_changes(
            db, item.review_token, text, via="telegram",
        )
        if reply_chat_id is not None:
            await send_telegram_message(
                reply_chat_id,
                "✅ Thank you — your feedback has been sent to the team.",
            )
        return response
