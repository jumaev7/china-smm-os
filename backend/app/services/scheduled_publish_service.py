"""Background worker — auto-publish scheduled content when scheduled_for is due."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.content import ContentItem
from app.schemas.publishing import PublishContentRequest
from app.services.publish_safety_service import PublishSafetyService
from app.services.publish_service import PublishService
from app.services.scheduled_publish_diagnostics_service import ScheduledPublishDiagnosticsService

logger = logging.getLogger(__name__)

TICK_SECONDS = 60
MAX_BATCH = 20


class ScheduledPublishService:
    _task: asyncio.Task | None = None

    @classmethod
    async def start(cls) -> None:
        if not settings.SCHEDULED_PUBLISH_ENABLED:
            logger.info("[Scheduler Publish] disabled (SCHEDULED_PUBLISH_ENABLED=false)")
            return
        if cls._task and not cls._task.done():
            return
        cls._task = asyncio.create_task(cls._run_loop())
        logger.info("[Scheduler Publish] worker started (interval=%ss)", TICK_SECONDS)

    @classmethod
    async def stop(cls) -> None:
        if not cls._task:
            return
        cls._task.cancel()
        try:
            await cls._task
        except asyncio.CancelledError:
            pass
        cls._task = None
        logger.info("[Scheduler Publish] worker stopped")

    @classmethod
    async def _run_loop(cls) -> None:
        while True:
            try:
                await cls.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[Scheduler Publish] tick error")
            await asyncio.sleep(TICK_SECONDS)

    @classmethod
    async def tick(cls) -> None:
        logger.info("[Scheduler Publish] tick:")
        async with AsyncSessionLocal() as db:
            await PublishService.recover_stale_publishing(db)

        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            debug = await ScheduledPublishDiagnosticsService.list_scheduled_debug(db)
            ScheduledPublishDiagnosticsService.log_scheduler_debug(debug["items"])

        due_ids = await cls._find_due_content_ids(now)
        logger.info("[Scheduler Publish] due found: %s", len(due_ids))

        for content_id in due_ids:
            await cls._publish_due_item(content_id, now)

    @staticmethod
    async def _find_due_content_ids(now: datetime) -> list[UUID]:
        async with AsyncSessionLocal() as db:
            query = (
                select(ContentItem.id)
                .where(
                    ContentItem.status == "scheduled",
                    ContentItem.scheduled_for.isnot(None),
                    ContentItem.scheduled_for <= now,
                    ContentItem.approved_at.isnot(None),
                    func.cardinality(ContentItem.platforms) > 0,
                )
                .order_by(ContentItem.scheduled_for.asc())
                .limit(MAX_BATCH)
            )
            result = await db.execute(query)
            return list(result.scalars().all())

    @staticmethod
    def _skip_reason(item: ContentItem) -> str | None:
        if item.status != "scheduled":
            return f"status={item.status}"
        scheduled_for = item.scheduled_for
        if scheduled_for is None:
            return "no scheduled_for"
        if scheduled_for.tzinfo is None:
            scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
        if scheduled_for > datetime.now(timezone.utc):
            return "not yet due"
        return None

    @classmethod
    async def _try_claim(cls, db, content_id: UUID, now: datetime) -> ContentItem | None:
        """Atomically claim scheduled → publishing to avoid duplicate runs."""
        result = await db.execute(
            update(ContentItem)
            .where(
                ContentItem.id == content_id,
                ContentItem.status == "scheduled",
                ContentItem.scheduled_for.isnot(None),
                ContentItem.scheduled_for <= now,
                ContentItem.approved_at.isnot(None),
            )
            .values(status="publishing")
            .returning(ContentItem.id)
        )
        claimed_id = result.scalar_one_or_none()
        if not claimed_id:
            await db.rollback()
            return None
        await db.commit()

        loaded = await db.execute(
            select(ContentItem)
            .where(ContentItem.id == content_id)
            .options(
                selectinload(ContentItem.media_file),
                selectinload(ContentItem.client),
            )
        )
        return loaded.scalar_one_or_none()

    @classmethod
    async def _publish_due_item(cls, content_id: UUID, now: datetime) -> None:
        async with AsyncSessionLocal() as db:
            preview = await db.execute(
                select(ContentItem)
                .where(ContentItem.id == content_id)
                .options(
                    selectinload(ContentItem.media_file),
                    selectinload(ContentItem.client),
                )
            )
            item = preview.scalar_one_or_none()
            if not item:
                return
            reason = cls._skip_reason(item)
            if reason:
                logger.info(
                    "[Scheduler Publish] skipped: content=%s reason=%s",
                    content_id,
                    reason,
                )
                return

            safety = await PublishSafetyService.evaluate(
                db,
                item,
                target_platforms=list(item.platforms or []),
                mode="scheduled_publish",
            )
            if not safety["passed"]:
                await PublishSafetyService.record_blocked(
                    db,
                    content_id,
                    safety["errors"],
                    target_platforms=list(item.platforms or []),
                )
                logger.info(
                    "[Scheduler Publish] blocked: content=%s reason=%s",
                    content_id,
                    safety["message"],
                )
                return

        async with AsyncSessionLocal() as db:
            claimed = await cls._try_claim(db, content_id, now)
            if not claimed:
                logger.info(
                    "[Scheduler Publish] skipped: content=%s reason=already claimed or not due",
                    content_id,
                )
                return

            logger.info(
                "[Scheduler Publish] started: content=%s scheduled_for=%s platforms=%s",
                content_id,
                claimed.scheduled_for,
                claimed.platforms,
            )

            try:
                result = await PublishService.publish_content(
                    db,
                    content_id,
                    request=PublishContentRequest(test=False, mode="scheduled_publish"),
                    from_scheduler=True,
                )
                status = result.get("status")
                if result.get("all_success"):
                    logger.info(
                        "[Scheduler Publish] success: content=%s status=%s",
                        content_id,
                        status,
                    )
                else:
                    logger.info(
                        "[Scheduler Publish] failed: content=%s status=%s results=%s",
                        content_id,
                        status,
                        [r.get("platform") for r in result.get("results", [])],
                    )
            except HTTPException as exc:
                logger.info(
                    "[Scheduler Publish] failed: content=%s error=%s",
                    content_id,
                    exc.detail,
                )
                await cls._release_to_scheduled(content_id)
            except Exception as exc:
                logger.exception(
                    "[Scheduler Publish] failed: content=%s error=%s",
                    content_id,
                    exc,
                )
                await cls._release_to_scheduled(content_id)

    @staticmethod
    async def _release_to_scheduled(content_id: UUID) -> None:
        """Revert publishing → scheduled when scheduler publish aborted before attempts."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ContentItem).where(ContentItem.id == content_id)
            )
            item = result.scalar_one_or_none()
            if item and item.status == "publishing" and item.published_at is None:
                item.status = "scheduled"
                await db.commit()
