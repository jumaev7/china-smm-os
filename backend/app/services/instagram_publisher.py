"""Instagram Business publisher — mock, blocked, or live Graph API publish."""
from __future__ import annotations

import logging
import secrets
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from PIL import Image

from app.core.config import settings
from app.core.storage import storage
from app.services.meta_graph_client import (
    MetaGraphError,
    missing_instagram_publish_permissions,
    publish_instagram_image,
)
from app.services.publish_context import PublishContext

logger = logging.getLogger(__name__)

_INSTAGRAM_MIN_RATIO = 4 / 5
_INSTAGRAM_MAX_RATIO = 1.91


def _fit_instagram_image_bytes(raw: bytes) -> tuple[bytes, bool]:
    """Pad an image into Instagram's supported aspect-ratio range, preserving it whole."""
    with Image.open(BytesIO(raw)) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    if not width or not height:
        raise ValueError("Instagram image has invalid dimensions")
    ratio = width / height
    if _INSTAGRAM_MIN_RATIO <= ratio <= _INSTAGRAM_MAX_RATIO:
        return raw, False

    target_width = max(width, int(round(height * _INSTAGRAM_MIN_RATIO)))
    target_height = max(height, int(round(width / _INSTAGRAM_MAX_RATIO)))
    canvas = Image.new("RGB", (target_width, target_height), (255, 255, 255))
    canvas.paste(image, ((target_width - width) // 2, (target_height - height) // 2))
    output = BytesIO()
    canvas.save(output, format="JPEG", quality=94, optimize=True)
    return output.getvalue(), True


async def _instagram_compatible_url(image_url: str) -> str:
    """Create an idempotent local derivative when a local image is too tall/wide."""
    base = urlparse((settings.MEDIA_BASE_URL or "").rstrip("/"))
    parsed = urlparse(image_url)
    if settings.USE_S3 or parsed.scheme != base.scheme or parsed.netloc != base.netloc:
        return image_url
    prefix = "/media/"
    if not parsed.path.startswith(prefix):
        return image_url
    key = unquote(parsed.path[len(prefix):]).lstrip("/")
    key_path = PurePosixPath(key)
    if not key or ".." in key_path.parts:
        raise ValueError("Unsafe Instagram media path")

    raw = await storage.read_file_bytes(key)
    fitted, changed = _fit_instagram_image_bytes(raw)
    if not changed:
        return image_url
    derivative = str(key_path.with_name(f"{key_path.stem}-instagram-4x5.jpg"))
    await storage.save_at_key(derivative, fitted)
    return storage.get_url(derivative)


def _result(ctx: PublishContext, *, error: str) -> dict:
    return {
        "platform": "instagram",
        "success": False,
        "mock": False,
        "blocked": True,
        "platform_post_id": None,
        "error": error,
        "account_name": ctx.account_name,
        "caption_preview": (ctx.caption or "")[:120],
    }


def _mock_publish(ctx: PublishContext) -> dict:
    post_id = f"mock-ig-{secrets.token_hex(6)}"
    return {
        "platform": "instagram",
        "success": True,
        "mock": True,
        "platform_post_id": post_id,
        "message": f"[Mock] Posted to Instagram Business ({ctx.account_name or 'account'}) for {ctx.company_name}",
        "media_url": ctx.media_url,
        "caption_preview": (ctx.caption or "")[:120],
    }


def _collect_image_url(ctx: PublishContext) -> str | None:
    if ctx.media_url and ctx.media_type != "video":
        return ctx.media_url
    for item in ctx.selected_media or []:
        if (item.get("media_type") or "image") != "video" and item.get("url"):
            return str(item["url"])
    return None


def _blockers(ctx: PublishContext) -> list[str]:
    blockers: list[str] = []
    if not (ctx.page_access_token or "").strip():
        blockers.append("Instagram Page access token is missing — reconnect Meta account")
    if not (ctx.instagram_business_account_id or "").strip():
        blockers.append("Instagram Business account ID is missing — reconnect Meta account")
    if ctx.token_expired:
        blockers.append("Meta access token has expired — reconnect or refresh the connection")
    missing = missing_instagram_publish_permissions(ctx.permissions)
    if missing:
        blockers.append(f"Instagram publish permission missing: {', '.join(missing)}")
    image_url = _collect_image_url(ctx)
    if not image_url:
        blockers.append("Instagram image publishing requires an image")
    elif urlparse(image_url).scheme.lower() != "https":
        blockers.append("Instagram image URL must be publicly reachable over HTTPS")
    return blockers


async def publish(ctx: PublishContext) -> dict:
    if ctx.account_status == "mock":
        return _mock_publish(ctx)

    blockers = _blockers(ctx)
    if blockers:
        return _result(ctx, error=blockers[0])
    if not settings.ENABLE_INSTAGRAM_LIVE_SMOKE:
        return _result(
            ctx,
            error="Instagram live publish is disabled — set ENABLE_INSTAGRAM_LIVE_SMOKE=true to post",
        )

    account_id = (ctx.instagram_business_account_id or "").strip()
    image_url = _collect_image_url(ctx) or ""
    try:
        image_url = await _instagram_compatible_url(image_url)
        published = await publish_instagram_image(
            instagram_business_account_id=account_id,
            page_access_token=(ctx.page_access_token or "").strip(),
            image_url=image_url,
            caption=(ctx.caption or "").strip(),
        )
        return {
            "platform": "instagram",
            "success": True,
            "mock": False,
            "platform_post_id": published["platform_post_id"],
            "post_url": published.get("post_url"),
            "message": f"Posted to Instagram Business {ctx.account_name or account_id}",
            "media_type": "image",
            "media_url": image_url,
            "caption_preview": (ctx.caption or "")[:120],
        }
    except MetaGraphError as exc:
        logger.error("[Instagram Publish] failed account_id=%s error=%s", account_id, exc)
        payload = {
            "platform": "instagram",
            "success": False,
            "mock": False,
            "platform_post_id": None,
            "error": str(exc),
            "caption_preview": (ctx.caption or "")[:120],
        }
        payload.update(exc.to_publish_fields())
        if exc.is_transient is False:
            payload["retryable"] = False
        elif exc.is_transient is True:
            payload["retryable"] = True
        return payload
    except Exception as exc:
        logger.error("[Instagram Publish] failed account_id=%s error=%s", account_id, exc)
        return {
            "platform": "instagram",
            "success": False,
            "mock": False,
            "platform_post_id": None,
            "error": str(exc),
            "caption_preview": (ctx.caption or "")[:120],
        }
