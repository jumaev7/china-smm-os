"""AI Task Executor — one-click safe execution of operator tasks."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.models.operator_task import OperatorTask
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.client_review_telegram_service import send_telegram_message
from app.services.content_service import ContentService
from app.services.media_request_service import MediaRequestService
from app.services.operator_inbox_service import OperatorInboxService
from app.services.operator_smart_inbox_service import parse_platforms_json
from app.services.operator_task_service import TERMINAL_STATUSES
from app.services.telegram_instruction_service import apply_group_instruction

logger = logging.getLogger(__name__)

EXECUTION_STATUSES = frozenset({"success", "failed", "pending"})
EXECUTABLE_ACTIONS = frozenset({
    "create_content",
    "request_media",
    "edit_content",
    "suggest_reply",
})

_REPLY_INTENTS = frozenset({"question", "unclear", "complaint", "pricing_billing"})
_CREATE_INTENTS = frozenset({"new_content_request", "schedule_request", "media_upload"})

_SUGGEST_REPLY_SYSTEM = """\
You draft a short reply to a client in a Telegram group for an SMM agency operator to review.
Return ONLY JSON: {"reply_text": "..."}

Rules:
- Warm, professional tone; match client language (Russian if unclear)
- Never promise automatic publishing or approval
- Never mention AI, inbox, or internal systems
- Under 400 characters
- Operator will review before sending — be helpful but cautious
"""


def _parse_execution_result(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _dump_execution_result(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _serialize_task(task: OperatorTask) -> dict[str, Any]:
    from app.services.operator_task_service import _serialize
    return _serialize(task)


async def _load_inbox_entry(
    db: AsyncSession,
    inbox_id: UUID,
) -> TelegramGroupBufferMessage | None:
    result = await db.execute(
        select(TelegramGroupBufferMessage)
        .options(selectinload(TelegramGroupBufferMessage.client))
        .where(TelegramGroupBufferMessage.id == inbox_id)
    )
    return result.scalar_one_or_none()


async def _resolve_action(
    db: AsyncSession,
    task: OperatorTask,
    inbox_entry: TelegramGroupBufferMessage | None,
) -> str:
    intent = (inbox_entry.account_manager_intent if inbox_entry else None) or ""

    if task.source_type == "media_request":
        return "request_media"

    if intent in _REPLY_INTENTS:
        return "suggest_reply"
    if intent == "change_request":
        return "edit_content"
    if intent in _CREATE_INTENTS:
        return "create_content"

    title = (task.title or "").lower()
    desc = (task.description or "").lower()

    if task.linked_content_id:
        try:
            content = await ContentService.get(db, task.linked_content_id)
            if not content.media_file_id and (
                "media" in desc or "material" in desc or task.source_type == "media_request"
            ):
                return "request_media"
        except HTTPException:
            pass

    if "change" in title or "edit" in desc:
        return "edit_content"
    if "content request" in title or "schedule" in title or "media upload" in title:
        return "create_content"
    if task.source_type == "telegram_inbox" and task.source_id:
        if task.linked_content_id:
            return "edit_content"
        return "create_content"
    if task.linked_content_id:
        return "edit_content"
    return "suggest_reply"


async def _generate_suggested_reply(
    db: AsyncSession,
    *,
    client: Client,
    inbox_entry: TelegramGroupBufferMessage | None,
    task: OperatorTask,
) -> str:
    client_text = (inbox_entry.text or "").strip() if inbox_entry else ""
    intent = (inbox_entry.account_manager_intent if inbox_entry else None) or "unclear"
    summary = (
        (inbox_entry.account_manager_summary if inbox_entry else None)
        or task.description
        or task.title
    )

    if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
        from app.services.account_manager_service import _DEFAULT_REPLIES
        base = _DEFAULT_REPLIES.get(intent, _DEFAULT_REPLIES["unclear"])
        if client_text:
            return f"{base} (По вашему сообщению: «{client_text[:120]}»)"
        return base

    _validate_api_key()
    kb_block = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, max_chars=2000, context="account_manager",
    )
    user_parts = [
        f"Client: {client.company_name}",
        f"Intent: {intent}",
        f"Summary: {summary}",
    ]
    if client_text:
        user_parts.append(f"Client message:\n{client_text[:1500]}")
    if task.description:
        user_parts.append(f"Operator action note: {task.description[:500]}")
    if kb_block:
        user_parts.append(kb_block)

    client_ai = get_openai()
    response = await client_ai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SUGGEST_REPLY_SYSTEM},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
        temperature=0.4,
        max_tokens=400,
        response_format={"type": "json_object"},
    )
    parsed = _extract_json(response.choices[0].message.content or "{}")
    reply = str(parsed.get("reply_text") or "").strip()
    if not reply:
        raise ValueError("Empty suggested reply from AI")
    return reply


class TaskExecutorService:
    @staticmethod
    async def execute(db: AsyncSession, task_id: UUID) -> dict[str, Any]:
        task = await TaskExecutorService._load_task(db, task_id)
        if task.status in TERMINAL_STATUSES:
            raise HTTPException(status_code=400, detail="Cannot execute a completed or canceled task")

        client = task.client
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        inbox_entry: TelegramGroupBufferMessage | None = None
        if task.source_type == "telegram_inbox" and task.source_id:
            inbox_entry = await _load_inbox_entry(db, task.source_id)

        action = await _resolve_action(db, task, inbox_entry)
        logger.info("[Task Executor] started: task=%s action=%s", task.id, action)
        logger.info("[Task Executor] action: task=%s action=%s", task.id, action)

        task.execution_status = "pending"
        await db.flush()

        try:
            result = await TaskExecutorService._run_action(
                db,
                task=task,
                client=client,
                inbox_entry=inbox_entry,
                action=action,
            )
            task.execution_status = "success"
            task.execution_result = _dump_execution_result(result)
            task.executed_at = datetime.now(timezone.utc)
            task.updated_at = datetime.now(timezone.utc)

            new_status = result.get("task_status")
            if new_status and new_status in {"todo", "in_progress", "waiting_client", "done"}:
                task.status = new_status

            content_id = result.get("content_id")
            if content_id:
                task.linked_content_id = UUID(str(content_id))

            await db.commit()
            await db.refresh(task, attribute_names=["client"])

            return {
                "ok": True,
                "action": action,
                "message": result.get("message", "Task executed"),
                "content_id": content_id,
                "suggested_reply": result.get("suggested_reply"),
                "task": _serialize_task(task),
            }
        except HTTPException:
            await db.rollback()
            task = await TaskExecutorService._load_task(db, task_id)
            raise
        except Exception as exc:
            await db.rollback()
            task = await TaskExecutorService._load_task(db, task_id)
            fail_result = {
                "action": action,
                "message": str(exc),
                "error": str(exc),
            }
            task.execution_status = "failed"
            task.execution_result = _dump_execution_result(fail_result)
            task.executed_at = datetime.now(timezone.utc)
            task.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(task, attribute_names=["client"])
            logger.warning("[Task Executor] failed: task=%s error=%s", task_id, exc)
            return {
                "ok": False,
                "action": action,
                "message": str(exc),
                "content_id": None,
                "suggested_reply": None,
                "task": _serialize_task(task),
            }

    @staticmethod
    async def send_reply(
        db: AsyncSession,
        task_id: UUID,
        *,
        reply_text: str | None = None,
    ) -> dict[str, Any]:
        task = await TaskExecutorService._load_task(db, task_id)
        client = task.client
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        stored = _parse_execution_result(task.execution_result) or {}
        text = (reply_text or stored.get("suggested_reply") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="No suggested reply to send")

        if stored.get("reply_sent"):
            raise HTTPException(status_code=409, detail="Reply already sent for this task")

        group_id = (client.telegram_group_id or "").strip()
        if not group_id:
            raise HTTPException(status_code=400, detail="Client has no Telegram group linked")

        ok, err = await send_telegram_message(group_id, text)
        if not ok:
            logger.warning("[Task Executor] failed: task=%s send_reply error=%s", task_id, err)
            raise HTTPException(status_code=502, detail=f"Failed to send Telegram message: {err}")

        stored["suggested_reply"] = text
        stored["reply_sent"] = True
        stored["reply_sent_at"] = datetime.now(timezone.utc).isoformat()
        task.execution_result = _dump_execution_result(stored)
        task.updated_at = datetime.now(timezone.utc)
        if task.status == "waiting_client":
            task.status = "in_progress"
        await db.commit()
        await db.refresh(task, attribute_names=["client"])

        logger.info("[Task Executor] reply sent: task=%s group=%s", task_id, group_id)
        return {
            "ok": True,
            "message": "Reply sent to client Telegram group",
            "task": _serialize_task(task),
        }

    @staticmethod
    async def _run_action(
        db: AsyncSession,
        *,
        task: OperatorTask,
        client: Client,
        inbox_entry: TelegramGroupBufferMessage | None,
        action: str,
    ) -> dict[str, Any]:
        if action == "create_content":
            return await TaskExecutorService._execute_create_content(
                db, task=task, client=client, inbox_entry=inbox_entry,
            )
        if action == "request_media":
            return await TaskExecutorService._execute_request_media(
                db, task=task, client=client, inbox_entry=inbox_entry,
            )
        if action == "edit_content":
            return await TaskExecutorService._execute_edit_content(
                db, task=task, client=client, inbox_entry=inbox_entry,
            )
        if action == "suggest_reply":
            return await TaskExecutorService._execute_suggest_reply(
                db, task=task, client=client, inbox_entry=inbox_entry,
            )
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    @staticmethod
    async def _execute_create_content(
        db: AsyncSession,
        *,
        task: OperatorTask,
        client: Client,
        inbox_entry: TelegramGroupBufferMessage | None,
    ) -> dict[str, Any]:
        if task.linked_content_id:
            logger.info(
                "[Task Executor] draft created: task=%s content=%s reason=already_linked",
                task.id,
                task.linked_content_id,
            )
            return {
                "action": "create_content",
                "message": "Draft already linked to this task",
                "content_id": str(task.linked_content_id),
                "task_status": "in_progress",
            }

        if inbox_entry and inbox_entry.linked_content_id:
            content_id = inbox_entry.linked_content_id
            task.linked_content_id = content_id
            logger.info(
                "[Task Executor] draft created: task=%s content=%s reason=inbox_linked",
                task.id,
                content_id,
            )
            return {
                "action": "create_content",
                "message": "Draft already exists for this inbox item",
                "content_id": str(content_id),
                "task_status": "in_progress",
            }

        if not inbox_entry or not task.source_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot create draft — no Telegram inbox source linked to this task",
            )

        platforms = parse_platforms_json(inbox_entry.suggested_platforms_json)
        scheduled_for = inbox_entry.suggested_publish_date

        result = await OperatorInboxService.create_content_from_inbox(
            db,
            task.source_id,
            platforms=platforms or None,
            scheduled_for=scheduled_for,
            instruction="[Task Executor] Created from operator task",
            ai_note=task.description or "Created by AI Task Executor — admin review required.",
        )
        content_id = result.get("content_id")
        if not content_id:
            raise HTTPException(status_code=500, detail="Draft creation did not return content_id")

        logger.info("[Task Executor] draft created: task=%s content=%s", task.id, content_id)
        return {
            "action": "create_content",
            "message": "Draft content created — review before publish",
            "content_id": str(content_id),
            "task_status": "in_progress",
        }

    @staticmethod
    async def _execute_request_media(
        db: AsyncSession,
        *,
        task: OperatorTask,
        client: Client,
        inbox_entry: TelegramGroupBufferMessage | None,
    ) -> dict[str, Any]:
        content_id = task.linked_content_id
        if not content_id and inbox_entry and inbox_entry.linked_content_id:
            content_id = inbox_entry.linked_content_id

        if not content_id:
            created = await TaskExecutorService._execute_create_content(
                db, task=task, client=client, inbox_entry=inbox_entry,
            )
            content_id = UUID(str(created["content_id"]))
            task.linked_content_id = content_id

        result = await MediaRequestService.request_media(db, content_id)
        logger.info(
            "[Task Executor] media request sent: task=%s content=%s",
            task.id,
            content_id,
        )
        return {
            "action": "request_media",
            "message": result.get("message", "Media request sent to client"),
            "content_id": str(content_id),
            "media_request_message": result.get("media_request_message"),
            "task_status": "waiting_client",
        }

    @staticmethod
    async def _execute_edit_content(
        db: AsyncSession,
        *,
        task: OperatorTask,
        client: Client,
        inbox_entry: TelegramGroupBufferMessage | None,
    ) -> dict[str, Any]:
        content_id = (
            task.linked_content_id
            or (inbox_entry.linked_content_id if inbox_entry else None)
            or (inbox_entry.account_manager_related_content_id if inbox_entry else None)
            or client.telegram_active_content_id
        )
        if not content_id:
            if inbox_entry and task.source_id:
                created = await TaskExecutorService._execute_create_content(
                    db, task=task, client=client, inbox_entry=inbox_entry,
                )
                content_id = UUID(str(created["content_id"]))
            else:
                raise HTTPException(
                    status_code=400,
                    detail="No linked content to edit — link a draft first",
                )

        result = await db.execute(
            select(ContentItem).where(
                ContentItem.id == content_id,
                ContentItem.client_id == client.id,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Content not found for this client")

        client_feedback = (inbox_entry.text or "").strip() if inbox_entry else ""
        instruction = task.description or "Apply client change request"
        if client_feedback:
            instruction = f"{instruction}\n\nClient message:\n{client_feedback[:2000]}"

        summary = await apply_group_instruction(
            db,
            client=client,
            content_item=item,
            instruction=f"[Task Executor] {instruction}",
            admin_name="task_executor",
            reply_to_message={"text": client_feedback} if client_feedback else None,
        )

        note = f"[Task Executor] {summary}"
        notes = item.internal_notes or ""
        item.internal_notes = f"{notes}\n{note}".strip() if notes else note
        await db.flush()

        logger.info("[Task Executor] draft created: task=%s content=%s action=edit", task.id, content_id)
        return {
            "action": "edit_content",
            "message": f"Draft updated — {summary}",
            "content_id": str(content_id),
            "edit_summary": summary,
            "task_status": "in_progress",
        }

    @staticmethod
    async def _execute_suggest_reply(
        db: AsyncSession,
        *,
        task: OperatorTask,
        client: Client,
        inbox_entry: TelegramGroupBufferMessage | None,
    ) -> dict[str, Any]:
        reply = await _generate_suggested_reply(
            db, client=client, inbox_entry=inbox_entry, task=task,
        )
        logger.info("[Task Executor] reply suggested: task=%s", task.id)
        return {
            "action": "suggest_reply",
            "message": "Suggested reply ready for operator review",
            "suggested_reply": reply,
            "reply_sent": False,
            "task_status": "waiting_client",
        }

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
