"""Audit quick fixes — explicit, safe operator actions."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.services.content_review_service import client_review_required, is_client_approved
from app.services.publishing_queue_service import PublishingQueueService
from app.services.system_health_service import SystemHealthService

logger = logging.getLogger(__name__)

AUDIT_REVIEWED_MARKER = "[Audit reviewed]"

CHECK_FIX_ACTIONS: dict[str, tuple[str, str]] = {
    "content.scheduled_not_admin": ("cancel_schedule", "Cancel schedule"),
    "content.scheduled_not_client": ("send_client_review", "Send client review"),
    "billing.missing_plan": ("open_billing", "Open billing"),
    "publishing.failed_attempts": ("retry_publish", "Retry publish"),
    "system.demo_data": ("seed_demo_data", "Seed demo data"),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_issue_id(check_key: str, entity_type: str, entity_id: UUID | str | None) -> str:
    raw = str(entity_id) if entity_id else "_"
    return f"{check_key}:{entity_type}:{raw}"


def parse_issue_id(issue_id: str) -> tuple[str, str, UUID | None]:
    parts = issue_id.split(":", 2)
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Invalid issue_id format")
    check_key, entity_type, raw_id = parts
    entity_uuid = None if raw_id == "_" else UUID(raw_id)
    return check_key, entity_type, entity_uuid


class AuditFixService:
    @staticmethod
    async def apply(db: AsyncSession, issue_id: str) -> dict:
        check_key, entity_type, entity_id = parse_issue_id(issue_id)
        expected = CHECK_FIX_ACTIONS.get(check_key)
        if not expected:
            logger.info("[Audit Fix] failed: issue_id=%s reason=unsupported_check", issue_id)
            raise HTTPException(status_code=400, detail=f"No quick fix for check: {check_key}")

        fix_action_type, _label = expected
        logger.info(
            "[Audit Fix] requested: issue_id=%s action=%s entity_type=%s entity_id=%s",
            issue_id,
            fix_action_type,
            entity_type,
            entity_id,
        )

        try:
            if fix_action_type == "cancel_schedule":
                result = await AuditFixService._cancel_schedule(db, entity_id, check_key)
            elif fix_action_type == "send_client_review":
                result = await AuditFixService._send_client_review(db, entity_id, check_key)
            elif fix_action_type == "open_billing":
                result = await AuditFixService._open_billing(db, entity_id, check_key)
            elif fix_action_type == "retry_publish":
                result = await AuditFixService._retry_publish(db, entity_id, entity_type, check_key)
            elif fix_action_type == "seed_demo_data":
                result = await AuditFixService._seed_demo_data(db, check_key)
            elif fix_action_type == "mark_failed_attempt_reviewed":
                result = await AuditFixService._mark_failed_attempt_reviewed(db, entity_id, check_key)
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported fix action: {fix_action_type}")

            logger.info(
                "[Audit Fix] applied: issue_id=%s action=%s ok=%s",
                issue_id,
                fix_action_type,
                result.get("ok"),
            )
            result["fix_action_type"] = fix_action_type
            return result
        except HTTPException:
            logger.info("[Audit Fix] failed: issue_id=%s action=%s", issue_id, fix_action_type)
            raise
        except Exception as exc:
            logger.warning(
                "[Audit Fix] failed: issue_id=%s action=%s error=%s",
                issue_id,
                fix_action_type,
                exc,
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @staticmethod
    async def _get_content(db: AsyncSession, content_id: UUID | None) -> ContentItem:
        if not content_id:
            raise HTTPException(status_code=400, detail="Content id required")
        result = await db.execute(select(ContentItem).where(ContentItem.id == content_id))
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Content not found")
        return item

    @staticmethod
    async def _cancel_schedule(db: AsyncSession, content_id: UUID | None, check_key: str) -> dict:
        if check_key != "content.scheduled_not_admin":
            raise HTTPException(status_code=400, detail="Cancel schedule not allowed for this issue")
        item = await AuditFixService._get_content(db, content_id)
        if item.status != "scheduled":
            raise HTTPException(status_code=400, detail="Content is not scheduled")
        result = await PublishingQueueService.cancel_schedule(db, content_id)
        return {
            "ok": bool(result.get("ok")),
            "message": result.get("message", "Schedule cancelled"),
            "entity_type": "content",
            "entity_id": str(content_id),
            "result": result,
        }

    @staticmethod
    async def _send_client_review(db: AsyncSession, content_id: UUID | None, check_key: str) -> dict:
        if check_key != "content.scheduled_not_client":
            raise HTTPException(status_code=400, detail="Send client review not allowed for this issue")
        item = await AuditFixService._get_content(db, content_id)
        if item.status != "scheduled":
            raise HTTPException(status_code=400, detail="Content is not scheduled")
        needs_client = client_review_required(item) or (
            item.client_review_status and not is_client_approved(item)
        )
        if not needs_client:
            raise HTTPException(status_code=400, detail="Client review is not pending for this content")
        result = await PublishingQueueService.send_client_review(db, content_id)
        return {
            "ok": bool(result.get("ok")),
            "message": result.get("message", "Client review sent"),
            "entity_type": "content",
            "entity_id": str(content_id),
            "result": result,
        }

    @staticmethod
    async def _open_billing(db: AsyncSession, client_id: UUID | None, check_key: str) -> dict:
        if check_key != "billing.missing_plan" or not client_id:
            raise HTTPException(status_code=400, detail="Open billing not allowed for this issue")
        result = await db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        if client.plan_name:
            raise HTTPException(status_code=400, detail="Client already has a billing plan")
        return {
            "ok": True,
            "message": "Open client billing settings to assign a plan",
            "entity_type": "client",
            "entity_id": str(client_id),
            "navigate_to": f"/clients/{client_id}",
        }

    @staticmethod
    async def _retry_publish(
        db: AsyncSession,
        entity_id: UUID | None,
        entity_type: str,
        check_key: str,
    ) -> dict:
        if check_key != "publishing.failed_attempts":
            raise HTTPException(status_code=400, detail="Retry publish not allowed for this issue")

        content_id: UUID
        if entity_type == "publish_attempt":
            if not entity_id:
                raise HTTPException(status_code=400, detail="Publish attempt id required")
            attempt_result = await db.execute(
                select(PublishAttempt).where(PublishAttempt.id == entity_id)
            )
            attempt = attempt_result.scalar_one_or_none()
            if not attempt:
                raise HTTPException(status_code=404, detail="Publish attempt not found")
            if attempt.status != "failed":
                raise HTTPException(status_code=400, detail="Publish attempt is not failed")
            if attempt.response and AUDIT_REVIEWED_MARKER in attempt.response:
                raise HTTPException(status_code=400, detail="Publish attempt already reviewed")
            content_id = attempt.content_id
        elif entity_type == "content":
            content_id = entity_id  # type: ignore[assignment]
            if not content_id:
                raise HTTPException(status_code=400, detail="Content id required")
        else:
            raise HTTPException(status_code=400, detail="Invalid entity for retry publish")

        result = await PublishingQueueService.retry_publish(db, content_id)
        return {
            "ok": bool(result.get("ok")),
            "message": result.get("message", "Retry publish finished"),
            "entity_type": "content",
            "entity_id": str(content_id),
            "result": result,
        }

    @staticmethod
    async def _seed_demo_data(db: AsyncSession, check_key: str) -> dict:
        if check_key != "system.demo_data":
            raise HTTPException(status_code=400, detail="Seed demo not allowed for this issue")
        result = await SystemHealthService.demo_seed(db)
        return {
            "ok": bool(result.get("created")),
            "message": result.get("message", "Demo seed finished"),
            "entity_type": "system",
            "entity_id": None,
            "result": result,
        }

    @staticmethod
    async def _mark_failed_attempt_reviewed(
        db: AsyncSession,
        attempt_id: UUID | None,
        check_key: str,
    ) -> dict:
        if check_key != "publishing.failed_attempts" or not attempt_id:
            raise HTTPException(status_code=400, detail="Mark reviewed not allowed for this issue")
        result = await db.execute(select(PublishAttempt).where(PublishAttempt.id == attempt_id))
        attempt = result.scalar_one_or_none()
        if not attempt:
            raise HTTPException(status_code=404, detail="Publish attempt not found")
        if attempt.status != "failed":
            raise HTTPException(status_code=400, detail="Only failed attempts can be marked reviewed")
        if attempt.response and AUDIT_REVIEWED_MARKER in attempt.response:
            raise HTTPException(status_code=400, detail="Publish attempt already reviewed")

        stamp = f"{AUDIT_REVIEWED_MARKER} at {_utc_now().isoformat()}"
        attempt.response = f"{attempt.response}\n{stamp}".strip() if attempt.response else stamp
        await db.commit()
        return {
            "ok": True,
            "message": "Failed publish attempt marked as reviewed",
            "entity_type": "publish_attempt",
            "entity_id": str(attempt_id),
        }
