"""AI Auto Draft — create draft content from new inbox items when enabled per client."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.services.operator_ai_service import OperatorAiService
from app.services.operator_common import (
    CLIENT_SENDER_ROLES,
    find_content_linked_to_buffer,
    parse_schedule_iso,
)

logger = logging.getLogger(__name__)

AUTO_DRAFT_INTENTS = frozenset({"create_post", "schedule_post"})


class OperatorAutoDraftService:
    @staticmethod
    async def try_auto_draft(
        db: AsyncSession,
        entry: TelegramGroupBufferMessage,
        client: Client,
    ) -> dict[str, Any] | None:
        if entry.sender_role not in CLIENT_SENDER_ROLES:
            return None

        if not bool(getattr(client, "operator_auto_draft_enabled", False)):
            return None

        logger.info(
            "[Auto Draft] enabled: client=%s inbox=%s",
            client.id,
            entry.id,
        )

        if entry.auto_drafted:
            logger.info(
                "[Auto Draft] duplicate prevented: inbox=%s reason=already_auto_drafted",
                entry.id,
            )
            return None

        if entry.linked_content_id:
            logger.info(
                "[Auto Draft] duplicate prevented: inbox=%s reason=linked_content",
                entry.id,
            )
            return None

        existing = await find_content_linked_to_buffer(
            db, entry.id, message_id=entry.message_id,
        )
        if existing:
            logger.info(
                "[Auto Draft] duplicate prevented: inbox=%s reason=existing_content content=%s",
                entry.id,
                existing.id,
            )
            return None

        suggestion = await OperatorAiService.suggest_for_inbox(
            db, entry.id, force_refresh=False,
        )
        intent = suggestion.get("intent")
        logger.info(
            "[Auto Draft] suggestion: inbox=%s intent=%s",
            entry.id,
            intent,
        )

        if intent not in AUTO_DRAFT_INTENTS:
            logger.info(
                "[Auto Draft] skipped: inbox=%s intent=%s",
                entry.id,
                intent,
            )
            return None

        action = suggestion.get("suggested_action") or "Auto draft from inbox"
        reason = suggestion.get("reason") or ""
        scheduled_for = parse_schedule_iso(suggestion.get("suggested_schedule"))
        media_selection = suggestion.get("media_selection") or {}
        platforms = suggestion.get("suggested_platforms")

        from app.services.operator_inbox_service import OperatorInboxService

        try:
            result = await OperatorInboxService.create_content_from_inbox(
                db,
                entry.id,
                platforms=platforms if isinstance(platforms, list) else None,
                scheduled_for=scheduled_for,
                media_selection=media_selection,
                instruction=f"[Auto Draft] {action}",
                auto_draft=True,
                ai_note=reason[:400] if reason else None,
            )
        except HTTPException as exc:
            logger.info(
                "[Auto Draft] skipped: inbox=%s reason=%s",
                entry.id,
                exc.detail,
            )
            return None

        content_id = result.get("content_id")
        if content_id:
            logger.info(
                "[Auto Draft] draft created: inbox=%s content=%s",
                entry.id,
                content_id,
            )

        return result
