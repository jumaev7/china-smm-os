"""Public client review link — generate token and handle client responses."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.services.content_service import ContentService

logger = logging.getLogger(__name__)

CLIENT_REVIEW_PENDING = "pending"
CLIENT_REVIEW_APPROVED = "approved"
CLIENT_REVIEW_CHANGES = "changes_requested"
INTAKE_GROUP_NOT_LINKED = "Client intake group is not linked."

_CLIENT_APPROVED_NOTE = "[Client review]: Client approved via review link."
_CLIENT_APPROVED_TG_NOTE = "[Client review]: Client approved via Telegram."
_CLIENT_FEEDBACK_PREFIX = "[Client review feedback]:"
_CLIENT_REGEN_NOTE = "[Client review]: Client requested regeneration."


def _review_url(token: str) -> str:
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}/review/{token}"


def _pick_final_video_url(payload: dict) -> str | None:
    if payload.get("generated_final_video_url"):
        return payload["generated_final_video_url"]
    exports = payload.get("final_export_urls") or {}
    if exports:
        return next(iter(exports.values()))
    for lang in ("ru", "uz", "en", "cn"):
        url = payload.get(f"final_video_url_{lang}")
        if url:
            return url
    return None


def _append_internal_note(item: ContentItem, line: str) -> None:
    notes = item.internal_notes or ""
    item.internal_notes = f"{notes}\n{line}".strip() if notes else line


def is_client_approved(item: ContentItem) -> bool:
    if item.client_review_status == CLIENT_REVIEW_APPROVED:
        return True
    if item.client_approved_at is not None:
        return item.client_review_status != CLIENT_REVIEW_PENDING
    return False


def client_review_required(item: ContentItem) -> bool:
    return item.client_review_status in (CLIENT_REVIEW_PENDING, CLIENT_REVIEW_CHANGES)


class ContentReviewService:
    @staticmethod
    def _intake_group_id(client: Client | None) -> str | None:
        if not client:
            return None
        group_id = (client.telegram_group_id or "").strip()
        return group_id or None

    @staticmethod
    def _log_preview_context(item: ContentItem, client: Client | None, trigger: str) -> None:
        group_id = ContentReviewService._intake_group_id(client)
        logger.info("[Client Review] trigger: %s", trigger)
        logger.info("[Client Review] content: %s", item.id)
        logger.info("[Client Review] client_id: %s", item.client_id)
        logger.info("[Client Review] telegram_group_id: %s", group_id or "(missing)")

    @staticmethod
    async def _load_item_for_preview(db: AsyncSession, content_id: UUID) -> ContentItem:
        result = await db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.client), selectinload(ContentItem.media_file))
            .where(ContentItem.id == content_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Content item not found")
        return item

    @staticmethod
    async def try_send_client_review_preview(
        db: AsyncSession,
        item: ContentItem,
        *,
        trigger: str,
        force: bool = False,
    ) -> dict:
        """
        Send Telegram client-review preview to client.telegram_group_id only.
        trigger: approve | schedule | manual
        """
        from app.services.client_review_telegram_service import ClientReviewTelegramService

        client = item.client
        ContentReviewService._log_preview_context(item, client, trigger)

        if is_client_approved(item):
            logger.info(
                "[Client Review] preview failed: content=%s reason=client_already_approved",
                item.id,
            )
            return {"sent": False, "skipped": True, "reason": "Client already approved"}

        group_id = ContentReviewService._intake_group_id(client)
        if not group_id:
            item.client_review_preview_error = INTAKE_GROUP_NOT_LINKED
            logger.info(
                "[Client Review] preview failed: content=%s error=%s",
                item.id,
                INTAKE_GROUP_NOT_LINKED,
            )
            await db.commit()
            return {"sent": False, "error": INTAKE_GROUP_NOT_LINKED}

        if item.client_review_status == CLIENT_REVIEW_CHANGES and not force:
            logger.info(
                "[Client Review] preview failed: content=%s reason=changes_requested",
                item.id,
            )
            return {"sent": False, "skipped": True, "reason": "Changes requested"}

        if trigger == "approve":
            if not item.approved_at and item.status != "approved":
                logger.info(
                    "[Client Review] preview failed: content=%s reason=not_admin_approved",
                    item.id,
                )
                return {"sent": False, "skipped": True, "reason": "Not admin-approved"}
        elif trigger == "schedule":
            if item.status != "scheduled":
                logger.info(
                    "[Client Review] preview failed: content=%s reason=not_scheduled status=%s",
                    item.id,
                    item.status,
                )
                return {"sent": False, "skipped": True, "reason": "Not scheduled"}
        elif trigger == "manual":
            if not item.approved_at and item.status not in ("scheduled", "approved"):
                logger.info(
                    "[Client Review] preview failed: content=%s reason=not_eligible_for_manual",
                    item.id,
                )
                return {
                    "sent": False,
                    "skipped": True,
                    "reason": "Content must be admin-approved or scheduled",
                }
        elif trigger == "pipeline":
            if not force:
                return {"sent": False, "skipped": True, "reason": "Pipeline preview requires force"}
        else:
            return {"sent": False, "skipped": True, "reason": f"Unknown trigger {trigger}"}

        if not force and item.client_review_preview_sent_at:
            logger.info(
                "[Client Review] preview failed: content=%s reason=already_sent",
                item.id,
            )
            return {
                "sent": True,
                "skipped": True,
                "reason": "Preview already sent",
                "sent_at": item.client_review_preview_sent_at,
            }

        await ContentReviewService.ensure_review_token(item)
        if item.client_review_status != CLIENT_REVIEW_PENDING:
            item.client_review_status = CLIENT_REVIEW_PENDING
            if trigger == "approve":
                item.client_approved_at = None
                item.client_review_feedback = None
        await db.flush()

        try:
            sent, err = await ClientReviewTelegramService.send_client_preview(db, item)
        except Exception as exc:
            logger.exception(
                "[Client Review] preview failed: content=%s error=%s",
                item.id,
                exc,
            )
            sent, err = False, str(exc)

        now = datetime.now(timezone.utc)
        if sent:
            item.client_review_preview_sent_at = now
            item.client_review_preview_error = None
            await db.commit()
            logger.info("[Client Review] preview sent: content=%s", item.id)
            return {"sent": True, "sent_at": now}

        item.client_review_preview_error = err or "Telegram preview failed"
        logger.info(
            "[Client Review] preview failed: content=%s error=%s",
            item.id,
            item.client_review_preview_error,
        )
        await db.commit()
        return {"sent": False, "error": item.client_review_preview_error}

    @staticmethod
    async def send_client_review_preview_manual(
        db: AsyncSession,
        content_id: UUID,
        *,
        force: bool = True,
    ) -> dict:
        """Send client review preview only — does not publish content."""
        item = await ContentReviewService._load_item_for_preview(db, content_id)
        if item.client_review_status == CLIENT_REVIEW_APPROVED or is_client_approved(item):
            raise HTTPException(status_code=400, detail="Client already approved this content")

        group_id = ContentReviewService._intake_group_id(item.client)
        if not group_id:
            item.client_review_preview_error = INTAKE_GROUP_NOT_LINKED
            await db.commit()
            raise HTTPException(status_code=400, detail=INTAKE_GROUP_NOT_LINKED)

        if not item.approved_at and item.status not in ("scheduled", "approved"):
            raise HTTPException(
                status_code=400,
                detail="Content must be admin-approved or scheduled before sending client review preview",
            )

        result = await ContentReviewService.try_send_client_review_preview(
            db, item, trigger="manual", force=force,
        )
        if result.get("error") == INTAKE_GROUP_NOT_LINKED:
            raise HTTPException(status_code=400, detail=INTAKE_GROUP_NOT_LINKED)
        return result

    @staticmethod
    async def ensure_review_token(item: ContentItem) -> str:
        if not item.review_token:
            item.review_token = secrets.token_urlsafe(32)
        return item.review_token

    @staticmethod
    async def create_review_link(db: AsyncSession, content_id: UUID) -> dict:
        item = await ContentService.get(db, content_id)
        token = await ContentReviewService.ensure_review_token(item)
        if not item.client_review_status:
            item.client_review_status = CLIENT_REVIEW_PENDING
        await db.commit()
        return {"token": token, "url": _review_url(token)}

    @staticmethod
    async def after_admin_approve(db: AsyncSession, content_id: UUID) -> None:
        """Start client review after admin approval — send Telegram preview to intake group."""
        item = await ContentReviewService._load_item_for_preview(db, content_id)
        if is_client_approved(item):
            if not item.client_review_status:
                item.client_review_status = CLIENT_REVIEW_APPROVED
            await db.commit()
            return

        await ContentReviewService.ensure_review_token(item)
        item.client_review_status = CLIENT_REVIEW_PENDING
        item.client_approved_at = None
        item.client_review_feedback = None
        item.client_review_preview_sent_at = None
        item.client_review_preview_error = None
        await db.flush()

        refreshed = await ContentReviewService._load_item_for_preview(db, content_id)
        await ContentReviewService.try_send_client_review_preview(
            db, refreshed, trigger="approve", force=True,
        )

    @staticmethod
    async def after_content_scheduled(db: AsyncSession, item: ContentItem) -> None:
        """Send client review preview when content is scheduled and client review is pending."""
        if not item or item.status != "scheduled":
            return
        if is_client_approved(item):
            return
        if item.client_review_status == CLIENT_REVIEW_CHANGES:
            return
        if item.client_review_status != CLIENT_REVIEW_PENDING:
            item.client_review_status = CLIENT_REVIEW_PENDING
            await db.flush()
        refreshed = await ContentReviewService._load_item_for_preview(db, item.id)
        await ContentReviewService.try_send_client_review_preview(
            db, refreshed, trigger="schedule", force=False,
        )

    @staticmethod
    async def _get_by_token(db: AsyncSession, token: str) -> ContentItem:
        result = await db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.media_file), selectinload(ContentItem.client))
            .where(ContentItem.review_token == token)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Review link not found or expired")
        return item

    @staticmethod
    async def get_public_review(db: AsyncSession, token: str) -> dict:
        item = await ContentReviewService._get_by_token(db, token)
        payload = ContentService.serialize(item)
        selected_media = await ContentService.build_selected_media(db, item)
        client: Client = item.client

        captions = []
        for lang, short_key, long_key in (
            ("RU", "caption_short_ru", "caption_long_ru"),
            ("UZ", "caption_short_uz", "caption_long_uz"),
            ("EN", "caption_short_en", "caption_long_en"),
        ):
            short = payload.get(short_key)
            long = payload.get(long_key)
            if short or long:
                captions.append({
                    "lang": lang,
                    "short": short,
                    "long": long,
                })

        already_approved = is_client_approved(item)

        return {
            "company_name": client.company_name,
            "status": item.status,
            "client_review_status": item.client_review_status,
            "media_url": payload.get("media_url"),
            "media_file_type": payload.get("media_file_type"),
            "selected_media": selected_media,
            "captions": captions,
            "hashtags": item.hashtags,
            "final_video_url": _pick_final_video_url(payload),
            "scheduled_for": item.scheduled_for,
            "platforms": item.platforms or [],
            "client_approved_at": item.client_approved_at,
            "client_review_feedback": item.client_review_feedback,
            "can_approve": not already_approved and item.client_review_status != CLIENT_REVIEW_CHANGES,
            "can_request_changes": not already_approved,
            "can_regenerate": not already_approved,
        }

    @staticmethod
    async def _notify_admin_action(item: ContentItem, message: str) -> None:
        from app.services.client_review_telegram_service import notify_admins

        client_name = item.client.company_name if item.client else "Unknown"
        await notify_admins(
            f"📬 Client review — {client_name}\n"
            f"Content: {item.id}\n"
            f"{message}"
        )

    @staticmethod
    async def client_approve(
        db: AsyncSession,
        token: str,
        *,
        via: str = "web",
    ) -> dict:
        item = await ContentReviewService._get_by_token(db, token)
        if is_client_approved(item):
            raise HTTPException(status_code=400, detail="Already approved by client")

        now = datetime.now(timezone.utc)
        item.client_approved_at = now
        item.client_review_status = CLIENT_REVIEW_APPROVED
        note = _CLIENT_APPROVED_TG_NOTE if via == "telegram" else _CLIENT_APPROVED_NOTE
        _append_internal_note(item, note)
        await db.commit()

        await ContentReviewService._notify_admin_action(item, "✅ Client approved the content.")
        logger.info("[Client Review] approved: content=%s via=%s", item.id, via)

        return {
            "ok": True,
            "message": "Thank you — your approval has been recorded.",
            "client_approved_at": now,
            "client_review_status": item.client_review_status,
        }

    @staticmethod
    async def client_request_changes(
        db: AsyncSession,
        token: str,
        feedback: str,
        *,
        via: str = "web",
    ) -> dict:
        item = await ContentReviewService._get_by_token(db, token)
        if is_client_approved(item):
            raise HTTPException(status_code=400, detail="Content already approved by client")

        feedback = feedback.strip()
        if not feedback:
            raise HTTPException(status_code=400, detail="Feedback is required")

        item.client_review_feedback = feedback
        item.client_review_status = CLIENT_REVIEW_CHANGES
        if item.status == "approved":
            item.status = "changes_requested"
        _append_internal_note(item, f"{_CLIENT_FEEDBACK_PREFIX} {feedback}")
        await db.commit()

        snippet = feedback[:200] + ("…" if len(feedback) > 200 else "")
        await ContentReviewService._notify_admin_action(
            item, f"✏️ Client requested changes:\n{snippet}",
        )
        logger.info("[Client Review] changes requested: content=%s via=%s", item.id, via)

        return {
            "ok": True,
            "message": "Thank you — your feedback has been sent to the team.",
            "status": item.status,
            "client_review_status": item.client_review_status,
        }

    @staticmethod
    async def client_reject(
        db: AsyncSession,
        token: str,
        *,
        via: str = "telegram",
    ) -> dict:
        item = await ContentReviewService._get_by_token(db, token)
        if is_client_approved(item):
            raise HTTPException(status_code=400, detail="Content already approved by client")

        feedback = "Rejected by client"
        item.client_review_feedback = feedback
        item.client_review_status = CLIENT_REVIEW_CHANGES
        if item.status == "approved":
            item.status = "changes_requested"
        _append_internal_note(item, f"{_CLIENT_FEEDBACK_PREFIX} {feedback}")
        await db.commit()

        await ContentReviewService._notify_admin_action(
            item, "❌ Client rejected the content.",
        )
        logger.info("[Client Review] rejected: content=%s via=%s", item.id, via)

        return {
            "ok": True,
            "message": "Rejection recorded — the team will follow up.",
            "status": item.status,
            "client_review_status": item.client_review_status,
        }

    @staticmethod
    async def _trigger_ai_regeneration(db: AsyncSession, item: ContentItem) -> None:
        from sqlalchemy import select as sa_select

        from app.models.client import Client as ClientModel
        from app.services.ai_service import generate_content
        from app.services.brand_profile import brand_profile_from_client
        from app.services.context_ai_service import build_context_signals
        from app.services.telegram_instruction_service import (
            build_generation_context_hint,
            extract_admin_instruction,
            extract_client_source_text,
        )

        client_result = await db.execute(
            sa_select(ClientModel).where(ClientModel.id == item.client_id)
        )
        client = client_result.scalar_one_or_none()
        if not client:
            return

        resolved_lang = client.source_language or "zh"
        resolved_source = extract_client_source_text(item.internal_notes)
        admin_instruction = extract_admin_instruction(item.internal_notes)
        resolved_hint = build_generation_context_hint(admin_instruction, None)
        context_signals = await build_context_signals(
            db, client=client, item=item, source_text=resolved_source,
        )

        try:
            generated = await generate_content(
                company_name=client.company_name,
                business_category=client.business_category,
                content_style=client.content_style,
                source_language=resolved_lang,
                source_text=resolved_source,
                context_hint=resolved_hint,
                client_notes=client.notes,
                brand_profile=brand_profile_from_client(client),
                context_signals=context_signals,
            )
            await ContentService.apply_generated(db, item.id, generated)
        except Exception as exc:
            logger.warning("Client regenerate AI failed for %s: %s", item.id, exc)

    @staticmethod
    async def client_regenerate(
        db: AsyncSession,
        token: str,
        *,
        via: str = "telegram",
    ) -> dict:
        item = await ContentReviewService._get_by_token(db, token)
        if is_client_approved(item):
            raise HTTPException(status_code=400, detail="Content already approved by client")

        _append_internal_note(item, _CLIENT_REGEN_NOTE)
        item.client_review_status = CLIENT_REVIEW_CHANGES
        item.client_approved_at = None
        item.client_review_feedback = "Client requested caption regeneration via Telegram."
        if item.status == "approved":
            item.status = "changes_requested"
        await db.commit()

        await ContentReviewService._trigger_ai_regeneration(db, item)

        refreshed = await ContentService.get(db, item.id)
        refreshed.status = "ready_for_approval"
        refreshed.client_review_status = CLIENT_REVIEW_CHANGES
        await db.commit()

        await ContentReviewService._notify_admin_action(
            refreshed, "❌ Client requested regeneration — captions re-generated, please review.",
        )

        return {
            "ok": True,
            "message": "Regeneration requested.",
            "status": refreshed.status,
            "client_review_status": refreshed.client_review_status,
        }
