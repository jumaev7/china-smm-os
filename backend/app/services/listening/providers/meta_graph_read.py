"""Read-only Meta Graph helpers for Social Listening.

These helpers only perform GET requests. They never publish, reply, comment,
react, message, or mutate Page content. Access tokens are accepted as
ephemeral call arguments and must never be persisted by callers.

Capability probes hit the real endpoint with limit=1 — permission *names*
on a token are never treated as proof that a capability works.
"""
from __future__ import annotations

import logging
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import httpx

from app.core.config import settings
from app.services.listening.providers.meta_errors import (
    MetaListeningError,
    classify_meta_error,
    public_failure_summary,
)

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"

# Official Permissions Reference + Pages API (independently verified):
# - pages_read_engagement: read content posted by the Page (/posts)
# - pages_read_user_content: read UGC comments; also documents tagged posts
# Do not assume /tagged works merely because pages_read_user_content is granted.
REQUIRED_FACEBOOK_COMMENTS_PERMISSIONS = frozenset({
    "pages_show_list",
    "pages_read_engagement",
    "pages_read_user_content",
})
REQUIRED_FACEBOOK_MENTIONS_PERMISSIONS = frozenset({
    "pages_show_list",
    "pages_read_user_content",
})

PROVIDER_CAPABILITY_VERSION = "meta_listening_v1"

CapabilityProbeKind = Literal["owned_content_comments", "direct_account_mentions", "page_identity"]


def _graph_version() -> str:
    return (settings.META_GRAPH_API_VERSION or "v21.0").strip().lstrip("v")


def _graph_url(path: str) -> str:
    return f"{GRAPH_BASE}/v{_graph_version()}/{path.lstrip('/')}"


def cursor_from_paging(paging: dict[str, Any] | None) -> str | None:
    if not paging:
        return None
    cursors = paging.get("cursors") or {}
    after = cursors.get("after")
    if after:
        return str(after)
    next_url = paging.get("next")
    if not next_url:
        return None
    try:
        query = parse_qs(urlparse(str(next_url)).query)
        vals = query.get("after") or []
        return vals[0] if vals else None
    except Exception:  # noqa: BLE001
        return None


