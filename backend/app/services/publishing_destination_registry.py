"""Canonical publishing destination truth — implementation status per platform."""
from __future__ import annotations

from typing import Any, Literal

from app.core.config import settings
from app.services.meta_graph_client import meta_oauth_configured

DestinationGlobalStatus = Literal["live", "partial", "mock", "not_configured"]
TenantDestinationStatus = Literal["live", "partial", "mock", "not_configured", "blocked"]

SUPPORTED_DESTINATIONS = ("telegram", "instagram", "facebook", "tiktok", "linkedin")

META_ACCOUNT_BLOCK_STATUSES = frozenset({
    "disconnected",
    "expired",
    "invalid",
    "missing_permissions",
    "blocked",
})

# Architecture truth — what the codebase actually implements today.
DESTINATION_TRUTH: dict[str, dict[str, Any]] = {
    "telegram": {
        "global_status": "live",
        "adapter": "telegram_publisher",
        "api": "Telegram Bot API (sendPhoto, sendVideo, sendMediaGroup, sendMessage)",
        "blockers_for_real": [
            "TELEGRAM_BOT_TOKEN must be set",
            "Bot must be admin on target channel/supergroup",
            "Client telegram_publish_chat_id or connected telegram publishing account required",
        ],
    },
    "instagram": {
        "global_status": "mock",
        "adapter": "instagram_publisher",
        "api": "Mock publish only — Meta Graph connection foundation (no content publish yet)",
        "blockers_for_real": [
            "Graph API content publish not implemented in this milestone",
            "Publisher always sets mock=True until live adapter ships",
        ],
        "connection": "Meta OAuth — Facebook Page + Instagram Business account",
    },
    "facebook": {
        "global_status": "mock",
        "adapter": "facebook_publisher",
        "api": "Mock publish only — Meta Graph connection foundation (no content publish yet)",
        "blockers_for_real": [
            "Graph API page publish not implemented in this milestone",
            "Publisher always sets mock=True until live adapter ships",
        ],
        "connection": "Meta OAuth — Facebook Page access token storage",
    },
    "tiktok": {
        "global_status": "mock",
        "adapter": "tiktok_publisher",
        "api": "Mock only — returns mock-tt-* platform_post_id",
        "blockers_for_real": [
            "No TikTok Content Posting API integration",
        ],
    },
    "linkedin": {
        "global_status": "mock",
        "adapter": "linkedin_publisher",
        "api": "Mock only — returns mock-li-* platform_post_id",
        "blockers_for_real": [
            "No LinkedIn Marketing API integration",
        ],
    },
}


def telegram_bot_configured() -> bool:
    return bool((settings.TELEGRAM_BOT_TOKEN or "").strip())


def scheduled_worker_enabled() -> bool:
    return bool(settings.SCHEDULED_PUBLISH_ENABLED)


def meta_connection_configured() -> bool:
    return meta_oauth_configured()


def global_destination_status(platform: str) -> DestinationGlobalStatus:
    truth = DESTINATION_TRUTH.get(platform)
    if not truth:
        return "not_configured"
    status = truth["global_status"]
    if platform == "telegram" and status == "live" and not telegram_bot_configured():
        return "partial"
    if platform in ("facebook", "instagram") and meta_connection_configured():
        return "partial"
    return status  # type: ignore[return-value]


def _meta_account_blocked(account_status: str | None) -> bool:
    return account_status in META_ACCOUNT_BLOCK_STATUSES


def platform_implementation(
    platform: str,
    *,
    dest_status: TenantDestinationStatus,
    account_status: str | None = None,
) -> Literal["live", "mock", "blocked"]:
    """Per-tenant implementation truth — live API, mock adapter, or blocked."""
    truth = DESTINATION_TRUTH.get(platform)
    if not truth:
        return "blocked"
    if dest_status == "blocked":
        return "blocked"
    if platform in ("facebook", "instagram"):
        if _meta_account_blocked(account_status):
            return "blocked"
        return "mock"
    if truth.get("global_status") == "mock":
        return "mock"
    if platform == "telegram":
        if account_status == "mock":
            return "mock"
        if (
            dest_status == "live"
            and account_status == "connected"
            and telegram_bot_configured()
        ):
            return "live"
        return "blocked"
    return "mock"


def tenant_destination_status(
    platform: str,
    *,
    has_account: bool,
    account_status: str | None = None,
    telegram_publish_chat_id: str | None = None,
) -> TenantDestinationStatus:
    global_status = global_destination_status(platform)

    if platform == "telegram":
        has_dest = bool((telegram_publish_chat_id or "").strip())
        if global_status == "partial":
            return "blocked" if not has_dest and not has_account else "partial"
        if not has_dest and not has_account:
            return "blocked"
        if account_status == "mock" and not telegram_bot_configured():
            return "mock"
        if account_status == "mock":
            return "mock"
        if global_status == "live" and telegram_bot_configured():
            return "live"
        return "partial"

    if platform in ("facebook", "instagram"):
        if not has_account:
            return "blocked"
        if account_status == "mock":
            return "mock"
        if _meta_account_blocked(account_status):
            return "blocked"
        if account_status == "connected":
            return "partial" if global_status == "partial" else "mock"
        return "blocked"

    if not has_account:
        return "blocked"
    if global_status == "mock":
        return "mock"
    return global_status  # type: ignore[return-value]
