"""Operator task board — CRUD and Account Manager upsert."""
from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.client import Client
from app.models.operator_task import OperatorTask
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.schemas.operator_task import OperatorTaskCreate, OperatorTaskUpdate
from app.services.client_service import ClientService
from app.services.operator_common import parse_schedule_iso

logger = logging.getLogger(__name__)

SOURCE_TYPES = frozenset({
    "telegram_inbox",
    "content",
    "media_request",
    "client_review",
    "manual",
    "sales_agent",
    "sales_assistant",
    "communication_hub",
    "unified_inbox",
    "proposal",
    "outreach",
    "sales_playbook",
    "whatsapp",
    "client_brief",
})
PRIORITIES = frozenset({"high", "medium", "low"})
STATUSES = frozenset({"todo", "in_progress", "waiting_client", "done", "canceled"})
CREATED_BY = frozenset({"ai_account_manager", "admin", "system"})
TERMINAL_STATUSES = frozenset({"done", "canceled"})

_INTENT_TITLES: dict[str, str] = {
    "new_content_request": "New content request",
    "change_request": "Content change request",
    "media_upload": "Review client media upload",
    "schedule_request": "Schedule content",
    "question": "Answer client question",
    "complaint": "Handle client complaint",
    "pricing_billing": "Pricing / billing inquiry",
    "unclear": "Clarify client request",
}

_WAITING_CLIENT_INTENTS = frozenset({"unclear", "question"})


