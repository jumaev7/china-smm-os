"""Telegram channel publisher — mock or real via Bot API."""
from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.storage import storage
from app.services.publish_context import PublishContext

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
_CAPTION_LIMIT = 1024


def _mock_publish(ctx: PublishContext) -> dict:
    chat_id = _normalize_chat_id(ctx.account_id or "@mock_channel")
    mock_message_id = secrets.token_hex(6)
    payload = _success_payload(
        chat_id=chat_id,
        message_id=mock_message_id,
        mock=True,
        media_type="mock",
        caption=_caption_text(ctx),
        extra_message=(
            f"[Mock] Posted to Telegram channel ({ctx.account_name or 'account'}) "
            f"for {ctx.company_name}"
        ),
    )
    payload["media_url"] = ctx.media_url
    return payload


def _normalize_chat_id(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Telegram channel username or chat_id is required")
    if value.startswith("-") or value.lstrip("-").isdigit():
        return value
    return value if value.startswith("@") else f"@{value}"


def _caption_text(ctx: PublishContext) -> str:
    text = (ctx.caption or "").strip()
    if len(text) > _CAPTION_LIMIT:
        text = text[: _CAPTION_LIMIT - 1] + "…"
    return text


def _storage_path_from_url(url: str) -> str | None:
    marker = "/media/"
    idx = url.find(marker)
    if idx >= 0:
        return url[idx + len(marker) :]
    return None


async def _load_media_bytes(url: str) -> tuple[bytes, str, str]:
    path = _storage_path_from_url(url)
    if path and storage.exists(path):
        data = await storage.read_file_bytes(path)
        ext = Path(path).suffix.lower() or ".bin"
        mime = "video/mp4" if ext in (".mp4", ".mov", ".webm") else "image/jpeg"
        filename = Path(path).name or f"media{ext}"
        return data, filename, mime

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0]
        ext = ".mp4" if "video" in content_type else ".jpg"
        filename = f"media{ext}"
        return resp.content, filename, content_type


def _collect_media(ctx: PublishContext) -> tuple[list[str], str | None]:
    photos: list[str] = []
    video_url: str | None = None

    if ctx.final_video_url and ctx.media_type == "video":
        video_url = ctx.final_video_url
    elif ctx.media_url and ctx.media_type == "video":
        video_url = ctx.media_url

    for item in ctx.selected_media or []:
        url = item.get("url")
        if not url:
            continue
        media_type = item.get("media_type") or "image"
        if media_type == "video" and not video_url:
            video_url = url
        elif media_type != "video":
            photos.append(url)

    if not photos and not video_url and ctx.media_url:
        if ctx.media_type == "video":
            video_url = ctx.media_url
        else:
            photos.append(ctx.media_url)

    return photos, video_url


def _telegram_post_url(account_id: str, message_id: int | str) -> str | None:
    """Build a t.me link for a published channel/supergroup message."""
    raw = (account_id or "").strip()
    mid = str(message_id)
    if not raw or not mid:
        return None

    if raw.startswith("@"):
        return f"https://t.me/{raw[1:]}/{mid}"

    if raw.startswith("-100") and len(raw) > 4 and raw[4:].isdigit():
        return f"https://t.me/c/{raw[4:]}/{mid}"

    if raw.startswith("-") and raw[1:].isdigit():
        return f"https://t.me/c/{raw[1:]}/{mid}"

    if raw.isdigit():
        return f"https://t.me/c/{raw}/{mid}"

    username = raw.lstrip("@")
    if username:
        return f"https://t.me/{username}/{mid}"
    return None


def _success_payload(
    *,
    chat_id: str,
    message_id: int | str,
    mock: bool,
    media_type: str,
    caption: str,
    extra_message: str | None = None,
) -> dict:
    post_id = str(message_id)
    post_url = None if mock else _telegram_post_url(chat_id, message_id)
    if post_url:
        logger.info("[Telegram Publish] post_url: %s", post_url)
    message = extra_message or (
        f"[Mock] Posted to Telegram channel" if mock else f"Posted to Telegram channel {chat_id}"
    )
    return {
        "platform": "telegram",
        "success": True,
        "mock": mock,
        "platform_post_id": post_id,
        "post_url": post_url,
        "account_id": chat_id,
        "message": message,
        "media_type": media_type,
        "caption_preview": caption[:120] if caption else None,
    }


