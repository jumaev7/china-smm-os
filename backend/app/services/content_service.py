import logging
import json
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, extract
from sqlalchemy.orm import selectinload
from fastapi import HTTPException
from app.models.content import ContentItem
from app.models.calendar import CalendarEntry
from app.models.client import Client
from app.models.media import MediaFile
from app.schemas.content import ContentCreate, ContentUpdate, CalendarEntryCreate, CalendarEntryUpdate
from app.core.client_scope_guard import guard_resource_client_id, scope_select
from app.core.storage import storage
from app.services.subtitle_service import (
    subtitle_path_for,
    translated_subtitle_path_for,
    burned_video_path_for,
    dubbed_video_fitted_path_for,
    dubbed_video_legacy_path_for,
    dubbed_video_extended_path_for,
    final_video_path_for,
    final_video_legacy_path_for,
    TRANSLATED_LANG_CODES,
    VOICE_LANG_CODES,
)
from app.services.video_processing_service import (
    VideoProcessingError,
    burn_subtitles_into_video,
    generate_final_video,
)
from app.services.voice_service import VoiceProcessingError, generate_dubbed_video

logger = logging.getLogger(__name__)


def _dubbed_fitted_storage_key(storage_path: str, lang: str) -> str | None:
    for key_fn in (dubbed_video_fitted_path_for, dubbed_video_legacy_path_for):
        key = key_fn(storage_path, lang)
        if storage.exists(key):
            return key
    return None


def _final_export_urls_for(storage_path: str) -> dict[str, str]:
    exports: dict[str, str] = {}
    cn_key = final_video_path_for(storage_path, "cn")
    if storage.exists(cn_key):
        exports["cn:original:n/a"] = storage.get_url(cn_key)
    for sub in TRANSLATED_LANG_CODES:
        if sub == "cn":
            continue
        legacy = final_video_legacy_path_for(storage_path, sub)
        if storage.exists(legacy):
            exports[f"{sub}:{sub}:fitted"] = storage.get_url(legacy)
        for voice in VOICE_LANG_CODES:
            for mode in ("fitted", "extended"):
                key = final_video_path_for(storage_path, sub, voice, mode)
                if storage.exists(key):
                    exports[f"{sub}:{voice}:{mode}"] = storage.get_url(key)
    return exports


def _legacy_final_video_url(storage_path: str, lang: str) -> str | None:
    if lang == "cn":
        key = final_video_path_for(storage_path, "cn")
        return storage.get_url(key) if storage.exists(key) else None
    for key_fn in (
        lambda: final_video_path_for(storage_path, lang, lang, "fitted"),
        lambda: final_video_legacy_path_for(storage_path, lang),
    ):
        key = key_fn()
        if storage.exists(key):
            return storage.get_url(key)
    return None

STATUS_TRANSITIONS = {
    "new": ["needs_review", "needs_caption", "ready", "rejected", "draft"],
    "needs_review": ["needs_caption", "ready", "rejected", "draft", "ready_for_approval", "scheduled"],
    "needs_caption": ["needs_review", "ready", "rejected", "draft", "ready_for_approval"],
    "rejected": ["needs_review", "draft", "needs_caption"],
    "draft":     ["new", "needs_review", "needs_caption", "ready", "ready_for_approval", "scheduled", "rejected"],
    "ready":     ["draft", "needs_review", "needs_caption", "ready_for_approval", "scheduled", "rejected"],
    "ready_for_approval": ["draft", "needs_review", "approved", "scheduled", "rejected"],
    "approved":  ["draft", "scheduled", "publishing", "rejected"],
    "scheduled": ["draft", "needs_review", "publishing", "failed", "partial_failed"],
    "publishing": ["published", "failed", "partial_failed"],
    "published": [],
    "partial_failed": ["draft", "scheduled", "approved", "publishing", "failed"],
    "failed":    ["draft", "scheduled", "approved", "publishing", "partial_failed", "needs_review"],
    "changes_requested": ["draft", "needs_review", "needs_caption", "ready", "ready_for_approval"],
}