def _serialize(task: OperatorTask) -> dict[str, Any]:
    company_name = task.client.company_name if task.client else None
    execution_result = None
    if task.execution_result:
        try:
            execution_result = json.loads(task.execution_result)
        except (json.JSONDecodeError, TypeError):
            execution_result = {"raw": task.execution_result}
    return {
        "id": task.id,
        "client_id": task.client_id,
        "company_name": company_name,
        "source_type": task.source_type,
        "source_id": task.source_id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "status": task.status,
        "due_at": task.due_at,
        "assigned_to": task.assigned_to,
        "created_by": task.created_by,
        "linked_content_id": task.linked_content_id,
        "execution_status": task.execution_status,
        "execution_result": execution_result,
        "executed_at": task.executed_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _title_for_inbox(entry: TelegramGroupBufferMessage) -> str:
    intent = entry.account_manager_intent or "unclear"
    return _INTENT_TITLES.get(intent, "Client message follow-up")


def _due_at_for_inbox(entry: TelegramGroupBufferMessage) -> datetime | None:
    if entry.suggested_publish_date:
        return entry.suggested_publish_date
    return parse_schedule_iso(entry.detected_deadline)


def _status_for_inbox(entry: TelegramGroupBufferMessage) -> str:
    intent = entry.account_manager_intent or "unclear"
    has_draft = bool(entry.linked_content_id or entry.auto_drafted)
    if has_draft:
        return "in_progress"
    if intent in _WAITING_CLIENT_INTENTS:
        return "waiting_client"
    return "todo"


def _action_needed(entry: TelegramGroupBufferMessage) -> bool:
    if not entry.account_manager_processed_at:
        return False
    intent = entry.account_manager_intent or "unclear"
    if intent == "media_upload" and entry.linked_content_id:
        return False
    return True


class OperatorTaskService:
    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        *,
        status: str | None = None,
        client_id: UUID | None = None,
        priority: str | None = None,
        source_type: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        query = (
            select(OperatorTask)
            .options(selectinload(OperatorTask.client))
            .order_by(
                OperatorTask.priority.desc(),
                OperatorTask.due_at.asc().nulls_last(),
                OperatorTask.updated_at.desc(),
            )
        )
        if client_id:
            query = query.where(OperatorTask.client_id == client_id)
        if status:
            query = query.where(OperatorTask.status == status)
        else:
            query = query.where(OperatorTask.status != "canceled")
        if priority:
            query = query.where(OperatorTask.priority == priority)
        if source_type:
            query = query.where(OperatorTask.source_type == source_type)

        count_q = select(func.count()).select_from(OperatorTask)
        if client_id:
            count_q = count_q.where(OperatorTask.client_id == client_id)
        if status:
            count_q = count_q.where(OperatorTask.status == status)
        else:
            count_q = count_q.where(OperatorTask.status != "canceled")
        if priority:
            count_q = count_q.where(OperatorTask.priority == priority)
        if source_type:
            count_q = count_q.where(OperatorTask.source_type == source_type)
        total = (await db.execute(count_q)).scalar_one()

        result = await db.execute(query.offset(skip).limit(limit))
        items = [_serialize(t) for t in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def get_task(db: AsyncSession, task_id: UUID) -> dict[str, Any]:
        task = await OperatorTaskService._load_task(db, task_id)
        return _serialize(task)

    @staticmethod
    async def create_task(db: AsyncSession, data: OperatorTaskCreate) -> dict[str, Any]:
        await ClientService.get(db, data.client_id)
        if data.source_type not in SOURCE_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid source_type: {data.source_type}")
        if data.priority not in PRIORITIES:
            raise HTTPException(status_code=400, detail=f"Invalid priority: {data.priority}")
        if data.status not in STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {data.status}")
        if data.created_by not in CREATED_BY:
            raise HTTPException(status_code=400, detail=f"Invalid created_by: {data.created_by}")

        if data.source_id:
            existing = await OperatorTaskService._find_by_source(
                db, data.source_type, data.source_id,
            )
            if existing:
                logger.info(
                    "[Tasks] duplicate skipped: source=%s source_id=%s existing=%s",
                    data.source_type,
                    data.source_id,
                    existing.id,
                )
                raise HTTPException(
                    status_code=409,
                    detail="Task already exists for this source",
                )

        task = OperatorTask(
            client_id=data.client_id,
            source_type=data.source_type,
            source_id=data.source_id,
            title=data.title.strip(),
            description=data.description,
            priority=data.priority,
            status=data.status,
            due_at=data.due_at,
            assigned_to=data.assigned_to,
            created_by=data.created_by,
            linked_content_id=data.linked_content_id,
        )
        db.add(task)
        await db.flush()
        await db.refresh(task, attribute_names=["client"])
        logger.info("[Tasks] created: id=%s source=%s client=%s", task.id, task.source_type, task.client_id)
        return _serialize(task)

    @staticmethod
    async def update_task(
        db: AsyncSession,
        task_id: UUID,
        data: OperatorTaskUpdate,
    ) -> dict[str, Any]:
        task = await OperatorTaskService._load_task(db, task_id)
        old_status = task.status
        payload = data.model_dump(exclude_unset=True)

        if "priority" in payload and payload["priority"] not in PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority")
        if "status" in payload and payload["status"] not in STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        if "title" in payload:
            payload["title"] = payload["title"].strip()

        for key, value in payload.items():
            setattr(task, key, value)
        task.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(task, attribute_names=["client"])

        if old_status != task.status:
            logger.info(
                "[Tasks] status changed: id=%s %s -> %s",
                task.id,
                old_status,
                task.status,
            )
        logger.info("[Tasks] updated: id=%s", task.id)
        return _serialize(task)

    @staticmethod
    async def delete_task(db: AsyncSession, task_id: UUID) -> None:
        task = await OperatorTaskService._load_task(db, task_id)
        await db.delete(task)
        await db.flush()
        logger.info("[Tasks] deleted: id=%s", task_id)

    @staticmethod
    async def set_status(db: AsyncSession, task_id: UUID, status: str) -> dict[str, Any]:
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        task = await OperatorTaskService._load_task(db, task_id)
        old_status = task.status
        task.status = status
        task.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(task, attribute_names=["client"])
        if old_status != status:
            logger.info(
                "[Tasks] status changed: id=%s %s -> %s",
                task.id,
                old_status,
                status,
            )
        return _serialize(task)

    @staticmethod
    async def upsert_from_telegram_inbox(
        db: AsyncSession,
        entry: TelegramGroupBufferMessage,
        client: Client,
    ) -> dict[str, Any] | None:
        if not _action_needed(entry):
            return None

        source_type = "telegram_inbox"
        source_id = entry.id
        existing = await OperatorTaskService._find_by_source(db, source_type, source_id)

        if existing and existing.status in TERMINAL_STATUSES:
            logger.info(
                "[Tasks] duplicate skipped: source=%s source_id=%s status=%s",
                source_type,
                source_id,
                existing.status,
            )
            return None

        title = _title_for_inbox(entry)
        description = entry.account_manager_recommended_action or entry.account_manager_summary
        priority = entry.account_manager_priority or entry.priority or "medium"
        if priority not in PRIORITIES:
            priority = "medium"
        status = _status_for_inbox(entry)
        due_at = _due_at_for_inbox(entry)
        linked_content_id = entry.linked_content_id or entry.account_manager_related_content_id

        if existing:
            old_status = existing.status
            existing.title = title
            existing.description = description
            existing.priority = priority
            existing.status = status
            existing.due_at = due_at
            existing.linked_content_id = linked_content_id
            existing.updated_at = datetime.now(timezone.utc)
            await db.flush()
            await db.refresh(existing, attribute_names=["client"])
            logger.info("[Tasks] updated: id=%s source=%s", existing.id, source_type)
            if old_status != status:
                logger.info(
                    "[Tasks] status changed: id=%s %s -> %s",
                    existing.id,
                    old_status,
                    status,
                )
            return _serialize(existing)

        task = OperatorTask(
            client_id=client.id,
            source_type=source_type,
            source_id=source_id,
            title=title,
            description=description,
            priority=priority,
            status=status,
            due_at=due_at,
            created_by="ai_account_manager",
            linked_content_id=linked_content_id,
        )
        db.add(task)
        await db.flush()
        await db.refresh(task, attribute_names=["client"])
        logger.info(
            "[Tasks] created: id=%s source=%s inbox=%s status=%s",
            task.id,
            source_type,
            entry.id,
            status,
        )
        return _serialize(task)

    @staticmethod
    async def tasks_by_source_ids(
        db: AsyncSession,
        source_type: str,
        source_ids: list[UUID],
    ) -> dict[UUID, OperatorTask]:
        if not source_ids:
            return {}
        result = await db.execute(
            select(OperatorTask)
            .where(
                OperatorTask.source_type == source_type,
                OperatorTask.source_id.in_(source_ids),
                OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
            )
            .order_by(OperatorTask.updated_at.desc())
        )
        mapping: dict[UUID, OperatorTask] = {}
        for task in result.scalars().all():
            if task.source_id and task.source_id not in mapping:
                mapping[task.source_id] = task
        return mapping

    @staticmethod
    async def _find_by_source(
        db: AsyncSession,
        source_type: str,
        source_id: UUID,
    ) -> OperatorTask | None:
        result = await db.execute(
            select(OperatorTask)
            .where(
                OperatorTask.source_type == source_type,
                OperatorTask.source_id == source_id,
            )
            .order_by(OperatorTask.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _load_task(db: AsyncSession, task_id: UUID) -> OperatorTask:
        result = await db.execute(
            select(OperatorTask)
            .options(selectinload(OperatorTask.client))
            .where(OperatorTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
