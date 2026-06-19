"""Scheduled publish diagnostics — explain why items are skipped by the scheduler."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.content import ContentItem
from app.models.publishing_account import PublishingAccount
from app.services.content_readiness_service import _has_caption
from app.services.content_review_service import client_review_required, is_client_approved
from app.services.content_service import ContentService
from app.services.publish_safety_service import SUPPORTED_PLATFORMS
from app.services.publishing_account_service import ACTIVE_STATUSES, PublishingAccountService

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class ScheduledPublishDiagnosticsService:
    @staticmethod
    def compute_skip_reason(
        item: ContentItem,
        *,
        now: datetime,
        has_media: bool,
        has_caption: bool,
        platforms: list[str],
        missing_account_platforms: list[str],
    ) -> str | None:
        if item.status == "published":
            return "already published"
        if item.status == "publishing":
            return "already publishing"
        if item.status != "scheduled":
            return "not scheduled"
        scheduled_for = _normalize_dt(item.scheduled_for)
        if scheduled_for is None:
            return "no scheduled_for"
        if scheduled_for > now:
            return "scheduled_for in future"
        if not item.approved_at:
            return "admin not approved"
        if item.status == "changes_requested" or item.client_review_status == "changes_requested":
            return "changes requested"
        if client_review_required(item) or (
            item.client_review_status and not is_client_approved(item)
        ):
            return "client not approved"
        if not platforms:
            return "no platforms"
        if missing_account_platforms:
            return "no publishing account"
        if not has_media and not has_caption:
            return "no caption/media"
        return None

    @staticmethod
    def compute_is_due(
        item: ContentItem,
        *,
        now: datetime,
        platforms: list[str],
    ) -> bool:
        scheduled_for = _normalize_dt(item.scheduled_for)
        return (
            item.status == "scheduled"
            and scheduled_for is not None
            and scheduled_for <= now
            and item.approved_at is not None
            and len(platforms) > 0
        )

    @staticmethod
    async def _accounts_for_platforms(
        db: AsyncSession,
        platforms: list[str],
    ) -> tuple[dict[str, list[str]], dict[str, str | None], list[str]]:
        available: dict[str, list[str]] = {}
        selected: dict[str, str | None] = {}
        missing: list[str] = []

        if not platforms:
            return available, selected, missing

        result = await db.execute(
            select(PublishingAccount)
            .where(PublishingAccount.platform.in_(platforms))
            .where(PublishingAccount.status.in_(tuple(ACTIVE_STATUSES)))
            .order_by(PublishingAccount.platform, PublishingAccount.created_at)
        )
        accounts = list(result.scalars().all())
        by_platform: dict[str, list[PublishingAccount]] = {}
        for account in accounts:
            by_platform.setdefault(account.platform, []).append(account)

        for platform in platforms:
            platform_accounts = by_platform.get(platform, [])
            available[platform] = [
                f"{a.account_name} ({a.status})" for a in platform_accounts
            ]
            if not platform_accounts:
                selected[platform] = None
                if platform in SUPPORTED_PLATFORMS:
                    missing.append(platform)
                continue
            try:
                resolved = await PublishingAccountService.resolve_for_platform(db, platform)
                selected[platform] = resolved.account_name
            except HTTPException:
                selected[platform] = None
                if platform in SUPPORTED_PLATFORMS:
                    missing.append(platform)

        return available, selected, missing

    @staticmethod
    def _format_local_time(scheduled_for: datetime | None, client_timezone: str | None) -> str | None:
        if scheduled_for is None or not client_timezone:
            return None
        try:
            from zoneinfo import ZoneInfo
            local = scheduled_for.astimezone(ZoneInfo(client_timezone))
            return local.strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            return None

    @staticmethod
    async def diagnose_item(
        db: AsyncSession,
        item: ContentItem,
        *,
        now: datetime | None = None,
        client_timezone: str | None = None,
    ) -> dict:
        now = now or _utc_now()
        platforms = list(item.platforms or [])
        selected_media = await ContentService.build_selected_media(db, item)
        has_media = bool(item.media_file_id) or len(selected_media) > 0
        has_caption = _has_caption(item)

        available, selected, missing = await ScheduledPublishDiagnosticsService._accounts_for_platforms(
            db, platforms,
        )
        skip_reason = ScheduledPublishDiagnosticsService.compute_skip_reason(
            item,
            now=now,
            has_media=has_media,
            has_caption=has_caption,
            platforms=platforms,
            missing_account_platforms=missing,
        )
        is_due = ScheduledPublishDiagnosticsService.compute_is_due(item, now=now, platforms=platforms)

        scheduled_for = _normalize_dt(item.scheduled_for)
        return {
            "id": item.id,
            "status": item.status,
            "scheduled_for": scheduled_for,
            "utc_time": scheduled_for.isoformat() if scheduled_for else None,
            "local_time": ScheduledPublishDiagnosticsService._format_local_time(
                scheduled_for, client_timezone,
            ),
            "current_time": now,
            "is_due": is_due,
            "approved_at": item.approved_at,
            "admin_approved": item.approved_at is not None,
            "client_review_status": item.client_review_status,
            "client_approved": is_client_approved(item),
            "platforms": platforms,
            "platforms_count": len(platforms),
            "publishing_accounts_available": available,
            "selected_accounts": selected,
            "has_media": has_media,
            "has_caption": has_caption,
            "skip_reason": skip_reason,
        }

    @staticmethod
    async def list_scheduled_debug(
        db: AsyncSession,
        *,
        client_timezone: str | None = None,
    ) -> dict:
        now = _utc_now()
        result = await db.execute(
            select(ContentItem)
            .where(ContentItem.scheduled_for.isnot(None))
            .options(selectinload(ContentItem.media_file))
            .order_by(ContentItem.scheduled_for.asc())
        )
        items = list(result.scalars().all())
        diagnosed = [
            await ScheduledPublishDiagnosticsService.diagnose_item(
                db, item, now=now, client_timezone=client_timezone,
            )
            for item in items
        ]
        due_count = sum(1 for entry in diagnosed if entry["is_due"] and entry["skip_reason"] is None)

        return {
            "current_time": now,
            "due_count": due_count,
            "items": diagnosed,
        }

    @staticmethod
    def log_scheduler_debug(entries: list[dict]) -> None:
        if not entries:
            logger.info("[Scheduler Publish Debug] item: (none with scheduled_for set)")
            return
        for entry in entries:
            logger.info("[Scheduler Publish Debug] item: %s", entry["id"])
            logger.info("[Scheduler Publish Debug] status: %s", entry["status"])
            logger.info("[Scheduler Publish Debug] is_due: %s", entry["is_due"])
            logger.info("[Scheduler Publish Debug] skip_reason: %s", entry["skip_reason"] or "(none)")