async def _call_telegram(
    method: str,
    *,
    data: dict | None = None,
    files: dict | None = None,
) -> dict:
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

    url = f"{TELEGRAM_API}/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        if files:
            resp = await client.post(url, data=data or {}, files=files)
        else:
            resp = await client.post(url, json=data or {})
    try:
        body = resp.json()
    except Exception as exc:
        raise ValueError(f"Telegram API invalid response ({resp.status_code})") from exc

    if not body.get("ok"):
        raise ValueError(body.get("description") or f"Telegram API error ({resp.status_code})")
    return body["result"]


async def _real_publish(ctx: PublishContext) -> dict:
    chat_id = _normalize_chat_id(ctx.account_id or "")
    caption = _caption_text(ctx)
    photos, video_url = _collect_media(ctx)
    media_type = "text"
    if video_url:
        media_type = "video"
    elif photos:
        media_type = "photo" if len(photos) == 1 else "photo_album"

    logger.info(
        "[Telegram Publish] account: %s channel=%s status=connected",
        ctx.account_name,
        chat_id,
    )
    logger.info("[Telegram Publish] media type: %s photos=%s video=%s", media_type, len(photos), bool(video_url))

    try:
        if video_url:
            file_bytes, filename, mime = await _load_media_bytes(video_url)
            result = await _call_telegram(
                "sendVideo",
                data={"chat_id": chat_id, "caption": caption, "supports_streaming": "true"},
                files={"video": (filename, file_bytes, mime)},
            )
            message_id = result["message_id"]
        elif len(photos) >= 2:
            try:
                media_payload = []
                files: dict[str, tuple] = {}
                for idx, photo_url in enumerate(photos[:10]):
                    file_bytes, filename, mime = await _load_media_bytes(photo_url)
                    attach_key = f"photo{idx}"
                    files[attach_key] = (filename, file_bytes, mime)
                    entry: dict = {"type": "photo", "media": f"attach://{attach_key}"}
                    if idx == 0 and caption:
                        entry["caption"] = caption
                    media_payload.append(entry)
                result = await _call_telegram(
                    "sendMediaGroup",
                    data={"chat_id": chat_id, "media": json.dumps(media_payload)},
                    files=files,
                )
                message_id = (
                    result[0]["message_id"]
                    if isinstance(result, list) and result
                    else result.get("message_id")
                )
            except Exception as album_exc:
                logger.warning(
                    "[Telegram Publish] sendMediaGroup failed, fallback to first photo: %s",
                    album_exc,
                )
                file_bytes, filename, mime = await _load_media_bytes(photos[0])
                result = await _call_telegram(
                    "sendPhoto",
                    data={"chat_id": chat_id, "caption": caption},
                    files={"photo": (filename, file_bytes, mime)},
                )
                message_id = result["message_id"]
        elif len(photos) == 1:
            file_bytes, filename, mime = await _load_media_bytes(photos[0])
            result = await _call_telegram(
                "sendPhoto",
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": (filename, file_bytes, mime)},
            )
            message_id = result["message_id"]
        else:
            if not caption:
                raise ValueError("Nothing to publish — add caption or media")
            result = await _call_telegram(
                "sendMessage",
                data={"chat_id": chat_id, "text": caption},
            )
            message_id = result["message_id"]

        logger.info("[Telegram Publish] success: channel=%s post_id=%s", chat_id, message_id)
        return _success_payload(
            chat_id=chat_id,
            message_id=message_id,
            mock=False,
            media_type=media_type,
            caption=caption,
        )
    except Exception as exc:
        logger.error("[Telegram Publish] failed: channel=%s error=%s", chat_id, exc)
        return {
            "platform": "telegram",
            "success": False,
            "mock": False,
            "platform_post_id": None,
            "error": str(exc),
            "media_type": media_type,
            "caption_preview": caption[:120] if caption else None,
        }


async def publish(ctx: PublishContext) -> dict:
    if ctx.account_status == "mock":
        return _mock_publish(ctx)
    return await _real_publish(ctx)
