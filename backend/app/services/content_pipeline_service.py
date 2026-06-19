"""Content pipeline — Kanban board and stage transitions."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.storage import storage
from app.models.campaign import Campaign
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.schemas.content_pipeline import PIPELINE_STAGES, PipelineStageTransitionRequest
from app.services.content_review_service import (
    CLIENT_REVIEW_APPROVED,
    CLIENT_REVIEW_PENDING,
    ContentReviewService,
    is_client_approved,
)
from app.services.content_service import ContentService
from app.services.publishing_queue_service import PublishingQueueService

logger = logging.getLogger(__name__)

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"internal_review", "failed"}),
    "internal_review": frozenset({"client_review", "draft", "failed"}),
    "client_review": frozenset({"approved", "draft", "failed"}),
    "approved": frozenset({"scheduled", "failed"}),
    "scheduled": frozenset({"failed", "draft"}),
    "published": frozenset({"failed"}),
    "failed": frozenset({"draft", "internal_review"}),
}


def _caption_preview(item: ContentItem) -> str | None:
    for field in ("caption_short_en", "caption_short_ru", "caption_short_uz", "internal_notes"):
        val = getattr(item, field, None)
        if val and str(val).strip():
            text = str(val).strip()
            return text[:100] + ("…" if len(text) > 100 else "")
    return None


def _resolve_stage(item: ContentItem, *, has_failed_attempt: bool) -> str:
    if item.status == "published":
        return "published"
    if item.status in ("failed", "partial_failed"):
        return "failed"
    if has_failed_attempt:
        return "failed"
    if item.status in ("scheduled", "publishing"):
        return "scheduled"
    if item.client_review_status in ("pending", "changes_requested"):
        return "client_review"
    if item.approved_at is not None:
        return "approved"
    if item.status in ("ready", "ready_for_approval", "changes_requested"):
        return "internal_review"
    return "draft"


def _allowed_next_stages(current: str) -> list[str]:
    return sorted(_ALLOWED_TRANSITIONS.get(current, frozenset()))


def _client_display_name(client: Any) -> str | None:
    if not client:
        return None
    for attr in ("company_name", "brand_name", "business_category"):
        value = getattr(client, attr, None)
        if value:
            return str(value)
    return None


def _serialize_card(
    item: ContentItem,
    *,
    pipeline_stage: str,
    has_failed_attempt: bool,
    campaign_names: dict[UUID, str],
) -> dict[str, Any]:
    thumb = None
    media_url = None
    if item.media_file:
        media_url = storage.get_url(item.media_file.storage_path)
        if item.media_file.thumbnail_path:
            thumb = storage.get_url(item.media_file.thumbnail_path)
        elif item.media_file.file_type == "image":
            thumb = media_url

    client_name = _client_display_name(item.client)
    campaign_name = campaign_names.get(item.campaign_id) if item.campaign_id else None

    return {
        "id": item.id,
        "client_id": item.client_id,
        "client_name": client_name,
        "campaign_id": item.campaign_id,
        "campaign_name": campaign_name,
        "platforms": list(item.platforms or []),
        "status": item.status,
        "pipeline_stage": pipeline_stage,
        "thumbnail_url": thumb,
        "media_url": media_url,
        "scheduled_for": item.scheduled_for,
        "client_review_status": item.client_review_status,
        "approved_at": item.approved_at,
        "published_at": item.published_at,
        "caption_preview": _caption_preview(item),
        "has_failed_publish_attempt": has_failed_attempt,
        "allowed_transitions": _allowed_next_stages(pipeline_stage),
    }


class ContentPipelineService:
    @staticmethod
    async def _failed_attempt_ids(db: AsyncSession, content_ids: list[UUID]) -> set[UUID]:
        if not content_ids:
            return set()
        r = await db.execute(
            select(PublishAttempt.content_id)
            .where(
                PublishAttempt.content_id.in_(content_ids),
                PublishAttempt.status == "failed",
            )
            .group_by(PublishAttempt.content_id)
        )
        return {row[0] for row in r.all()}

    @staticmethod
    async def board(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        campaign_id: UUID | None = None,
        platform: str | None = None,
        status: str | None = None,
        limit: int = 300,
    ) -> dict[str, Any]:
        q = (
            select(ContentItem)
            .options(
                selectinload(ContentItem.client),
                selectinload(ContentItem.media_file),
            )
            .order_by(ContentItem.updated_at.desc())
            .limit(limit)
        )
        if client_id:
            q = q.where(ContentItem.client_id == client_id)
        if campaign_id:
            q = q.where(ContentItem.campaign_id == campaign_id)
        if platform:
            q = q.where(ContentItem.platforms.contains([platform]))

        items = list((await db.execute(q)).scalars().all())
        failed_ids = await ContentPipelineService._failed_attempt_ids(db, [i.id for i in items])

        campaign_ids = {i.campaign_id for i in items if i.campaign_id}
        campaign_names: dict[UUID, str] = {}
        if campaign_ids:
            cr = await db.execute(select(Campaign).where(Campaign.id.in_(campaign_ids)))
            campaign_names = {c.id: c.name for c in cr.scalars().all()}

        stages: dict[str, list[dict[str, Any]]] = {s: [] for s in PIPELINE_STAGES}
        for item in items:
            has_failed = item.id in failed_ids
            stage = _resolve_stage(item, has_failed_attempt=has_failed)
            if status and stage != status:
                continue
            card = _serialize_card(
                item,
                pipeline_stage=stage,
                has_failed_attempt=has_failed,
                campaign_names=campaign_names,
            )
            stages[stage].append(card)

        counts = {s: len(stages[s]) for s in PIPELINE_STAGES}
        total = sum(counts.values())
        logger.info(
            "[Content Pipeline] board loaded: total=%s client=%s campaign=%s",
            total, client_id, campaign_id,
        )
        return {"stages": stages, "counts": counts, "total": total}

    @staticmethod
    async def _current_stage(db: AsyncSession, item: ContentItem) -> str:
        failed_ids = await ContentPipelineService._failed_attempt_ids(db, [item.id])
        return _resolve_stage(item, has_failed_attempt=item.id in failed_ids)

    @staticmethod
    async def transition_stage(
        db: AsyncSession,
        content_id: UUID,
        body: PipelineStageTransitionRequest,
    ) -> dict[str, Any]:
        item = await ContentService.get(db, content_id)
        target = body.stage
        if target not in PIPELINE_STAGES:
            raise HTTPException(status_code=400, detail="Invalid pipeline stage")

        failed_ids = await ContentPipelineService._failed_attempt_ids(db, [item.id])
        current = _resolve_stage(item, has_failed_attempt=item.id in failed_ids)

        if target == "published":
            logger.info("[Content Pipeline] blocked: content=%s target=published", content_id)
            raise HTTPException(
                status_code=400,
                detail="Manual transition to published is not allowed — use the publishing workflow",
            )

        if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            logger.info(
                "[Content Pipeline] blocked: content=%s from=%s to=%s",
                content_id, current, target,
            )
            raise HTTPException(
                status_code=400,
                detail=f"Transition from '{current}' to '{target}' is not allowed",
            )

        message: str | None = None

        if target == "draft":
            item.status = "draft"
            item.client_review_status = None
            item.scheduled_for = None

        elif target == "internal_review":
            item.status = "ready"

        elif target == "client_review":
            if item.status == "draft":
                item.status = "ready_for_approval"
            elif item.status not in ("ready", "ready_for_approval", "changes_requested"):
                item.status = "ready_for_approval"
            if not item.client_review_status or item.client_review_status == CLIENT_REVIEW_APPROVED:
                item.client_review_status = CLIENT_REVIEW_PENDING
            await db.flush()
            refreshed = await ContentReviewService._load_item_for_preview(db, content_id)
            await ContentReviewService.ensure_review_token(refreshed)
            preview = await ContentReviewService.try_send_client_review_preview(
                db, refreshed, trigger="pipeline", force=True,
            )
            if preview.get("sent"):
                message = "Client review preview sent"
            elif preview.get("skipped"):
                message = preview.get("reason") or "Client review already satisfied"
            else:
                message = preview.get("error") or "Client review preview not sent"

        elif target == "approved":
            if not is_client_approved(item) and item.client_review_status in (CLIENT_REVIEW_PENDING, "changes_requested"):
                item.client_review_status = CLIENT_REVIEW_APPROVED
            item.status = "approved"
            if not item.approved_at:
                item.approved_at = datetime.now(timezone.utc)
            message = "Content approved"

        elif target == "scheduled":
            if not body.scheduled_for:
                logger.info("[Content Pipeline] blocked: content=%s missing scheduled_for", content_id)
                raise HTTPException(status_code=400, detail="scheduled_for is required to move to scheduled")
            sched = body.scheduled_for
            if sched.tzinfo is None:
                sched = sched.replace(tzinfo=timezone.utc)
            item.scheduled_for = sched
            item.status = "scheduled"
            await db.flush()
            await ContentReviewService.after_content_scheduled(db, item)
            message = "Content scheduled"

        elif target == "failed":
            item.status = "failed"
            if body.reason:
                prefix = "[Pipeline failed]:"
                notes = item.internal_notes or ""
                line = f"{prefix} {body.reason.strip()}"
                item.internal_notes = f"{notes}\n{line}".strip() if notes else line
            message = "Marked as failed"

        await db.commit()
        refreshed = await ContentService.get(db, content_id)
        new_stage = await ContentPipelineService._current_stage(db, refreshed)
        logger.info(
            "[Content Pipeline] transition: content=%s from=%s to=%s status=%s",
            content_id, current, target, refreshed.status,
        )
        return {
            "ok": True,
            "content_id": content_id,
            "pipeline_stage": new_stage,
            "status": refreshed.status,
            "message": message,
        }

    @staticmethod
    async def retry_publish(db: AsyncSession, content_id: UUID) -> dict[str, Any]:
        result = await PublishingQueueService.retry_publish(db, content_id)
        return result