class ContentService:

    @staticmethod
    async def create(db: AsyncSession, data: ContentCreate) -> ContentItem:
        result = await db.execute(select(Client).where(Client.id == data.client_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Client not found")
        item = ContentItem(**data.model_dump())
        db.add(item)
        await db.commit()
        try:
            from app.services.platform_audit_service import PlatformAuditService
            client_row = await db.get(Client, item.client_id)
            tenant_id = client_row.tenant_id if client_row else None
            await PlatformAuditService.record(
                db,
                actor_type="tenant",
                tenant_id=tenant_id,
                event_type="content_creation",
                resource_type="content_item",
                resource_id=str(item.id),
                details={"client_id": str(item.client_id)},
            )
        except Exception:
            logger.warning("[Content] audit log failed on content creation", exc_info=True)
        # Re-fetch with relationships so media_file is populated in serialize()
        return await ContentService.get(db, item.id)

    @staticmethod
    async def get(db: AsyncSession, content_id: UUID) -> ContentItem:
        """Fetch a ContentItem with media_file eagerly loaded."""
        result = await db.execute(
            select(ContentItem)
            .where(ContentItem.id == content_id)
            .options(selectinload(ContentItem.media_file))
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Content item not found")
        guard_resource_client_id(item.client_id)
        return item

    @staticmethod
    async def list_all(
        db: AsyncSession,
        client_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 50,
        source: str | None = None,
    ) -> tuple[list[ContentItem], int]:
        query = (
            select(ContentItem)
            .options(selectinload(ContentItem.media_file))
            .order_by(ContentItem.created_at.desc())
        )
        count_q = select(func.count()).select_from(ContentItem)

        query, count_q = scope_select(query, count_q, ContentItem.client_id, client_id=client_id)
        if status:
            query = query.where(ContentItem.status == status)
            count_q = count_q.where(ContentItem.status == status)
        if source:
            query = query.where(ContentItem.source == source)
            count_q = count_q.where(ContentItem.source == source)

        total = (await db.execute(count_q)).scalar()
        result = await db.execute(query.offset(skip).limit(limit))
        return result.scalars().all(), total

    @staticmethod
    async def update(db: AsyncSession, content_id: UUID, data: ContentUpdate) -> ContentItem:
        item = await ContentService.get(db, content_id)
        previous_status = item.status

        if data.status and data.status != item.status:
            allowed = STATUS_TRANSITIONS.get(item.status, [])
            if data.status not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot transition from '{item.status}' to '{data.status}'. Allowed: {allowed}",
                )
            if data.status == "published":
                item.published_at = datetime.now(timezone.utc)

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(item, field, value)

        if "context_ai_override" in data.model_dump(exclude_unset=True):
            from app.services.context_ai_service import sync_context_override_marker
            sync_context_override_marker(item)

        if previous_status != "scheduled" and item.status == "scheduled":
            from app.services.content_review_service import ContentReviewService
            await ContentReviewService.after_content_scheduled(db, item)

        await db.commit()
        # Re-fetch so media_file relationship reflects any media_file_id change
        return await ContentService.get(db, content_id)

    @staticmethod
    async def update_links(
        db: AsyncSession,
        content_id: UUID,
        *,
        linked_sales_lead_id: UUID | None = ...,
        linked_buyer_id: UUID | None = ...,
        linked_sales_deal_id: UUID | None = ...,
    ) -> ContentItem:
        item = await ContentService.get(db, content_id)
        if linked_sales_lead_id is not ...:
            item.linked_sales_lead_id = linked_sales_lead_id
        if linked_buyer_id is not ...:
            item.linked_buyer_id = linked_buyer_id
        if linked_sales_deal_id is not ...:
            item.linked_sales_deal_id = linked_sales_deal_id
        await db.commit()
        return await ContentService.get(db, content_id)

    @staticmethod
    async def approve(db: AsyncSession, content_id: UUID) -> ContentItem:
        item = await ContentService.get(db, content_id)
        if item.status not in ("ready", "draft", "ready_for_approval", "changes_requested", "needs_review", "needs_caption", "new"):
            raise HTTPException(status_code=400, detail="Only draft/ready content can be approved")

        item.status = "approved"
        item.approved_at = datetime.now(timezone.utc)
        await db.commit()

        from app.services.content_review_service import ContentReviewService
        await ContentReviewService.after_admin_approve(db, content_id)

        return await ContentService.get(db, content_id)

    @staticmethod
    async def mark_published(db: AsyncSession, content_id: UUID) -> ContentItem:
        item = await ContentService.get(db, content_id)
        item.status = "published"
        item.published_at = datetime.now(timezone.utc)
        await db.commit()
        return await ContentService.get(db, content_id)

    @staticmethod
    async def mark_failed(db: AsyncSession, content_id: UUID) -> ContentItem:
        item = await ContentService.get(db, content_id)
        item.status = "failed"
        await db.commit()
        return await ContentService.get(db, content_id)

    @staticmethod
    async def apply_generated(db: AsyncSession, content_id: UUID, generated) -> ContentItem:
        """Write AI-generated content back to the content item."""
        item = await ContentService.get(db, content_id)
        for field, value in generated.model_dump().items():
            setattr(item, field, value)
        if item.status == "draft":
            item.status = "ready"
        await db.commit()
        return await ContentService.get(db, content_id)

    @staticmethod
    async def mark_ready_for_approval(db: AsyncSession, content_id: UUID) -> ContentItem:
        item = await ContentService.get(db, content_id)
        item.status = "ready_for_approval"
        await db.commit()
        return await ContentService.get(db, content_id)

    @staticmethod
    async def burn_subtitled_video(db: AsyncSession, content_id: UUID, lang: str) -> ContentItem:
        """Burn selected translated SRT into a new MP4 (does not overwrite original)."""
        lang = lang.strip().lower()
        if lang not in TRANSLATED_LANG_CODES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid language. Allowed: {', '.join(TRANSLATED_LANG_CODES)}",
            )

        item = await ContentService.get(db, content_id)
        if not item.media_file:
            raise HTTPException(status_code=400, detail="Content has no media file")
        if item.media_file.file_type != "video":
            raise HTTPException(status_code=400, detail="Media is not a video")

        srt_path = translated_subtitle_path_for(item.media_file.storage_path, lang)
        if not storage.exists(srt_path):
            raise HTTPException(
                status_code=404,
                detail=f"No {lang.upper()} subtitles found. Generate subtitles first.",
            )

        try:
            await burn_subtitles_into_video(item.media_file.storage_path, lang)
        except VideoProcessingError as exc:
            logger.warning("Burn subtitles failed for content %s: %s", content_id, exc)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to generate subtitled video: {exc}",
            ) from exc

        return await ContentService.get(db, content_id)

    @staticmethod
    async def generate_voiceover(
        db: AsyncSession,
        content_id: UUID,
        lang: str,
        *,
        mode: str = "fitted",
    ) -> ContentItem:
        """AI voice dub from translated SRT (RU / UZ / EN)."""
        lang = lang.strip().lower()
        mode = (mode or "fitted").strip().lower()
        if lang not in VOICE_LANG_CODES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid language. Allowed: {', '.join(VOICE_LANG_CODES)}",
            )
        if mode not in ("fitted", "extended"):
            raise HTTPException(
                status_code=400,
                detail="Invalid mode. Allowed: fitted, extended",
            )

        item = await ContentService.get(db, content_id)
        if not item.media_file:
            raise HTTPException(status_code=400, detail="Content has no media file")
        if item.media_file.file_type != "video":
            raise HTTPException(status_code=400, detail="Media is not a video")

        srt_path = translated_subtitle_path_for(item.media_file.storage_path, lang)
        if not storage.exists(srt_path):
            raise HTTPException(
                status_code=404,
                detail=f"No {lang.upper()} subtitles found. Generate subtitles first.",
            )

        logger.info("[Voiceover] mode received: %s (lang=%s content=%s)", mode, lang, content_id)

        try:
            output_key = await generate_dubbed_video(
                item.media_file.storage_path, lang, mode=mode
            )
            logger.info("[Voiceover] output path: %s", output_key)
        except VoiceProcessingError as exc:
            logger.error(
                "Voice dub failed for content %s lang=%s mode=%s: %s",
                content_id, lang, mode, exc, exc_info=True,
            )
            detail = str(exc)
            if exc.args and exc.args[0] == VoiceProcessingError.FITTED_TOO_LONG:
                detail = VoiceProcessingError.FITTED_TOO_LONG
            raise HTTPException(
                status_code=502,
                detail=detail,
            ) from exc
        except Exception as exc:
            logger.error(
                "Voice dub unexpected error for content %s lang=%s: %s",
                content_id, lang, exc, exc_info=True,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to generate voiceover: {exc}",
            ) from exc

        item = await ContentService.get(db, content_id)
        serialized = ContentService.serialize(item)
        logger.info(
            "[Voiceover] response URLs: fitted_ru=%s fitted_uz=%s fitted_en=%s "
            "extended_ru=%s extended_uz=%s extended_en=%s",
            serialized.get("dubbed_video_url_ru"),
            serialized.get("dubbed_video_url_uz"),
            serialized.get("dubbed_video_url_en"),
            serialized.get("dubbed_video_extended_url_ru"),
            serialized.get("dubbed_video_extended_url_uz"),
            serialized.get("dubbed_video_extended_url_en"),
        )
        return item

    @staticmethod
    async def generate_final_export(
        db: AsyncSession,
        content_id: UUID,
        subtitle_lang: str,
        voice_lang: str,
        voice_mode: str,
    ) -> tuple[ContentItem, str]:
        """Burn subtitles onto dubbed video (or original for CN); separate .final.mp4 file."""
        subtitle_lang = subtitle_lang.strip().lower()
        voice_lang = voice_lang.strip().lower()
        voice_mode = (voice_mode or "fitted").strip().lower()

        logger.info("[Final Export] subtitle: %s", subtitle_lang)
        logger.info("[Final Export] voice: %s", voice_lang)
        logger.info("[Final Export] mode: %s", voice_mode)

        if subtitle_lang not in TRANSLATED_LANG_CODES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid subtitle language. Allowed: {', '.join(TRANSLATED_LANG_CODES)}",
            )
        if subtitle_lang != "cn":
            if voice_lang not in VOICE_LANG_CODES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid voice language. Allowed: {', '.join(VOICE_LANG_CODES)}",
                )
            if voice_mode not in ("fitted", "extended"):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid voice mode. Allowed: fitted, extended",
                )

        item = await ContentService.get(db, content_id)
        if not item.media_file:
            raise HTTPException(status_code=400, detail="Content has no media file")
        if item.media_file.file_type != "video":
            raise HTTPException(status_code=400, detail="Media is not a video")

        srt_path = translated_subtitle_path_for(item.media_file.storage_path, subtitle_lang)
        if not storage.exists(srt_path):
            raise HTTPException(
                status_code=404,
                detail=f"No {subtitle_lang.upper()} subtitles found. Generate subtitles first.",
            )

        try:
            output_key = await generate_final_video(
                item.media_file.storage_path,
                subtitle_lang,
                voice_lang,
                voice_mode,
            )
        except VideoProcessingError as exc:
            logger.error(
                "Final video failed for content %s subtitle=%s voice=%s mode=%s: %s",
                content_id, subtitle_lang, voice_lang, voice_mode, exc, exc_info=True,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to generate final video: {exc}",
            ) from exc
        except VoiceProcessingError as exc:
            logger.error(
                "Final video voice step failed for content %s subtitle=%s voice=%s mode=%s: %s",
                content_id, subtitle_lang, voice_lang, voice_mode, exc, exc_info=True,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to generate final video (voiceover): {exc}",
            ) from exc
        except Exception as exc:
            logger.error(
                "Final video unexpected error for content %s subtitle=%s voice=%s mode=%s: %s",
                content_id, subtitle_lang, voice_lang, voice_mode, exc, exc_info=True,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to generate final video: {exc}",
            ) from exc

        item = await ContentService.get(db, content_id)
        return item, output_key

    @staticmethod
    async def delete(db: AsyncSession, content_id: UUID) -> None:
        item = await ContentService.get(db, content_id)
        await db.delete(item)
        await db.commit()

    @staticmethod
    async def build_selected_media(db: AsyncSession, item: ContentItem) -> list[dict]:
        """Resolve buffer refs (or primary media) into preview-ready media list."""
        selected: list[dict] = []
        if item.telegram_buffer_refs:
            try:
                refs = json.loads(item.telegram_buffer_refs)
            except json.JSONDecodeError:
                refs = []
            if isinstance(refs, list):
                for ref in refs:
                    mf_id = ref.get("media_file_id")
                    if not mf_id:
                        continue
                    mf = await db.get(MediaFile, UUID(str(mf_id)))
                    if not mf:
                        continue
                    msg_type = ref.get("message_type") or mf.file_type
                    media_type = "video" if msg_type == "video" or mf.file_type == "video" else "image"
                    selected.append({
                        "ordinal": ref.get("ordinal") or len(selected) + 1,
                        "media_file_id": str(mf.id),
                        "media_type": media_type,
                        "url": storage.get_url(mf.storage_path),
                        "text": (ref.get("text") or "")[:200],
                    })

        if not selected and item.media_file:
            selected.append({
                "ordinal": 1,
                "media_file_id": str(item.media_file.id),
                "media_type": item.media_file.file_type,
                "url": storage.get_url(item.media_file.storage_path),
                "text": "",
            })
        return selected

    @staticmethod
    async def serialize_detail(db: AsyncSession, item: ContentItem) -> dict:
        d = ContentService.serialize(item)
        d["selected_media"] = await ContentService.build_selected_media(db, item)
        if item.source == "content_plan":
            from app.models.content_plan import ContentPlanItem
            from app.services.content_planner_service import CONTENT_PLAN_AI_MARKER
            result = await db.execute(
                select(ContentPlanItem)
                .options(selectinload(ContentPlanItem.plan))
                .where(ContentPlanItem.linked_content_id == item.id)
            )
            plan_item = result.scalar_one_or_none()
            if plan_item and plan_item.plan:
                notes = item.internal_notes or ""
                d["content_plan_context"] = {
                    "plan_item_id": plan_item.id,
                    "plan_id": plan_item.plan_id,
                    "plan_title": plan_item.plan.title,
                    "theme": plan_item.theme,
                    "goal": plan_item.goal,
                    "content_type": plan_item.content_type,
                    "planned_date": plan_item.planned_date,
                    "ai_generated": CONTENT_PLAN_AI_MARKER in notes,
                }
        return d

    @staticmethod
    def serialize(item: ContentItem) -> dict:
        """Return a JSON-safe dict; media_url is always an absolute URL or None."""
        d = {c.name: getattr(item, c.name) for c in item.__table__.columns}
        # item.media_file is eagerly loaded by every method that calls get()
        d["media_url"] = (
            storage.get_url(item.media_file.storage_path)
            if item.media_file
            else None
        )
        d["media_file_type"] = item.media_file.file_type if item.media_file else None
        if item.media_file:
            sp = item.media_file.storage_path
            sub_path = subtitle_path_for(sp)
            d["subtitle_url"] = storage.get_url(sub_path) if storage.exists(sub_path) else None
            for lang in TRANSLATED_LANG_CODES:
                tpath = translated_subtitle_path_for(sp, lang)
                d[f"subtitle_url_{lang}"] = (
                    storage.get_url(tpath) if storage.exists(tpath) else None
                )
                bpath = burned_video_path_for(sp, lang)
                d[f"subtitled_video_url_{lang}"] = (
                    storage.get_url(bpath) if storage.exists(bpath) else None
                )
            for vlang in VOICE_LANG_CODES:
                fitted_key = _dubbed_fitted_storage_key(sp, vlang)
                d[f"dubbed_video_url_{vlang}"] = (
                    storage.get_url(fitted_key) if fitted_key else None
                )
                extpath = dubbed_video_extended_path_for(sp, vlang)
                d[f"dubbed_video_extended_url_{vlang}"] = (
                    storage.get_url(extpath) if storage.exists(extpath) else None
                )
            for lang in TRANSLATED_LANG_CODES:
                d[f"final_video_url_{lang}"] = _legacy_final_video_url(sp, lang)
            exports = _final_export_urls_for(sp)
            d["final_export_urls"] = exports or None
        else:
            d["subtitle_url"] = None
            for lang in TRANSLATED_LANG_CODES:
                d[f"subtitle_url_{lang}"] = None
                d[f"subtitled_video_url_{lang}"] = None
                d[f"final_video_url_{lang}"] = None
            for vlang in VOICE_LANG_CODES:
                d[f"dubbed_video_url_{vlang}"] = None
                d[f"dubbed_video_extended_url_{vlang}"] = None
            d["final_export_urls"] = None
        d["generated_final_video_url"] = None
        from app.services.context_ai_service import parse_detected_context
        parsed_ctx = parse_detected_context(item.internal_notes)
        d["context_ai_detected"] = parsed_ctx["category"] if parsed_ctx else None
        d["context_ai_confidence"] = parsed_ctx["confidence"] if parsed_ctx else None
        from app.services.content_enrichment_service import suggestions_from_json
        from app.services.content_quality_service import warnings_from_json
        d["suggestions"] = suggestions_from_json(item.suggestions_json)
        d["quality_warnings"] = warnings_from_json(item.quality_warnings_json)
        d["content_classification"] = item.content_classification
        d["telegram_original_caption"] = item.telegram_original_caption
        d["telegram_forward_from"] = item.telegram_forward_from
        d["source_badge"] = "Telegram" if (item.source or "").startswith("telegram") or item.source in ("tg_group_buffer", "tg_inbox_auto_draft") else item.source
        return d