async def graph_get(
    path: str,
    *,
    access_token: str,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """GET a Graph path. Never logs the access token."""
    query = dict(params or {})
    query["access_token"] = access_token
    safe_path = path.lstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(_graph_url(safe_path), params=query)
    except httpx.TimeoutException as exc:
        raise MetaListeningError(
            "provider_unavailable",
            public_failure_summary("provider_unavailable"),
            retryable=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise MetaListeningError(
            "provider_unavailable",
            public_failure_summary("provider_unavailable"),
            retryable=True,
        ) from exc

    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise MetaListeningError(
            "malformed_provider_response",
            public_failure_summary("malformed_provider_response"),
            retryable=False,
            http_status=response.status_code,
        ) from exc

    if response.status_code >= 400 or (isinstance(payload, dict) and "error" in payload):
        err = classify_meta_error(
            http_status=response.status_code,
            payload=payload if isinstance(payload, dict) else None,
        )
        logger.warning(
            "listening_meta_graph_error",
            extra={
                "path": safe_path.split("?")[0][:120],
                "http_status": response.status_code,
                "error_code": err.code,
                "provider_code": err.provider_code,
            },
        )
        raise err

    if not isinstance(payload, dict):
        raise MetaListeningError(
            "malformed_provider_response",
            public_failure_summary("malformed_provider_response"),
            retryable=False,
            http_status=response.status_code,
        )
    return payload


async def fetch_page_posts(
    *,
    page_id: str,
    access_token: str,
    limit: int = 5,
    after: str | None = None,
    timeout: float = 30.0,
) -> tuple[list[dict[str, Any]], str | None]:
    """Read posts authored by the Page (pages_read_engagement)."""
    params: dict[str, Any] = {
        "fields": "id,message,created_time,permalink_url,updated_time",
        "limit": max(1, min(int(limit), 25)),
    }
    if after:
        params["after"] = after
    payload = await graph_get(
        f"{page_id}/posts",
        access_token=access_token,
        params=params,
        timeout=timeout,
    )
    data = list(payload.get("data") or [])
    return data, cursor_from_paging(payload.get("paging") if isinstance(payload.get("paging"), dict) else None)


async def fetch_post_comments(
    *,
    post_id: str,
    access_token: str,
    limit: int = 25,
    after: str | None = None,
    timeout: float = 30.0,
) -> tuple[list[dict[str, Any]], str | None]:
    """Read comments on a Page post (pages_read_user_content)."""
    params: dict[str, Any] = {
        "fields": "id,message,created_time,from{id,name},permalink_url,comment_count",
        "filter": "toplevel",
        "order": "chronological",
        "limit": max(1, min(int(limit), 50)),
    }
    if after:
        params["after"] = after
    payload = await graph_get(
        f"{post_id}/comments",
        access_token=access_token,
        params=params,
        timeout=timeout,
    )
    data = list(payload.get("data") or [])
    return data, cursor_from_paging(payload.get("paging") if isinstance(payload.get("paging"), dict) else None)


async def fetch_page_tagged(
    *,
    page_id: str,
    access_token: str,
    limit: int = 25,
    after: str | None = None,
    timeout: float = 30.0,
) -> tuple[list[dict[str, Any]], str | None]:
    """Read public posts in which the Page is tagged (GET /{page-id}/tagged)."""
    params: dict[str, Any] = {
        "fields": "id,message,created_time,permalink_url,from{id,name},updated_time",
        "limit": max(1, min(int(limit), 50)),
    }
    if after:
        params["after"] = after
    payload = await graph_get(
        f"{page_id}/tagged",
        access_token=access_token,
        params=params,
        timeout=timeout,
    )
    data = list(payload.get("data") or [])
    return data, cursor_from_paging(payload.get("paging") if isinstance(payload.get("paging"), dict) else None)


async def health_probe_page(
    *,
    page_id: str,
    access_token: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Harmless identity read — does not prove comments or tagged capability."""
    payload = await graph_get(
        page_id,
        access_token=access_token,
        params={"fields": "id,name"},
        timeout=timeout,
    )
    return {"page_id": str(payload.get("id") or page_id), "name": payload.get("name")}


async def probe_capability(
    *,
    kind: CapabilityProbeKind,
    page_id: str,
    access_token: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Validate a specific capability with a harmless limit=1 read.

    Permission strings on the token are never sufficient proof.

    A successful limit=1 probe confirms **endpoint access** for the authorized
    Page only — not general market coverage, keyword reach, competitor pages,
    or Instagram listening.
    """
    # Bound probe latency; never use unbounded Graph waits on health paths.
    probe_timeout = max(1.0, min(float(timeout), 15.0))

    if kind == "page_identity":
        page = await health_probe_page(
            page_id=page_id, access_token=access_token, timeout=probe_timeout,
        )
        return {
            "capability": kind,
            "status": "ok",
            "page_id": page.get("page_id"),
            "limitation": "endpoint_access_only",
        }

    if kind == "owned_content_comments":
        posts, _ = await fetch_page_posts(
            page_id=page_id,
            access_token=access_token,
            limit=1,
            timeout=probe_timeout,
        )
        if posts:
            post_id = str(posts[0].get("id") or "").strip()
            if post_id:
                await fetch_post_comments(
                    post_id=post_id,
                    access_token=access_token,
                    limit=1,
                    timeout=probe_timeout,
                )
        return {
            "capability": kind,
            "status": "ok",
            "endpoint": "GET /{page-post-id}/comments",
            "posts_sampled": len(posts),
            # Never persist Graph payloads — status/freshness only upstream.
            "limitation": (
                "limit=1 confirms endpoint access for this authorized Page only; "
                "not general market coverage"
            ),
        }

    if kind == "direct_account_mentions":
        rows, _ = await fetch_page_tagged(
            page_id=page_id,
            access_token=access_token,
            limit=1,
            timeout=probe_timeout,
        )
        return {
            "capability": kind,
            "status": "ok",
            "endpoint": "GET /{page-id}/tagged",
            "items_sampled": len(rows),
            "limitation": (
                "limit=1 confirms endpoint access for this authorized Page only; "
                "not general market coverage"
            ),
        }

    raise MetaListeningError(
        "unsupported_capability",
        public_failure_summary("unsupported_capability"),
        retryable=False,
    )


__all__ = [
    "REQUIRED_FACEBOOK_COMMENTS_PERMISSIONS",
    "REQUIRED_FACEBOOK_MENTIONS_PERMISSIONS",
    "PROVIDER_CAPABILITY_VERSION",
    "graph_get",
    "fetch_page_posts",
    "fetch_post_comments",
    "fetch_page_tagged",
    "health_probe_page",
    "probe_capability",
    "cursor_from_paging",
]
