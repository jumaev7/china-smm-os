"""Meta Graph API client — OAuth exchange, token debug, page/IG resolution."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"

REQUIRED_CONNECTION_PERMISSIONS = frozenset({
    "pages_show_list",
    "pages_read_engagement",
    "instagram_basic",
    "business_management",
})

FUTURE_PUBLISH_PERMISSIONS = frozenset({
    "pages_manage_posts",
    "instagram_content_publish",
})

REQUIRED_FACEBOOK_PUBLISH_PERMISSIONS = frozenset({
    "pages_manage_posts",
})


def meta_oauth_configured() -> bool:
    return bool(
        (settings.META_APP_ID or "").strip()
        and (settings.META_APP_SECRET or "").strip()
        and (settings.META_OAUTH_REDIRECT_URI or "").strip()
    )


def _graph_version() -> str:
    return (settings.META_GRAPH_API_VERSION or "v21.0").strip().lstrip("v")


def _graph_url(path: str) -> str:
    version = _graph_version()
    return f"{GRAPH_BASE}/v{version}/{path.lstrip('/')}"


def build_oauth_authorize_url(*, state: str) -> str:
    scopes = (settings.META_OAUTH_SCOPES or "").strip() or ",".join(
        sorted(REQUIRED_CONNECTION_PERMISSIONS | FUTURE_PUBLISH_PERMISSIONS)
    )
    params = {
        "client_id": settings.META_APP_ID,
        "redirect_uri": settings.META_OAUTH_REDIRECT_URI,
        "state": state,
        "scope": scopes,
        "response_type": "code",
    }
    return f"https://www.facebook.com/v{_graph_version()}/dialog/oauth?{urlencode(params)}"


async def _get_json(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(_graph_url(path), params=params or {})
        payload = response.json()
        if response.status_code >= 400 or "error" in payload:
            error = payload.get("error") or {}
            message = error.get("message") or response.text
            raise RuntimeError(f"Meta Graph API error: {message}")
        return payload


async def _post_json(path: str, *, params: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(_graph_url(path), data=params)
        payload = response.json()
        if response.status_code >= 400 or "error" in payload:
            error = payload.get("error") or {}
            message = error.get("message") or response.text
            raise RuntimeError(f"Meta Graph API error: {message}")
        return payload


def facebook_post_url(platform_post_id: str) -> str | None:
    post_id = (platform_post_id or "").strip()
    if not post_id:
        return None
    if "_" in post_id:
        page_id, story_id = post_id.split("_", 1)
        if page_id and story_id:
            return f"https://www.facebook.com/{page_id}/posts/{story_id}"
    return f"https://www.facebook.com/{post_id}"


async def publish_page_feed_post(
    *,
    page_id: str,
    page_access_token: str,
    message: str,
) -> dict[str, Any]:
    """Publish a text-only post to a Facebook Page feed."""
    payload = await _post_json(
        f"{page_id}/feed",
        params={
            "access_token": page_access_token,
            "message": message,
        },
    )
    post_id = str(payload.get("id") or "")
    if not post_id:
        raise RuntimeError("Meta Graph API returned no post id for page feed publish")
    return {
        "platform_post_id": post_id,
        "post_url": facebook_post_url(post_id),
        "raw": payload,
    }


async def publish_page_photo_post(
    *,
    page_id: str,
    page_access_token: str,
    image_url: str,
    caption: str = "",
) -> dict[str, Any]:
    """Publish a single image post to a Facebook Page (image URL must be publicly reachable)."""
    params: dict[str, Any] = {
        "access_token": page_access_token,
        "url": image_url,
    }
    if caption:
        params["caption"] = caption
    payload = await _post_json(f"{page_id}/photos", params=params)
    post_id = str(payload.get("post_id") or payload.get("id") or "")
    if not post_id:
        raise RuntimeError("Meta Graph API returned no post id for page photo publish")
    return {
        "platform_post_id": post_id,
        "post_url": facebook_post_url(post_id),
        "raw": payload,
    }


async def exchange_code_for_token(code: str) -> dict[str, Any]:
    return await _get_json(
        "oauth/access_token",
        params={
            "client_id": settings.META_APP_ID,
            "client_secret": settings.META_APP_SECRET,
            "redirect_uri": settings.META_OAUTH_REDIRECT_URI,
            "code": code,
        },
    )


async def exchange_for_long_lived_token(short_lived_token: str) -> dict[str, Any]:
    return await _get_json(
        "oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": settings.META_APP_ID,
            "client_secret": settings.META_APP_SECRET,
            "fb_exchange_token": short_lived_token,
        },
    )


async def debug_token(access_token: str) -> dict[str, Any]:
    app_token = f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"
    payload = await _get_json(
        "debug_token",
        params={"input_token": access_token, "access_token": app_token},
    )
    return payload.get("data") or {}


async def get_user_pages(user_access_token: str) -> list[dict[str, Any]]:
    payload = await _get_json(
        "me/accounts",
        params={
            "access_token": user_access_token,
            "fields": "id,name,access_token,instagram_business_account{id,username,name}",
        },
    )
    return list(payload.get("data") or [])


def _parse_expires_at(data: dict[str, Any]) -> datetime | None:
    expires_at = data.get("expires_at")
    if expires_at in (None, 0):
        return None
    try:
        return datetime.fromtimestamp(int(expires_at), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def token_is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    return expires_at <= datetime.now(timezone.utc)


def extract_granted_permissions(debug_data: dict[str, Any]) -> list[str]:
    scopes = debug_data.get("scopes") or debug_data.get("granular_scopes") or []
    if not scopes:
        return []
    if isinstance(scopes[0], dict):
        return sorted({s.get("scope", "") for s in scopes if s.get("scope")})
    return sorted({str(s) for s in scopes if s})


def missing_connection_permissions(granted: list[str]) -> list[str]:
    granted_set = set(granted)
    return sorted(REQUIRED_CONNECTION_PERMISSIONS - granted_set)


def missing_facebook_publish_permissions(granted: list[str]) -> list[str]:
    granted_set = set(granted)
    return sorted(REQUIRED_FACEBOOK_PUBLISH_PERMISSIONS - granted_set)


def pick_page(pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not pages:
        return None
    with_ig = [p for p in pages if (p.get("instagram_business_account") or {}).get("id")]
    return with_ig[0] if with_ig else pages[0]


async def resolve_page_connection(user_access_token: str) -> dict[str, Any]:
    """Exchange tokens and resolve the primary Facebook Page + Instagram Business account."""
    long_lived = await exchange_for_long_lived_token(user_access_token)
    long_token = long_lived.get("access_token") or user_access_token
    user_debug = await debug_token(long_token)
    pages = await get_user_pages(long_token)
    page = pick_page(pages)
    if not page:
        raise RuntimeError("No Facebook Pages found for this Meta account")

    page_token = page.get("access_token") or ""
    page_debug = await debug_token(page_token) if page_token else {}
    ig_account = page.get("instagram_business_account") or {}

    return {
        "user_access_token": long_token,
        "user_expires_at": _parse_expires_at(user_debug),
        "page_access_token": page_token,
        "page_expires_at": _parse_expires_at(page_debug),
        "facebook_page_id": str(page.get("id") or ""),
        "facebook_page_name": str(page.get("name") or ""),
        "instagram_business_account_id": str(ig_account.get("id") or ""),
        "instagram_username": str(ig_account.get("username") or ig_account.get("name") or ""),
        "permissions": extract_granted_permissions(user_debug),
        "metadata": {
            "meta_user_id": str(user_debug.get("user_id") or ""),
            "page_count": len(pages),
            "pages": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "has_instagram": bool((p.get("instagram_business_account") or {}).get("id")),
                }
                for p in pages
            ],
        },
    }
