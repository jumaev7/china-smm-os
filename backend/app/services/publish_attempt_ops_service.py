"""Admin operations for publish attempt resilience."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client import Client
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.schemas.publishing import PublishContentRequest
from app.services.publish_resilience import (
    OPS_LIST_STATUSES,
    STATUS_EXHAUSTED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
    PublishResilienceService,
    utc_now,
)
from app.services.publish_service import PublishService
from app.services.publishing_tenant_scope import tenant_id_for_content_optional

logger = logging.getLogger(__name__)


class PublishAttemptOpsService:
    @staticmethod
    async def _tenant_filter(tenant_id: UUID | None):
        if tenant_id is None:
            return True
        return Client.tenant_id == tenant_id

    @classmethod
    async def list_attempts(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        status: str | None = None,
        platform: str | None = None,
        content_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        statuses = (
            {status}
            if status
            else set(OPS_LIST_STATUSES) | {STATUS_SUCCESS, STATUS_FAILED}
        )
        # Default operator view focuses on problem states.
        if status is None:
            statuses = set(OPS_LIST_STATUSES)

        query = (
            select(PublishAttempt, ContentItem, Client)
            .join(ContentItem, ContentItem.id == PublishAttempt.content_id)
            .join(Client, Client.id == ContentItem.client_id)
            .options(selectinload(PublishAttempt.account))
            .where(PublishAttempt.status.in_(tuple(statuses)))
            .order_by(PublishAttempt.created_at.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 200)))
        )
        if tenant_id is not None:
            query = query.where(Client.tenant_id == tenant_id)
        if platform:
            query = query.where(PublishAttempt.platform == platform)
        if content_id:
            query = query.where(PublishAttempt.content_id == content_id)

        rows = list((await db.execute(query)).all())
        items = []
        counts: dict[str, int] = {}
        for attempt, content, client in rows:
            serialized = PublishResilienceService.serialize_attempt(attempt)
            serialized["company_name"] = client.company_name
            serialized["content_status"] = content.status
            serialized["tenant_id"] = client.tenant_id
            items.append(serialized)
            counts[attempt.status] = counts.get(attempt.status, 0) + 1

        return {
            "current_time": utc_now(),
            "items": items,
            "total": len(items),
            "counts": counts,
        }

    @classmethod
    async def get_attempt(
        cls,
        db: AsyncSession,
        attempt_id: UUID,
        *,
        tenant_id: UUID | None = None,
    ) -> dict:
        attempt = await cls._load_attempt(db, attempt_id, tenant_id=tenant_id)
        serialized = PublishResilienceService.serialize_attempt(attempt)
        content = await PublishService._get_content(db, attempt.content_id)
        serialized["content_status"] = content.status
        return serialized

    @classmethod
    async def _load_attempt(
        cls,
        db: AsyncSession,
        attempt_id: UUID,
        *,
        tenant_id: UUID | None = None,
    ) -> PublishAttempt:
        result = await db.execute(
            select(PublishAttempt)
            .join(ContentItem, ContentItem.id == PublishAttempt.content_id)
            .join(Client, Client.id == ContentItem.client_id)
            .where(PublishAttempt.id == attempt_id)
            .options(selectinload(PublishAttempt.account))
        )
        attempt = result.scalar_one_or_none()
        if attempt is None:
            raise HTTPException(status_code=404, detail="Publish attempt not found")

        content = await PublishService._get_content(db, attempt.content_id)
        content_tenant = await tenant_id_for_content_optional(db, content)
        if tenant_id is not None and content_tenant != tenant_id:
            raise HTTPException(status_code=404, detail="Publish attempt not found")
        return attempt

    @classmethod
    async def manual_retry(
        cls,
        db: AsyncSession,
        attempt_id: UUID,
        *,
        tenant_id: UUID | None = None,
    ) -> dict:
        attempt = await cls._load_attempt(db, attempt_id, tenant_id=tenant_id)
        allowed, reason = PublishResilienceService.manual_retry_allowed(attempt)
        if not allowed:
            return {
                "ok": False,
                "message": reason or "Manual retry unavailable",
                "attempt_id": attempt_id,
                "content_id": attempt.content_id,
                "status": attempt.status,
                "retry_blocked_reason": reason,
            }

        # Guard against duplicate external posts.
        if attempt.idempotency_key:
            prior = await PublishResilienceService.find_live_success(
                db, idempotency_key=attempt.idempotency_key,
            )
            if prior is not None:
                return {
                    "ok": False,
                    "message": "Destination already published — retry blocked to prevent duplicates",
                    "attempt_id": attempt_id,
                    "content_id": attempt.content_id,
                    "status": attempt.status,
                    "retry_blocked_reason": "already_published",
                    "existing_post_id": prior.external_post_id,
                }

        if attempt.status == STATUS_IN_PROGRESS:
            return {
                "ok": False,
                "message": "Publish is currently in progress",
                "attempt_id": attempt_id,
                "content_id": attempt.content_id,
                "status": attempt.status,
                "retry_blocked_reason": "in_progress",
            }

        # Clear scheduled auto-retry so manual path owns the next attempt.
        if attempt.status in (STATUS_RETRYING, STATUS_OPERATOR_REVIEW, STATUS_EXHAUSTED, STATUS_FAILED):
            attempt.next_retry_at = None
            if attempt.status == STATUS_RETRYING:
                attempt.status = STATUS_FAILED
                attempt.finished_at = utc_now()
            await db.flush()

        result = await PublishService.publish_content(
            db,
            attempt.content_id,
            request=PublishContentRequest(
                mode="manual_publish",
                platforms=[attempt.platform],
                account_id=attempt.account_id,
            ),
            platforms=[attempt.platform],
        )
        logger.info(
            "[PublishAttemptOps] manual retry attempt=%s content=%s success=%s",
            attempt_id,
            attempt.content_id,
            result.get("all_success"),
        )
        return {
            "ok": bool(result.get("all_success")),
            "message": (
                "Publish completed"
                if result.get("all_success")
                else "Publish finished with errors"
            ),
            "attempt_id": attempt_id,
            "content_id": attempt.content_id,
            "status": result.get("status"),
            "publish_result": result,
        }

    @classmethod
    async def due_retry_content_ids(cls, db: AsyncSession, *, limit: int = 20) -> list[UUID]:
        """Content IDs that have due automatic retries (unique, ordered)."""
        now = utc_now()
        rows = list(
            (
                await db.scalars(
                    select(PublishAttempt.content_id)
                    .where(
                        PublishAttempt.status == STATUS_RETRYING,
                        PublishAttempt.retryable.is_(True),
                        PublishAttempt.next_retry_at.isnot(None),
                        PublishAttempt.next_retry_at <= now,
                    )
                    .order_by(PublishAttempt.next_retry_at.asc())
                    .limit(max(1, limit))
                )
            ).all()
        )
        # Preserve order while unique
        seen: set[UUID] = set()
        ordered: list[UUID] = []
        for content_id in rows:
            if content_id in seen:
                continue
            seen.add(content_id)
            ordered.append(content_id)
        return ordered
