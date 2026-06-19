"""
Telegram ingestion orchestration: settings, albums, enrichment pipeline, group feedback.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.models.media import MediaFile
from app.models.telegram_ingestion import (
    DEFAULT_SETTINGS_ID,
    TelegramAlbumPending,
    TelegramIngestionSettings,
)
from app.services.content_classification_service import classify_content, classify_with_ai
from app.services.content_enrichment_service import (
    enrich_content,
    enrich_with_ai,
    suggestions_to_json,
)
from app.services.content_quality_service import run_quality_checks, warnings_to_json
from app.services.context_ai_service import parse_detected_context

logger = logging.getLogger(__name__)

ALBUM_ASSEMBLY_DELAY_SEC = 2.0
_album_tasks: dict[str, asyncio.Task] = {}


def _group_id_variants(chat_id: int | str) -> list[str]:
    primary = str(chat_id)
    variants = [primary]
    if primary.startswith("-100"):
        rest = primary[4:]
        if rest:
            variants.extend([rest, f"-{rest}"])
    elif primary.startswith("-"):
        variants.append(primary.lstrip("-"))
    else:
        variants.extend([f"-{primary}", f"-100{primary}"])
    return list(dict.fromkeys(variants))


def extract_forward_info(message: dict) -> str | None:
    origin = message.get("forward_origin") or {}
    if origin:
        otype = origin.get("type", "")
        if otype == "user":
            user = origin.get("sender_user") or {}
            name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
            return f"Forwarded from user: {name or user.get('id', 'unknown')}"
        if otype == "chat":
            chat = origin.get("sender_chat") or {}
            return f"Forwarded from: {chat.get('title') or chat.get('username') or chat.get('id')}"
        if otype == "channel":
            chat = origin.get("chat") or {}
            return f"Forwarded from channel: {chat.get('title') or chat.get('username') or 'unknown'}"
    legacy = message.get("forward_from") or message.get("forward_from_chat")
    if legacy:
        if isinstance(legacy, dict):
            return f"Forwarded from: {legacy.get('title') or legacy.get('first_name') or legacy.get('id')}"
    return None


class TelegramIngestionService:

    @staticmethod
    async def get_settings(db: AsyncSession) -> TelegramIngestionSettings:
        row = await db.get(TelegramIngestionSettings, DEFAULT_SETTINGS_ID)
        if row:
            return row
        row = TelegramIngestionSettings(
            id=DEFAULT_SETTINGS_ID,
            enabled=True,
            default_status="needs_review",
            default_target_languages=["ru", "uz", "en", "zh"],
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def update_settings(db: AsyncSession, data: dict[str, Any]) -> TelegramIngestionSettings:
        row = await TelegramIngestionService.get_settings(db)
        for key, value in data.items():
            if hasattr(row, key) and value is not None:
                setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    def settings_to_dict(row: TelegramIngestionSettings) -> dict[str, Any]:
        return {
            "enabled": row.enabled,
            "allowed_group_ids": row.allowed_group_ids or [],
            "default_tenant_id": str(row.default_tenant_id) if row.default_tenant_id else None,
            "default_status": row.default_status,
            "default_target_languages": row.default_target_languages or ["ru", "uz", "en", "zh"],
            "auto_classification": row.auto_classification,
            "auto_enrichment": row.auto_enrichment,
            "quality_checks_enabled": row.quality_checks_enabled,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "env_bot_configured": bool(settings.TELEGRAM_BOT_TOKEN),
        }

    @staticmethod
    def is_ingestion_enabled(settings_row: TelegramIngestionSettings) -> bool:
        return bool(settings_row.enabled and settings.TELEGRAM_BOT_TOKEN)

    @staticmethod
    def is_group_allowed(chat_id: int | str, settings_row: TelegramIngestionSettings) -> bool:
        allowed = settings_row.allowed_group_ids or []
        if not allowed:
            return True
        variants = set(_group_id_variants(chat_id))
        return bool(variants & {str(g).strip() for g in allowed if str(g).strip()})

    @staticmethod
    async def apply_tenant_to_client(
        db: AsyncSession,
        client: Client,
        settings_row: TelegramIngestionSettings,
    ) -> None:
        if client.tenant_id:
            return
        if settings_row.default_tenant_id:
            client.tenant_id = settings_row.default_tenant_id
            await db.flush()

    @staticmethod
    async def find_duplicate_content(
        db: AsyncSession,
        client_id: UUID,
        telegram_message_id: int | None,
        media_file_id: UUID | None,
    ) -> ContentItem | None:
        if telegram_message_id is not None:
            result = await db.execute(
                select(ContentItem).where(
                    ContentItem.client_id == client_id,
                    ContentItem.telegram_message_id == telegram_message_id,
                ).limit(1)
            )
            dup = result.scalar_one_or_none()
            if dup:
                return dup
        if media_file_id:
            result = await db.execute(
                select(ContentItem).where(
                    ContentItem.client_id == client_id,
                    ContentItem.media_file_id == media_file_id,
                ).limit(1)
            )
            return result.scalar_one_or_none()
        return None

    @staticmethod
    async def queue_album_part(
        db: AsyncSession,
        *,
        client: Client,
        group_id: str,
        media_group_id: str,
        message_id: int,
        media_file_id: UUID | None,
        caption: str | None,
        message_type: str,
        refs_json: str | None = None,
    ) -> bool:
        existing = await db.execute(
            select(TelegramAlbumPending).where(
                TelegramAlbumPending.group_id == group_id,
                TelegramAlbumPending.message_id == message_id,
            )
        )
        if existing.scalar_one_or_none():
            return False

        db.add(TelegramAlbumPending(
            client_id=client.id,
            group_id=group_id,
            media_group_id=media_group_id,
            message_id=message_id,
            media_file_id=media_file_id,
            caption=caption,
            message_type=message_type,
            refs_json=refs_json,
        ))
        await db.flush()
        return True

    @staticmethod
    async def load_album_parts(
        db: AsyncSession,
        group_id: str,
        media_group_id: str,
    ) -> list[TelegramAlbumPending]:
        result = await db.execute(
            select(TelegramAlbumPending)
            .where(
                TelegramAlbumPending.group_id == group_id,
                TelegramAlbumPending.media_group_id == media_group_id,
            )
            .order_by(TelegramAlbumPending.message_id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def clear_album_parts(db: AsyncSession, parts: list[TelegramAlbumPending]) -> None:
        for part in parts:
            await db.delete(part)
        await db.flush()

    @staticmethod
    def schedule_album_assembly(
        db_factory,
        *,
        client_id: UUID,
        group_id: str,
        media_group_id: str,
        chat_id: int | str,
        chat_title: str,
        content_source: str,
        assemble_callback,
    ) -> None:
        key = f"{group_id}:{media_group_id}"

        async def _delayed_assemble() -> None:
            try:
                await asyncio.sleep(ALBUM_ASSEMBLY_DELAY_SEC)
                async with db_factory() as db:
                    await assemble_callback(
                        db,
                        client_id=client_id,
                        group_id=group_id,
                        media_group_id=media_group_id,
                        chat_id=chat_id,
                        chat_title=chat_title,
                        content_source=content_source,
                    )
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.error("[Telegram Album] assembly failed: %s", exc, exc_info=True)
            finally:
                _album_tasks.pop(key, None)

        existing = _album_tasks.get(key)
        if existing and not existing.done():
            existing.cancel()
        _album_tasks[key] = asyncio.create_task(_delayed_assemble())

    @staticmethod
    async def process_after_create(
        db: AsyncSession,
        *,
        content_item: ContentItem,
        client: Client,
        caption: str | None,
        media_file: MediaFile | None,
        message: dict | None = None,
        selected_media_count: int = 1,
    ) -> dict[str, Any]:
        """Run classification, enrichment, quality checks; set initial status."""
        settings_row = await TelegramIngestionService.get_settings(db)
        await TelegramIngestionService.apply_tenant_to_client(db, client, settings_row)

        original_caption = (caption or "").strip()
        if message:
            fwd = extract_forward_info(message)
            if fwd:
                content_item.telegram_forward_from = fwd
            mgid = message.get("media_group_id")
            if mgid:
                content_item.telegram_media_group_id = str(mgid)

        content_item.telegram_original_caption = original_caption or None

        parsed_ctx = parse_detected_context(content_item.internal_notes)
        ctx_category = parsed_ctx["category"] if parsed_ctx else None

        classification_result: dict[str, Any] = {"category": "other", "confidence": 0.2, "method": "skipped"}
        if settings_row.auto_classification:
            ai_class = await classify_with_ai(
                caption=original_caption,
                internal_notes=content_item.internal_notes,
            )
            classification_result = ai_class or classify_content(
                caption=original_caption,
                internal_notes=content_item.internal_notes,
                media_file_type=media_file.file_type if media_file else None,
                context_ai_category=ctx_category,
            )
            content_item.content_classification = classification_result["category"]

        suggestions: dict[str, Any] | None = None
        target_langs = settings_row.default_target_languages or ["ru", "uz", "en", "zh"]
        if settings_row.auto_enrichment:
            ai_enrich = await enrich_with_ai(
                client=client,
                caption=original_caption,
                internal_notes=content_item.internal_notes,
                classification=classification_result["category"],
                target_languages=target_langs,
            )
            suggestions = ai_enrich or enrich_content(
                client=client,
                caption=original_caption,
                internal_notes=content_item.internal_notes,
                classification=classification_result["category"],
                target_languages=target_langs,
            )
            content_item.suggestions_json = suggestions_to_json(suggestions)
            if suggestions.get("target_platforms"):
                content_item.platforms = list(suggestions["target_platforms"])

        default_status = settings_row.default_status or "needs_review"
        if not content_item.status or content_item.status == "draft":
            content_item.status = default_status

        if not original_caption and not (content_item.internal_notes or "").strip():
            if content_item.status == "needs_review":
                content_item.status = "needs_caption"

        warnings: list[dict[str, Any]] = []
        if settings_row.quality_checks_enabled:
            warnings = run_quality_checks(
                content_item=content_item,
                media_file=media_file,
                caption=original_caption,
                selected_media_count=selected_media_count,
                target_languages=target_langs,
                suggestions=suggestions,
            )
            content_item.quality_warnings_json = warnings_to_json(warnings)

        await db.flush()
        return {
            "classification": classification_result,
            "suggestions": suggestions,
            "warnings": warnings,
            "status": content_item.status,
        }

    @staticmethod
    def status_display_label(status: str) -> str:
        labels = {
            "new": "New",
            "needs_review": "Needs Review",
            "needs_caption": "Needs Caption",
            "ready": "Ready",
            "scheduled": "Scheduled",
            "published": "Published",
            "rejected": "Rejected",
            "draft": "Draft",
        }
        return labels.get(status, status.replace("_", " ").title())

    @staticmethod
    def build_dashboard_url(content_id: UUID | str) -> str:
        base = (settings.PUBLIC_APP_URL or "http://localhost:3000").rstrip("/")
        return f"{base}/content/{content_id}"

    @staticmethod
    def build_feedback_message(
        *,
        content_item: ContentItem,
        media_count: int,
        caption_detected: bool,
        warnings: list[dict[str, Any]],
        dashboard_url: str | None = None,
    ) -> str:
        status_label = TelegramIngestionService.status_display_label(content_item.status)
        has_warnings = bool(warnings)

        if has_warnings:
            lines = ["Content received with warnings ⚠️", f"Status: {status_label}"]
            lines.append(f"Media: {media_count} file{'s' if media_count != 1 else ''}")
            lines.append(f"Caption: {'detected' if caption_detected else 'missing'}")
            lines.append("Warnings:")
            for w in warnings[:6]:
                lines.append(f"• {w.get('message', w.get('id', 'issue'))}")
            if dashboard_url:
                lines.append(f"Open in dashboard: {dashboard_url}")
            return "\n".join(lines)

        lines = ["Content received ✅", f"Status: {status_label}"]
        lines.append(f"Media: {media_count} file{'s' if media_count != 1 else ''}")
        lines.append(f"Caption: {'detected' if caption_detected else 'missing'}")
        if dashboard_url:
            lines.append(f"Open in dashboard: {dashboard_url}")
        return "\n".join(lines)
