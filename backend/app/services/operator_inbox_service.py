"""Operator inbox — buffered Telegram client materials before content creation."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.endpoint_guard import safe_section
from app.core.storage import storage
from app.models.client import Client
from app.models.content import ContentItem
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.schemas.operator_inbox import OperatorInboxAiSuggestion
from app.services.operator_ai_service import (
    OperatorAiService,
    can_apply_suggestion,
    load_cached_suggestion,
    resolve_media_from_suggestion,
)
from app.services.operator_common import (
    CLIENT_SENDER_ROLES,
    INBOX_IGNORED,
    INBOX_NEW,
    INBOX_USED,
    TG_INBOX_AUTO_DRAFT_SOURCE,
    effective_inbox_status,
    find_content_linked_to_buffer,
    parse_schedule_iso,
)
from app.services.telegram_group_agent_service import (
    _load_buffer_entries,
    _scoped_client_entries_for_reply,
    create_content_from_buffer_selection,
    mark_buffer_entries_linked,
)
from app.services.telegram_instruction_service import set_admin_instruction
from app.services.operator_smart_inbox_service import (
    ensure_auto_groups,
    parse_platforms_json,
    primary_in_group,
)

logger = logging.getLogger(__name__)


def _safe_cached_suggestion(entry: TelegramGroupBufferMessage) -> dict | None:
    raw = load_cached_suggestion(entry)
    if not raw:
        return None
    try:
        return OperatorInboxAiSuggestion(**raw).model_dump()
    except Exception:
        return None


def _media_previews_for_entries(
    entries: list[TelegramGroupBufferMessage],
    *,
    limit: int = 6,
) -> tuple[int, list[dict]]:
    previews: list[dict] = []
    media_count = 0
    for entry in entries:
        if not entry.media_file_id:
            continue
        media_count += 1
        if len(previews) >= limit:
            continue
        url = storage.get_url(entry.storage_path) if entry.storage_path else None
        previews.append({
            "buffer_id": entry.id,
            "media_type": entry.message_type,
            "url": url,
            "text": (entry.text or "")[:120] or None,
        })
    return media_count, previews


def _build_inbox_row(
    entry: TelegramGroupBufferMessage,
    *,
    eff: str,
    linked_id: UUID | None,
    cached_ai: dict | None,
    group_members: list[TelegramGroupBufferMessage] | None,
    db_scope_media: tuple[int, list[dict]],
) -> dict:
    members = group_members or [entry]
    is_primary = entry.id == primary_in_group(members).id
    group_ids = [m.id for m in members]

    media_count, media_previews = db_scope_media
    client = entry.client
    needs_action = eff == INBOX_NEW and not linked_id

    row = {
        "id": entry.id,
        "client_id": entry.client_id,
        "company_name": client.company_name if client else "Unknown",
        "telegram_group_title": client.telegram_group_title if client else None,
        "message_text": (entry.text or "").strip() or None,
        "media_count": media_count,
        "media_previews": media_previews,
        "created_at": entry.created_at,
        "message_at": entry.message_at,
        "status": eff,
        "linked_content_id": linked_id,
        "ai_suggestion": cached_ai,
        "auto_drafted": bool(entry.auto_drafted),
        "ai_summary": entry.ai_summary,
        "priority": entry.priority,
        "suggested_publish_date": entry.suggested_publish_date,
        "suggested_platforms": parse_platforms_json(entry.suggested_platforms_json),
        "detected_deadline": entry.detected_deadline,
        "detected_offer": entry.detected_offer,
        "detected_language": entry.detected_language,
        "grouped_task_id": entry.grouped_task_id,
        "is_group_primary": is_primary,
        "group_message_count": len(members),
        "group_media_count": media_count,
        "group_inbox_ids": group_ids,
        "needs_action": needs_action,
        "related_to_media_request": False,
        "account_manager_intent": entry.account_manager_intent,
        "account_manager_summary": entry.account_manager_summary,
        "account_manager_recommended_action": entry.account_manager_recommended_action,
        "account_manager_priority": entry.account_manager_priority or entry.priority,
        "account_manager_reply_sent": bool(entry.account_manager_reply_sent),
        "account_manager_reply_text": entry.account_manager_reply_text,
        "account_manager_related_content_id": entry.account_manager_related_content_id,
        "operator_task_id": None,
        "operator_task_status": None,
        "operator_task_title": None,
    }
    return row


async def _group_media_totals(
    db: AsyncSession,
    members: list[TelegramGroupBufferMessage],
) -> tuple[int, list[dict]]:
    total_media = 0
    previews: list[dict] = []
    seen: set[UUID] = set()
    for member in members:
        group_entries = await _load_buffer_entries(db, member.client_id, member.group_id)
        scope = _scoped_client_entries_for_reply(group_entries, member)
        for e in scope:
            if e.media_file_id and e.id not in seen:
                seen.add(e.id)
                total_media += 1
                if len(previews) < 6:
                    url = storage.get_url(e.storage_path) if e.storage_path else None
                    previews.append({
                        "buffer_id": e.id,
                        "media_type": e.message_type,
                        "url": url,
                        "text": (e.text or "")[:120] or None,
                    })
    return total_media, previews


class OperatorInboxService:
    @staticmethod
    async def list_inbox(
        db: AsyncSession,
        *,
        status: str | None = None,
        client_id: UUID | None = None,
        priority: str | None = None,
        needs_action: bool | None = None,
        auto_drafted: bool | None = None,
        grouped: bool | None = None,
        limit: int = 100,
        skip: int = 0,
    ) -> dict:
        query = (
            select(TelegramGroupBufferMessage)
            .where(TelegramGroupBufferMessage.sender_role.in_(tuple(CLIENT_SENDER_ROLES)))
            .options(selectinload(TelegramGroupBufferMessage.client))
            .order_by(TelegramGroupBufferMessage.message_at.desc())
        )
        if client_id:
            query = query.where(TelegramGroupBufferMessage.client_id == client_id)

        result = await db.execute(query)
        all_entries = list(result.scalars().all())

        group_map = await ensure_auto_groups(db, all_entries)

        counts = {INBOX_NEW: 0, INBOX_USED: 0, INBOX_IGNORED: 0}
        filtered: list[tuple[TelegramGroupBufferMessage, str, UUID | None]] = []
        dirty = False

        for entry in all_entries:
            linked_id = entry.linked_content_id
            if not linked_id:
                linked = await find_content_linked_to_buffer(
                    db, entry.id, message_id=entry.message_id,
                )
                if linked:
                    linked_id = linked.id
                    entry.linked_content_id = linked_id
                    entry.inbox_status = INBOX_USED
                    dirty = True

            eff = effective_inbox_status(entry)
            counts[eff] = counts.get(eff, 0) + 1

            if status and eff != status:
                continue
            filtered.append((entry, eff, linked_id))

        if dirty:
            await db.commit()

        if dirty:
            await db.commit()

        members_by_id: dict[UUID, list[TelegramGroupBufferMessage]] = {}
        for gid, members in group_map.items():
            for m in members:
                members_by_id[m.id] = members
        for entry in all_entries:
            if entry.grouped_task_id and entry.id not in members_by_id:
                siblings = [e for e in all_entries if e.grouped_task_id == entry.grouped_task_id]
                if len(siblings) > 1:
                    for s in siblings:
                        members_by_id[s.id] = siblings

        primary_ids: set[UUID] = set()
        for members in members_by_id.values():
            primary_ids.add(primary_in_group(members).id)
        for entry in all_entries:
            if entry.id not in members_by_id:
                primary_ids.add(entry.id)

        filtered_primary: list[tuple[TelegramGroupBufferMessage, str, UUID | None]] = []
        for entry, eff, linked_id in filtered:
            if entry.id not in primary_ids:
                continue
            filtered_primary.append((entry, eff, linked_id))

        if priority:
            filtered_primary = [
                t for t in filtered_primary
                if (t[0].priority or "medium") == priority
            ]
        if needs_action is True:
            filtered_primary = [
                t for t in filtered_primary
                if t[1] == INBOX_NEW and not t[2]
            ]
        if auto_drafted is True:
            filtered_primary = [t for t in filtered_primary if t[0].auto_drafted]
        if grouped is True:
            filtered_primary = [
                t for t in filtered_primary
                if len(members_by_id.get(t[0].id, [t[0]])) > 1
            ]

        total = len(filtered_primary)
        page_slice = filtered_primary[skip : skip + limit]
        errors: list[str] = []

        async def _build_rows() -> list[dict]:
            rows: list[dict] = []
            linked_ids = [lid for _, _, lid in page_slice if lid]
            from app.services.media_request_service import MediaRequestService
            from app.services.operator_task_service import OperatorTaskService
            media_request_ids = await MediaRequestService.content_ids_with_media_request(
                db, linked_ids,
            )
            inbox_ids = [entry.id for entry, _, _ in page_slice]
            task_by_inbox = await OperatorTaskService.tasks_by_source_ids(
                db, "telegram_inbox", inbox_ids,
            )

            for entry, eff, linked_id in page_slice:
                members = members_by_id.get(entry.id, [entry])
                if len(members) > 1:
                    media_count, media_previews = await _group_media_totals(db, members)
                else:
                    group_entries = await _load_buffer_entries(db, entry.client_id, entry.group_id)
                    scope = _scoped_client_entries_for_reply(group_entries, entry)
                    media_count, media_previews = _media_previews_for_entries(scope)

                cached_ai = _safe_cached_suggestion(entry)
                row = _build_inbox_row(
                    entry,
                    eff=eff,
                    linked_id=linked_id,
                    cached_ai=cached_ai,
                    group_members=members,
                    db_scope_media=(media_count, media_previews),
                )
                if len(members) > 1:
                    row["group_media_count"] = media_count
                if linked_id and linked_id in media_request_ids:
                    row["related_to_media_request"] = True
                linked_task = task_by_inbox.get(entry.id)
                if linked_task:
                    row["operator_task_id"] = linked_task.id
                    row["operator_task_status"] = linked_task.status
                    row["operator_task_title"] = linked_task.title
                rows.append(row)
            return rows

        rows = await safe_section(
            "inbox_rows",
            _build_rows(),
            default=[],
            errors=errors,
            db=db,
        )

        return {
            "items": rows,
            "total": total,
            "counts": counts,
            "errors": errors,
        }

    @staticmethod
    async def _get_inbox_entry(
        db: AsyncSession,
        inbox_id: UUID,
    ) -> TelegramGroupBufferMessage:
        result = await db.execute(
            select(TelegramGroupBufferMessage)
            .options(selectinload(TelegramGroupBufferMessage.client))
            .where(TelegramGroupBufferMessage.id == inbox_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Inbox item not found")
        if entry.sender_role not in CLIENT_SENDER_ROLES:
            raise HTTPException(status_code=400, detail="Not a client buffer message")
        return entry

    @staticmethod
    async def _apply_content_metadata(
        db: AsyncSession,
        item: ContentItem,
        *,
        platforms: list[str] | None,
        scheduled_for: datetime | None,
        ai_note: str | None,
        note_prefix: str = "[Operator AI] ",
    ) -> None:
        if platforms:
            item.platforms = platforms
        if scheduled_for:
            item.scheduled_for = scheduled_for
        if ai_note:
            notes = item.internal_notes or ""
            line = f"{note_prefix}{ai_note}"
            item.internal_notes = f"{notes}\n{line}".strip() if notes else line
        await db.flush()

    @staticmethod
    async def create_content_from_inbox(
        db: AsyncSession,
        inbox_id: UUID,
        *,
        platforms: list[str] | None = None,
        scheduled_for: datetime | None = None,
        media_selection: dict[str, Any] | None = None,
        instruction: str | None = None,
        auto_draft: bool = False,
        ai_note: str | None = None,
        from_group: bool = False,
    ) -> dict:
        entry = await OperatorInboxService._get_inbox_entry(db, inbox_id)
        client = entry.client
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        if entry.linked_content_id:
            if auto_draft:
                logger.info(
                    "[Auto Draft] duplicate prevented: inbox=%s reason=linked_content",
                    inbox_id,
                )
            raise HTTPException(
                status_code=409,
                detail="Content already linked to this inbox item",
            )

        if auto_draft and entry.auto_drafted:
            logger.info(
                "[Auto Draft] duplicate prevented: inbox=%s reason=already_auto_drafted",
                inbox_id,
            )
            raise HTTPException(
                status_code=409,
                detail="Auto draft already created for this inbox item",
            )

        existing = await find_content_linked_to_buffer(
            db, entry.id, message_id=entry.message_id,
        )
        if existing:
            await mark_buffer_entries_linked(db, [entry], existing.id)
            await db.commit()
            logger.info(
                "[Operator Inbox] linked existing content=%s inbox=%s",
                existing.id,
                inbox_id,
            )
            return {
                "ok": True,
                "message": "Linked to existing content (not duplicated)",
                "inbox_id": inbox_id,
                "content_id": existing.id,
                "status": INBOX_USED,
            }

        if effective_inbox_status(entry) == INBOX_IGNORED:
            entry.inbox_status = INBOX_NEW
            await db.flush()

        group_entries = await _load_buffer_entries(db, client.id, entry.group_id)
        scope = _scoped_client_entries_for_reply(group_entries, entry)

        if from_group and entry.grouped_task_id:
            siblings_result = await db.execute(
                select(TelegramGroupBufferMessage).where(
                    TelegramGroupBufferMessage.grouped_task_id == entry.grouped_task_id,
                    TelegramGroupBufferMessage.sender_role.in_(tuple(CLIENT_SENDER_ROLES)),
                )
            )
            siblings = list(siblings_result.scalars().all())
            combined_scope: list[TelegramGroupBufferMessage] = []
            seen_scope: set[UUID] = set()
            for sib in siblings:
                sib_entries = await _load_buffer_entries(db, sib.client_id, sib.group_id)
                sib_scope = _scoped_client_entries_for_reply(sib_entries, sib)
                for e in sib_scope:
                    if e.id not in seen_scope:
                        seen_scope.add(e.id)
                        combined_scope.append(e)
            scope = combined_scope
            if not media_selection:
                media_selection = {
                    "use_all_media": True,
                    "use_client_text_as_description": True,
                }

        if media_selection:
            selected, source_text = resolve_media_from_suggestion(scope, media_selection)
        else:
            selected = [e for e in scope if e.media_file_id]
            source_text = (entry.text or "").strip() or None
            if not source_text:
                for e in scope:
                    if e.text and (e.text or "").strip():
                        source_text = e.text.strip()
                        break
        if not selected and scope:
            selected = [scope[-1]]
        if not selected:
            raise HTTPException(status_code=400, detail="No media or text in buffer scope")

        if not source_text:
            source_text = (entry.text or "").strip() or None
            if not source_text:
                for e in scope:
                    if e.text and (e.text or "").strip():
                        source_text = e.text.strip()
                        break

        chat_title = client.telegram_group_title or entry.group_id
        instruction = instruction or (
            "Created by AI Auto Draft" if auto_draft else "Created from operator inbox"
        )

        try:
            item = await create_content_from_buffer_selection(
                db,
                client=client,
                group_id=entry.group_id,
                chat_title=chat_title,
                instruction=instruction,
                admin_name="auto_draft" if auto_draft else "operator",
                selected=selected,
                source_text=source_text,
                admin_message_id=None,
                run_prepare=False,
                content_source=TG_INBOX_AUTO_DRAFT_SOURCE if auto_draft else None,
            )
            note = ai_note
            if auto_draft:
                note = (note or "").strip()
                auto_line = "Created by AI Auto Draft — admin review required before publish."
                note = f"{auto_line} {note}".strip() if note else auto_line
            await OperatorInboxService._apply_content_metadata(
                db,
                item,
                platforms=platforms,
                scheduled_for=scheduled_for,
                ai_note=note,
                note_prefix="[Auto Draft] " if auto_draft else "[Operator AI] ",
            )
            link_map = {entry.id: entry}
            for e in selected:
                link_map[e.id] = e
            for e in scope:
                link_map.setdefault(e.id, e)
            if entry.grouped_task_id:
                sib_result = await db.execute(
                    select(TelegramGroupBufferMessage).where(
                        TelegramGroupBufferMessage.grouped_task_id == entry.grouped_task_id,
                    )
                )
                for sib in sib_result.scalars().all():
                    link_map[sib.id] = sib
            await mark_buffer_entries_linked(db, list(link_map.values()), item.id)
            if auto_draft:
                entry.auto_drafted = True
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("[Operator Inbox] create-content failed: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to create content from buffer",
            ) from exc

        logger.info(
            "[Operator Inbox] create-content: inbox=%s content=%s",
            inbox_id,
            item.id,
        )
        return {
            "ok": True,
            "message": "Content created from inbox",
            "inbox_id": inbox_id,
            "content_id": item.id,
            "status": INBOX_USED,
        }

    @staticmethod
    async def apply_ai_suggestion(db: AsyncSession, inbox_id: UUID) -> dict:
        entry = await OperatorInboxService._get_inbox_entry(db, inbox_id)
        suggestion = OperatorAiService.get_cached_or_raise(entry)

        if not can_apply_suggestion(suggestion):
            raise HTTPException(
                status_code=400,
                detail="Suggestion cannot be applied automatically — review manually",
            )

        intent = suggestion.get("intent")
        platforms = suggestion.get("suggested_platforms")
        scheduled_for = parse_schedule_iso(suggestion.get("suggested_schedule"))
        media_selection = suggestion.get("media_selection") or {}
        action = suggestion.get("suggested_action") or "Applied AI suggestion"
        reason = suggestion.get("reason") or ""

        if intent == "edit_existing" and suggestion.get("active_content_id"):
            from sqlalchemy import select as sa_select

            content_id = UUID(str(suggestion["active_content_id"]))
            result = await db.execute(
                sa_select(ContentItem).where(ContentItem.id == content_id)
            )
            item = result.scalar_one_or_none()
            if not item:
                raise HTTPException(status_code=404, detail="Active content not found")
            await OperatorInboxService._apply_content_metadata(
                db,
                item,
                platforms=platforms if isinstance(platforms, list) else None,
                scheduled_for=scheduled_for,
                ai_note=f"{action}. {reason}".strip(),
            )
            set_admin_instruction(item, f"[Inbox AI] {action}")
            await db.commit()
            logger.info(
                "[Operator AI] applied: inbox=%s content=%s intent=edit_existing",
                inbox_id,
                content_id,
            )
            return {
                "ok": True,
                "message": "AI suggestion applied to active draft (not published)",
                "inbox_id": inbox_id,
                "content_id": content_id,
                "status": effective_inbox_status(entry),
            }

        result = await OperatorInboxService.create_content_from_inbox(
            db,
            inbox_id,
            platforms=platforms if isinstance(platforms, list) else None,
            scheduled_for=scheduled_for,
            media_selection=media_selection,
            instruction=f"[Operator AI] {action}",
        )
        if result.get("content_id") and reason:
            res = await db.execute(
                select(ContentItem).where(ContentItem.id == result["content_id"])
            )
            item = res.scalar_one_or_none()
            if item:
                await OperatorInboxService._apply_content_metadata(
                    db,
                    item,
                    platforms=None,
                    scheduled_for=None,
                    ai_note=reason[:400],
                )
                await db.commit()
        logger.info(
            "[Operator AI] applied: inbox=%s content=%s intent=%s",
            inbox_id,
            result.get("content_id"),
            intent,
        )
        return result

    @staticmethod
    async def ignore_inbox_item(db: AsyncSession, inbox_id: UUID) -> dict:
        entry = await OperatorInboxService._get_inbox_entry(db, inbox_id)
        if entry.linked_content_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot ignore — already linked to content",
            )
        entry.inbox_status = INBOX_IGNORED
        await db.commit()
        logger.info("[Operator Inbox] ignored: %s", inbox_id)
        return {
            "ok": True,
            "message": "Marked as ignored",
            "inbox_id": inbox_id,
            "status": INBOX_IGNORED,
        }

    @staticmethod
    async def restore_inbox_item(db: AsyncSession, inbox_id: UUID) -> dict:
        entry = await OperatorInboxService._get_inbox_entry(db, inbox_id)
        if entry.linked_content_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot restore — already linked to content",
            )
        entry.inbox_status = INBOX_NEW
        await db.commit()
        logger.info("[Operator Inbox] restored: %s", inbox_id)
        return {
            "ok": True,
            "message": "Restored to new",
            "inbox_id": inbox_id,
            "status": INBOX_NEW,
        }
