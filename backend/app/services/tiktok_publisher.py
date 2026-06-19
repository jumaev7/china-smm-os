"""TikTok publisher adapter (mock)."""
from __future__ import annotations

import secrets

from app.services.publish_context import PublishContext


async def publish(ctx: PublishContext) -> dict:
    post_id = f"mock-tt-{secrets.token_hex(6)}"
    return {
        "platform": "tiktok",
        "success": True,
        "mock": True,
        "platform_post_id": post_id,
        "message": f"[Mock] Posted to TikTok ({ctx.account_name or 'account'}) for {ctx.company_name}",
        "media_url": ctx.final_video_url or ctx.media_url,
        "caption_preview": (ctx.caption or "")[:120],
    }
