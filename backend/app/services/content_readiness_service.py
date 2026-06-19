"""Publishing readiness checklist for content approval / scheduling."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.content import ContentItem
from app.services.content_review_service import is_client_approved
from app.services.content_service import ContentService

_CAPTION_FIELDS = (
    "caption_short_ru", "caption_short_uz", "caption_short_en",
    "caption_long_ru", "caption_long_uz", "caption_long_en",
)
_SUBTITLE_URL_KEYS = (
    "subtitle_url", "subtitle_url_cn", "subtitle_url_ru", "subtitle_url_uz", "subtitle_url_en",
)


def _check_item(
    check_id: str,
    label: str,
    ready: bool,
    *,
    critical: bool = True,
    message: str | None = None,
) -> dict:
    return {
        "id": check_id,
        "label": label,
        "ready": ready,
        "critical": critical,
        "message": message or (None if ready else f"{label} — not ready"),
    }


def _has_caption(item: ContentItem) -> bool:
    return any(
        getattr(item, field) and str(getattr(item, field)).strip()
        for field in _CAPTION_FIELDS
    )


def _has_subtitles(payload: dict) -> bool:
    return any(payload.get(key) for key in _SUBTITLE_URL_KEYS)


def _video_workflow_started(payload: dict) -> bool:
    if payload.get("generated_final_video_url"):
        return True
    for key, value in payload.items():
        if not value:
            continue
        if key.startswith(("subtitled_video_url_", "dubbed_video_url_", "dubbed_video_extended_url_")):
            return True
    return False


def _has_final_video(payload: dict) -> bool:
    if payload.get("generated_final_video_url"):
        return True
    exports = payload.get("final_export_urls") or {}
    if exports:
        return True
    for lang in ("cn", "ru", "uz", "en"):
        if payload.get(f"final_video_url_{lang}"):
            return True
    return False


class ContentReadinessService:
    @staticmethod
    async def evaluate(
        db: AsyncSession,
        item: ContentItem,
        *,
        intent: str = "approve",
    ) -> dict:
        payload = ContentService.serialize(item)
        selected = await ContentService.build_selected_media(db, item)
        client_exists = (
            await db.execute(select(Client.id).where(Client.id == item.client_id))
        ).scalar_one_or_none() is not None

        is_video = payload.get("media_file_type") == "video"
        has_media = bool(item.media_file_id) or len(selected) > 0
        has_context = bool(item.context_ai_override) or bool(payload.get("context_ai_detected"))
        workflow_started = _video_workflow_started(payload)

        items: list[dict] = [
            _check_item(
                "media",
                "Media attached",
                has_media,
                message="Attach or select media before publishing",
            ),
            _check_item(
                "caption",
                "Caption generated",
                _has_caption(item),
                message="Generate captions for at least one language",
            ),
            _check_item(
                "hashtags",
                "Hashtags generated",
                bool(item.hashtags and item.hashtags.strip()),
                message="Generate or add hashtags",
            ),
            _check_item(
                "client",
                "Client linked",
                client_exists,
                message="Link content to a valid client",
            ),
            _check_item(
                "context",
                "Context category detected or manually set",
                has_context,
                message="Set Context AI category or run detection",
            ),
            _check_item(
                "platforms",
                "Platform selected",
                bool(item.platforms and len(item.platforms) > 0),
                message="Select at least one publishing platform",
            ),
        ]

        if intent == "schedule":
            items.append(
                _check_item(
                    "schedule",
                    "Schedule date/time selected",
                    item.scheduled_for is not None,
                    message="Set a schedule date and time (or use Schedule button)",
                )
            )

        admin_approved = item.approved_at is not None and item.status in (
            "approved", "scheduled", "published", "publishing", "changes_requested",
        )
        client_approved = is_client_approved(item)

        if item.approved_at or item.client_review_status:
            items.append(
                _check_item(
                    "admin_approved",
                    "Admin approved",
                    admin_approved,
                    message="Admin must approve content first" if not admin_approved else None,
                )
            )
            items.append(
                _check_item(
                    "client_approved",
                    "Client approved",
                    client_approved,
                    message=(
                        "Waiting for client approval (Telegram preview or review link)"
                        if not client_approved
                        else None
                    ),
                )
            )

        if item.client_review_status == "changes_requested" or item.status == "changes_requested":
            feedback = (item.client_review_feedback or "").strip()
            msg = "Client requested changes — update content before re-approving"
            if feedback:
                snippet = feedback[:120] + ("…" if len(feedback) > 120 else "")
                msg = f"{msg}: {snippet}"
            items.append(
                _check_item(
                    "client_changes",
                    "Client change requests addressed",
                    item.client_review_status != "changes_requested" and item.status != "changes_requested",
                    message=msg,
                )
            )

        if is_video:
            items.append(
                _check_item(
                    "subtitles",
                    "Subtitles available",
                    _has_subtitles(payload),
                    message="Generate subtitles for this video",
                )
            )
            if workflow_started:
                items.append(
                    _check_item(
                        "final_video",
                        "Final video available",
                        _has_final_video(payload),
                        message="Generate final export after subtitles/voiceover",
                    )
                )

        critical_ids = {"media", "caption", "hashtags", "client", "context", "platforms"}
        if is_video:
            critical_ids.add("subtitles")
            if workflow_started:
                critical_ids.add("final_video")
        if intent == "schedule":
            critical_ids.add("schedule")
            critical_ids.add("admin_approved")
            critical_ids.add("client_approved")
        if item.client_review_status in ("pending", "changes_requested"):
            critical_ids.add("client_approved")
        if item.status == "changes_requested" or item.client_review_status == "changes_requested":
            critical_ids.add("client_changes")

        for entry in items:
            entry["critical"] = entry["id"] in critical_ids

        approve_critical = {i["id"] for i in items if i["critical"] and i["id"] not in ("schedule", "admin_approved", "client_approved", "client_changes")}
        schedule_critical = {i["id"] for i in items if i["critical"]}

        def _all_critical_ready(check_ids: set[str]) -> bool:
            return all(i["ready"] for i in items if i["id"] in check_ids)

        ready_for_approve = _all_critical_ready(approve_critical)
        ready_for_schedule = _all_critical_ready(schedule_critical)

        return {
            "ready": ready_for_approve,
            "ready_for_approve": ready_for_approve,
            "ready_for_schedule": ready_for_schedule,
            "items": items,
        }
