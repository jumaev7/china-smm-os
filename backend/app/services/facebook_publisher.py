"""Facebook Page publisher — mock, blocked, or live Graph API publish."""
from __future__ import annotations

import logging
import secrets

from app.core.config import settings
from app.services.meta_graph_client import (
    missing_facebook_publish_permissions,
    publish_page_feed_post,
    publish_page_photo_post,
)
from app.services.publish_context import PublishContext

logger = logging.getLogger(__name__)


def _blocked_result(ctx: PublishContext, error: str) -> dict:
    return {
        "platform": "facebook",
        "success": False,
        "mock": False,
        "blocked": True,
        "platform_post_id": None,
        "error": error,
        "account_name": ctx.account_name,
        "caption_preview": (ctx.caption or "")[:120],
    }


def _mock_publish(ctx: PublishContext) -> dict:
    post_id = f"mock-fb-{secrets.token_hex(6)}"
    return {
        "platform": "facebook",
        "success": True,
        "mock": True,
        "platform_post_id": post_id,
        "message": (
            f"[Mock] Posted to Facebook Page ({ctx.account_name or 'account'}) "
            f"for {ctx.company_name}"
        ),
        "media_url": ctx.media_url,
        "caption_preview": (ctx.caption or "")[:120],
    }


def _collect_image_url(ctx: PublishContext) -> str | None:
    if ctx.media_url and ctx.media_type != "video":
        return ctx.media_url
    for item in ctx.selected_media or []:
        url = item.get("url")
        if not url:
            continue
        if (item.get("media_type") or "image") != "video":
            return url
    return None


def _facebook_publish_blockers(ctx: PublishContext) -> list[str]:
    blockers: list[str] = []
    if not (ctx.page_access_token or "").strip():
        blockers.append("Facebook Page access token is missing — reconnect Meta account")
    if not (ctx.facebook_page_id or "").strip():
        blockers.append("Facebook Page ID is missing — reconnect Meta account")
    if (ctx.facebook_page_id or "").startswith("demo-page-"):
        blockers.append("Facebook demo account cannot publish live — connect a real Meta account")
    if ctx.token_expired:
        blockers.append("Meta access token has expired — reconnect or refresh the connection")
    missing_publish = missing_facebook_publish_permissions(ctx.permissions)
    if missing_publish:
        blockers.append(
            f"Facebook publish permission missing: {', '.join(missing_publish)}",
        )
    return blockers


async def _live_publish(ctx: PublishContext) -> dict:
    page_id = (ctx.facebook_page_id or "").strip()
    page_token = (ctx.page_access_token or "").strip()
    caption = (ctx.caption or "").strip()
    image_url = _collect_image_url(ctx)

    logger.info(
        "[Facebook Publish] account=%s page_id=%s has_image=%s",
        ctx.account_name,
        page_id,
        bool(image_url),
    )

    try:
        if image_url:
            result = await publish_page_photo_post(
                page_id=page_id,
                page_access_token=page_token,
                image_url=image_url,
                caption=caption,
            )
            media_type = "photo"
        elif caption:
            result = await publish_page_feed_post(
                page_id=page_id,
                page_access_token=page_token,
                message=caption,
            )
            media_type = "text"
        else:
            return _blocked_result(
                ctx,
                "Nothing to publish — add caption or image for Facebook Page post",
            )

        post_id = result["platform_post_id"]
        post_url = result.get("post_url")
        logger.info("[Facebook Publish] success page_id=%s post_id=%s", page_id, post_id)
        return {
            "platform": "facebook",
            "success": True,
            "mock": False,
            "platform_post_id": post_id,
            "post_url": post_url,
            "message": f"Posted to Facebook Page {ctx.account_name or page_id}",
            "media_type": media_type,
            "media_url": image_url,
            "caption_preview": caption[:120] if caption else None,
        }
    except Exception as exc:
        logger.error("[Facebook Publish] failed page_id=%s error=%s", page_id, exc)
        return {
            "platform": "facebook",
            "success": False,
            "mock": False,
            "platform_post_id": None,
            "error": str(exc),
            "caption_preview": caption[:120] if caption else None,
        }


async def publish(ctx: PublishContext) -> dict:
    if ctx.account_status == "mock":
        return _mock_publish(ctx)

    blockers = _facebook_publish_blockers(ctx)
    if blockers:
        return _blocked_result(ctx, blockers[0])

    if not settings.ENABLE_FACEBOOK_LIVE_SMOKE:
        return _blocked_result(
            ctx,
            "Facebook live publish is disabled — set ENABLE_FACEBOOK_LIVE_SMOKE=true to post",
        )

    return await _live_publish(ctx)
