"""Scheduled publishing queue — list blocked/due items and admin actions."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.calendar import CalendarEntry
from app.models.content import ContentItem
from app.schemas.publishing import PublishContentRequest
from app.services.content_readiness_service import _has_caption
from app.services.content_review_service import ContentReviewService
from app.services.content_service import ContentService
from app.services.publish_safety_service import PublishSafetyService, SUPPORTED_PLATFORMS
from app.services.publish_service import PublishService
from app.services.publishing_tenant_scope import tenant_id_for_content_optional
from app.services.scheduled_publish_diagnostics_service import ScheduledPublishDiagnosticsService

logger = logging.getLogger(__name__)

QUEUE_STATUSES = frozenset({"scheduled", "publishing", "failed", "partial_failed"})

BLOCK_REASON_LABELS: dict[str, str] = {
    "client not approved": "Waiting for client approval",
    "no publishing account": "Missing publishing account",
    "scheduled_for in future": "Scheduled time in future",
    "already publishing": "Stuck publishing",
    "already published": "Already published",
    "not scheduled": "Not scheduled",
    "no scheduled_for": "No scheduled time",
    "admin not approved": "Admin not approved",
    "changes requested": "Changes requested",
    "no platforms": "No platforms selected",
    "no caption/media": "Missing caption or media",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _block_reason_label(raw: str | None) -> str | None:
    if not raw:
        return None
    return BLOCK_REASON_LABELS.get(raw, raw.replace("_", " ").capitalize())


def _queue_category(
    item: ContentItem,
    *,
    skip_reason: str | None,
    safety_passed: bool,
    is_due: bool,
) -> str:
    if item.status == "publishing":
        return "stuck_publishing"
    if item.status in ("failed", "partial_failed"):
        return "failed"
    if skip_reason == "client not approved":
        return "waiting_client"
    if skip_reason == "no publishing account":
        return "waiting_account"
    if skip_reason == "scheduled_for in future":
        return "future"
    if item.status == "scheduled" and skip_reason is None and safety_passed and is_due:
        return "ready"
    if skip_reason:
        return "blocked"
    if item.status == "scheduled" and safety_passed:
        return "ready"
    return "blocked"


class PublishingQueueService:
    @staticmethod
    async def list_queue(
        db: AsyncSession,
        *,
        client_timezone: str | None = None,
    ) -> dict:
        now = _utc_now()
        result = await db.execute(
            select(ContentItem)
            .where(
                ContentItem.status.in_(tuple(QUEUE_STATUSES)),
                or_(
                    ContentItem.scheduled_for.isnot(None),
                    ContentItem.status == "publishing",
                ),
            )
            .options(
                selectinload(ContentItem.client),
                selectinload(ContentItem.media_file),
            )
            .order_by(ContentItem.scheduled_for.asc().nulls_last(), ContentItem.created_at.desc())
        )
        items = list(result.scalars().all())
        rows: list[dict] = []
        counts: dict[str, int] = {}

        for item in items:
            platforms = list(item.platforms or [])
            selected_media = await ContentService.build_selected_media(db, item)
            has_media = bool(item.media_file_id) or len(selected_media) > 0
            has_caption = _has_caption(item)
            content_tenant_id = await tenant_id_for_content_optional(db, item)
            if content_tenant_id is None:
                missing = [p for p in platforms if p in SUPPORTED_PLATFORMS]
            else:
                _, _, missing = await ScheduledPublishDiagnosticsService._accounts_for_platforms(
                    db, content_tenant_id, platforms,
                )
            skip_reason = ScheduledPublishDiagnosticsService.compute_skip_reason(
                item,
                now=now,
                has_media=has_media,
                has_caption=has_caption,
                platforms=platforms,
                missing_account_platforms=missing,
            )
            is_due = ScheduledPublishDiagnosticsService.compute_is_due(
                item, now=now, platforms=platforms,
            )

            safety = await PublishSafetyService.evaluate(
                db,
                item,
                target_platforms=platforms,
                mode="scheduled_publish",
                from_scheduler=True,
            )
            safety_status = "passed" if safety["passed"] else "blocked"
            category = _queue_category(
                item,
                skip_reason=skip_reason,
                safety_passed=safety["passed"],
                is_due=is_due,
            )
            counts[category] = counts.get(category, 0) + 1

            client = item.client
            scheduled_for = item.scheduled_for
            if scheduled_for and scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

            rows.append({
                "id": item.id,
                "client_id": item.client_id,
                "company_name": client.company_name if client else "Unknown",
                "status": item.status,
                "scheduled_for": scheduled_for,
                "local_time": ScheduledPublishDiagnosticsService._format_local_time(
                    scheduled_for, client_timezone,
                ),
                "platforms": platforms,
                "client_review_status": item.client_review_status,
                "admin_approved": item.approved_at is not None,
                "safety_status": safety_status,
                "block_reason": skip_reason,
                "block_reason_label": _block_reason_label(skip_reason),
                "queue_category": category,
                "is_due": is_due,
            })

        return {
            "current_time": now,
            "items": rows,
            "total": len(rows),
            "counts": counts,
        }

    @staticmethod
    async def cancel_schedule(db: AsyncSession, content_id: UUID) -> dict:
        item = await ContentService.get(db, content_id)
        if item.status not in QUEUE_STATUSES and item.status != "publishing":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel schedule for status={item.status}",
            )

        entry_result = await db.execute(
            select(CalendarEntry).where(CalendarEntry.content_item_id == content_id)
        )
        calendar_entry = entry_result.scalar_one_or_none()
        if calendar_entry:
            await db.delete(calendar_entry)

        item.scheduled_for = None
        if item.status == "publishing":
            await PublishService.recover_stale_publishing(db, content_id=content_id)
            await db.refresh(item)

        if item.approved_at:
            item.status = "approved"
        else:
            item.status = "ready"

        await db.commit()
        logger.info("[Publishing Queue] cancel: content=%s status=%s", content_id, item.status)
        return {
            "ok": True,
            "message": "Schedule cancelled — content removed from publish queue",
            "content_id": content_id,
            "status": item.status,
        }

    @staticmethod
    async def retry_publish(db: AsyncSession, content_id: UUID) -> dict:
        await PublishService.recover_stale_publishing(db, content_id=content_id)
        item = await PublishService._get_content(db, content_id)
        platforms = list(item.platforms or [])

        safety = await PublishSafetyService.evaluate(
            db,
            item,
            target_platforms=platforms,
            mode="manual_publish",
        )
        if not safety["passed"]:
            message = safety.get("message") or "Publish blocked by safety guard"
            logger.info(
                "[Publishing Queue] retry blocked: content=%s safety=%s",
                content_id,
                message,
            )
            return {
                "ok": False,
                "message": message,
                "content_id": content_id,
                "status": item.status,
                "safety_status": "blocked",
                "block_reason": message,
                "safety": safety,
            }

        if item.status not in ("scheduled", "approved", "failed", "partial_failed"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot retry publish for status={item.status}",
            )

        if item.status in ("failed", "partial_failed") and item.approved_at:
            item.status = "scheduled"
            await db.flush()

        result = await PublishService.publish_content(
            db,
            content_id,
            request=PublishContentRequest(mode="manual_publish"),
            platforms=platforms,
        )
        logger.info(
            "[Publishing Queue] retry: content=%s success=%s",
            content_id,
            result.get("all_success"),
        )
        return {
            "ok": bool(result.get("all_success")),
            "message": "Publish completed" if result.get("all_success") else "Publish finished with errors",
            "content_id": content_id,
            "status": result.get("status"),
            "safety_status": "passed",
            "publish_result": result,
        }

    @staticmethod
    async def send_client_review(db: AsyncSession, content_id: UUID) -> dict:
        result = await ContentReviewService.send_client_review_preview_manual(
            db, content_id, force=True,
        )
        sent = bool(result.get("sent"))
        return {
            "ok": sent and not result.get("skipped"),
            "message": (
                "Client review preview sent"
                if sent and not result.get("skipped")
                else result.get("reason") or result.get("error") or "Preview not sent"
            ),
            "content_id": content_id,
            "preview": result,
        }
