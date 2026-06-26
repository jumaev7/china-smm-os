"""Meta OAuth flow — authorize URL, callback handling, demo fallback."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.meta_connection_service import MetaConnectionService
from app.services.meta_graph_client import (
    exchange_code_for_token,
    meta_oauth_configured,
    resolve_page_connection,
)

logger = logging.getLogger(__name__)

STATE_TTL_MINUTES = 15


class MetaOAuthService:
    @staticmethod
    def _encode_state() -> str:
        payload = {
            "nonce": secrets.token_hex(8),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES),
        }
        return jwt.encode(payload, settings.admin_secret_key, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def _verify_state(state: str) -> None:
        try:
            jwt.decode(
                state,
                settings.admin_secret_key,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError as exc:
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc

    @staticmethod
    def start_oauth() -> dict[str, str]:
        if not meta_oauth_configured():
            if settings.DEMO_MODE:
                return {
                    "authorize_url": "",
                    "demo_connect_url": "/api/v1/publishing/meta/oauth/demo-connect",
                    "mode": "demo",
                }
            raise HTTPException(
                status_code=400,
                detail=(
                    "Meta OAuth not configured. Set META_APP_ID, META_APP_SECRET, "
                    "and META_OAUTH_REDIRECT_URI."
                ),
            )
        state = MetaOAuthService._encode_state()
        from app.services.meta_graph_client import build_oauth_authorize_url

        return {
            "authorize_url": build_oauth_authorize_url(state=state),
            "state": state,
            "mode": "live",
        }

    @staticmethod
    async def handle_callback(
        db: AsyncSession,
        *,
        code: str | None,
        state: str | None,
        error: str | None = None,
        error_description: str | None = None,
    ) -> dict[str, str]:
        if error:
            message = error_description or error
            raise HTTPException(status_code=400, detail=f"Meta OAuth denied: {message}")
        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing OAuth code or state")
        MetaOAuthService._verify_state(state)

        if not meta_oauth_configured():
            raise HTTPException(status_code=400, detail="Meta OAuth not configured")

        token_payload = await exchange_code_for_token(code)
        short_token = token_payload.get("access_token")
        if not short_token:
            raise HTTPException(status_code=400, detail="Meta OAuth did not return an access token")

        connection = await resolve_page_connection(short_token)
        accounts = await MetaConnectionService.upsert_from_oauth(db, connection)
        return {
            "status": "connected",
            "facebook_account_id": str(accounts["facebook"].id),
            "instagram_account_id": str(accounts["instagram"].id) if "instagram" in accounts else "",
            "facebook_page_id": connection["facebook_page_id"],
            "instagram_business_account_id": connection.get("instagram_business_account_id") or "",
        }

    @staticmethod
    async def demo_connect(db: AsyncSession) -> dict[str, str]:
        if not settings.DEMO_MODE:
            raise HTTPException(status_code=400, detail="Demo Meta connect requires DEMO_MODE=true")
        expires_at = datetime.now(timezone.utc) + timedelta(days=60)
        connection = {
            "user_access_token": f"demo-user-token-{secrets.token_hex(8)}",
            "user_expires_at": expires_at,
            "page_access_token": f"demo-page-token-{secrets.token_hex(8)}",
            "page_expires_at": expires_at,
            "facebook_page_id": f"demo-page-{secrets.token_hex(4)}",
            "facebook_page_name": "Demo Facebook Page",
            "instagram_business_account_id": f"demo-ig-{secrets.token_hex(4)}",
            "instagram_username": "demo_instagram_business",
            "permissions": sorted({
                "pages_show_list",
                "pages_read_engagement",
                "instagram_basic",
                "business_management",
                "pages_manage_posts",
                "instagram_content_publish",
            }),
            "metadata": {"demo": True, "meta_user_id": f"demo-user-{secrets.token_hex(4)}"},
        }
        accounts = await MetaConnectionService.upsert_from_oauth(db, connection)
        return {
            "status": "connected",
            "mode": "demo",
            "facebook_account_id": str(accounts["facebook"].id),
            "instagram_account_id": str(accounts["instagram"].id) if "instagram" in accounts else "",
        }

    @staticmethod
    def frontend_redirect_url(*, success: bool, message: str = "") -> str:
        base = (settings.PUBLIC_APP_URL or "http://localhost:3000").rstrip("/")
        params = "meta_connected=1" if success else f"meta_error={message[:200]}"
        return f"{base}/publishing?{params}"