class CalendarService:

    @staticmethod
    def _utc_scheduled_for(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    async def _apply_content_schedule(
        content_item: ContentItem | None,
        *,
        scheduled_for: datetime | None,
        scheduled_date,
        time_slot: str | None,
        platforms: list[str] | None,
    ) -> None:
        if not content_item or content_item.status in ("published",):
            return
        content_item.status = "scheduled"
        if scheduled_for is not None:
            content_item.scheduled_for = CalendarService._utc_scheduled_for(scheduled_for)
        elif time_slot and scheduled_date:
            try:
                import datetime as dt
                from datetime import time as dtime
                h, m = map(int, time_slot.split(":"))
                content_item.scheduled_for = CalendarService._utc_scheduled_for(
                    dt.datetime.combine(scheduled_date, dtime(h, m))
                )
            except Exception:
                pass
        if platforms:
            content_item.platforms = platforms

    @staticmethod
    async def schedule(db: AsyncSession, data: CalendarEntryCreate) -> CalendarEntry:
        """Create or replace a calendar entry; marks content as scheduled."""
        # Remove existing entry for this content item
        existing = await db.execute(
            select(CalendarEntry).where(CalendarEntry.content_item_id == data.content_item_id)
        )
        old = existing.scalar_one_or_none()
        if old:
            await db.delete(old)
            await db.flush()

        entry = CalendarEntry(**data.model_dump(exclude={"scheduled_for"}))
        db.add(entry)

        content_result = await db.execute(
            select(ContentItem).where(ContentItem.id == data.content_item_id)
        )
        content_item = content_result.scalar_one_or_none()
        await CalendarService._apply_content_schedule(
            content_item,
            scheduled_for=data.scheduled_for,
            scheduled_date=data.scheduled_date,
            time_slot=data.time_slot,
            platforms=data.platforms,
        )

        if content_item:
            from app.services.content_review_service import ContentReviewService
            await ContentReviewService.after_content_scheduled(db, content_item)

        await db.commit()
        return await CalendarService._get_entry_with_relations(db, entry.id)

    @staticmethod
    async def update_entry(db: AsyncSession, entry_id: UUID, data: CalendarEntryUpdate) -> CalendarEntry:
        result = await db.execute(
            select(CalendarEntry)
            .where(CalendarEntry.id == entry_id)
            .options(selectinload(CalendarEntry.content_item))
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Calendar entry not found")
        payload = data.model_dump(exclude_unset=True)
        scheduled_for = payload.pop("scheduled_for", None)
        for field, value in payload.items():
            setattr(entry, field, value)
        await CalendarService._apply_content_schedule(
            entry.content_item,
            scheduled_for=scheduled_for,
            scheduled_date=entry.scheduled_date,
            time_slot=entry.time_slot,
            platforms=entry.platforms,
        )
        if entry.content_item:
            from app.services.content_review_service import ContentReviewService
            await ContentReviewService.after_content_scheduled(db, entry.content_item)
        await db.commit()
        return await CalendarService._get_entry_with_relations(db, entry_id)

    @staticmethod
    async def delete_entry(db: AsyncSession, entry_id: UUID) -> None:
        result = await db.execute(
            select(CalendarEntry)
            .where(CalendarEntry.id == entry_id)
            .options(selectinload(CalendarEntry.content_item))
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Calendar entry not found")
        content = entry.content_item
        if content and content.status == "scheduled":
            content.status = "draft"
            content.scheduled_for = None
        await db.delete(entry)
        await db.commit()

    @staticmethod
    async def mark_published(db: AsyncSession, entry_id: UUID) -> CalendarEntry:
        from app.services.publish_service import PublishService

        result = await db.execute(
            select(CalendarEntry)
            .where(CalendarEntry.id == entry_id)
            .options(selectinload(CalendarEntry.content_item))
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Calendar entry not found")
        content = entry.content_item
        if not content:
            raise HTTPException(status_code=400, detail="Calendar entry has no linked content")
        platforms = entry.platforms or content.platforms
        await PublishService.publish_content(db, content.id, platforms=platforms or None)
        return await CalendarService._get_entry_with_relations(db, entry_id)

    @staticmethod
    async def move_to_draft(db: AsyncSession, entry_id: UUID) -> None:
        result = await db.execute(
            select(CalendarEntry)
            .where(CalendarEntry.id == entry_id)
            .options(selectinload(CalendarEntry.content_item))
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Calendar entry not found")
        content = entry.content_item
        if content:
            content.status = "draft"
            content.scheduled_for = None
        await db.delete(entry)
        await db.commit()

    @staticmethod
    async def _get_entry_with_relations(db: AsyncSession, entry_id: UUID) -> CalendarEntry:
        """Fetch CalendarEntry with all nested relationships for serialization."""
        result = await db.execute(
            select(CalendarEntry)
            .where(CalendarEntry.id == entry_id)
            .options(
                selectinload(CalendarEntry.content_item)
                    .selectinload(ContentItem.client),
                selectinload(CalendarEntry.content_item)
                    .selectinload(ContentItem.media_file),
            )
        )
        return result.scalar_one()

    @staticmethod
    def serialize_entry(entry: CalendarEntry) -> dict:
        """Return a JSON-safe dict for a CalendarEntry with nested content+client+media."""
        d = {c.name: getattr(entry, c.name) for c in entry.__table__.columns}
        if entry.content_item:
            ci = entry.content_item
            d["content_item"] = {
                "id": str(ci.id),
                "client_id": str(ci.client_id),
                "status": ci.status,
                "platforms": ci.platforms,
                "caption_short_ru": ci.caption_short_ru,
                "caption_short_en": ci.caption_short_en,
                "caption_short_uz": ci.caption_short_uz,
                "media_url": (
                    storage.get_url(ci.media_file.storage_path)
                    if ci.media_file
                    else None
                ),
            }
            if hasattr(ci, "client") and ci.client:
                d["client"] = {
                    "id": str(ci.client.id),
                    "company_name": ci.client.company_name,
                }
        return d

    @staticmethod
    async def get_month(db: AsyncSession, year: int, month: int) -> list[CalendarEntry]:
        result = await db.execute(
            select(CalendarEntry)
            .options(
                selectinload(CalendarEntry.content_item).selectinload(ContentItem.client),
                selectinload(CalendarEntry.content_item).selectinload(ContentItem.media_file),
            )
            .where(
                extract("year", CalendarEntry.scheduled_date) == year,
                extract("month", CalendarEntry.scheduled_date) == month,
            )
            .order_by(CalendarEntry.scheduled_date, CalendarEntry.time_slot)
        )
        return result.scalars().all()
