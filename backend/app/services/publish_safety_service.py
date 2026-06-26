"""Pre-publish safety guard — block incomplete or unsafe content before publishing."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.services.content_readiness_service import ContentReadinessService, _has_caption
from app.services.content_review_service import client_review_required, is_client_approved
from app.services.content_service import ContentService
from app.services.publishing_account_service import PublishingAccountService
from app.services.publishing_destination_registry import (
    global_destination_status,
    platform_implementation,
    telegram_bot_configured,
    tenant_destination_status,
)
from app.services.meta_connection_service import MetaConnectionService
from app.utils.telegram_publish_destination import validate_telegram_publish_chat_id

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = frozenset({"telegram", "facebook", "instagram", "tiktok", "linkedin"})
PublishMode = Literal["test_publish", "manual_publish", "scheduled_publish"]


def _error(check_id: str, message: str, *, critical: bool = True) -> dict:
    return {"id": check_id, "message": message, "critical": critical}


def _http_detail_str(detail: object) -> str:
    if detail is None:
        return "Request failed"
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        msg = detail.get("message")
        return str(msg) if msg else str(detail)
    return str(detail)


_REQUIRED_ACTIONS: dict[str, str] = {
    "platforms": "Select at least one publishing platform",
    "content": "Attach media or add a caption",
    "admin_approved": "Admin-approve the content item",
    "client_approved": "Obtain client approval (review link or Telegram preview)",
    "client_changes": "Address client change requests",
    "status": "Resolve content status before publishing",
    "scheduled_for": "Set a valid scheduled publish time",
}


def _normalize_mode(
    mode: str | None = None,
    *,
    from_scheduler: bool = False,
    test: bool = False,
) -> PublishMode:
    if from_scheduler:
        return "scheduled_publish"
    if mode in ("test_publish", "manual_publish", "scheduled_publish"):
        return mode  # type: ignore[return-value]
    if test:
        return "test_publish"
    return "manual_publish"


class PublishSafetyService:
    @staticmethod
    async def _client_publish_chat_id(db: AsyncSession, item: ContentItem) -> str | None:
        if not item.client_id:
            return None
        result = await db.execute(
            select(Client.telegram_publish_chat_id).where(Client.id == item.client_id)
        )
        raw = result.scalar_one_or_none()
        if not raw:
            return None
        try:
            return validate_telegram_publish_chat_id(raw)
        except ValueError:
            return None

    @staticmethod
    async def evaluate(
        db: AsyncSession,
        item: ContentItem,
        *,
        target_platforms: list[str],
        account_id: UUID | None = None,
        mode: PublishMode | str | None = None,
        from_scheduler: bool = False,
        test: bool = False,
    ) -> dict:
        resolved_mode = _normalize_mode(mode, from_scheduler=from_scheduler, test=test)
        logger.info("[Publish Safety] mode: %s content=%s", resolved_mode, item.id)

        errors: list[dict] = []
        seen_ids: set[str] = set()

        def add_error(check_id: str, message: str, *, critical: bool = True) -> None:
            if check_id in seen_ids:
                return
            seen_ids.add(check_id)
            errors.append(_error(check_id, message, critical=critical))

        if resolved_mode == "test_publish":
            await PublishSafetyService._evaluate_test_publish(
                db,
                item,
                add_error=add_error,
                target_platforms=target_platforms,
                account_id=account_id,
            )
        elif resolved_mode == "scheduled_publish":
            await PublishSafetyService._evaluate_scheduled_publish(
                db,
                item,
                add_error=add_error,
                target_platforms=target_platforms,
                account_id=account_id,
            )
        else:
            await PublishSafetyService._evaluate_manual_publish(
                db,
                item,
                add_error=add_error,
                target_platforms=target_platforms,
                account_id=account_id,
            )

        passed = len(errors) == 0
        if passed:
            logger.info(
                "[Publish Safety] passed: content=%s mode=%s",
                item.id,
                resolved_mode,
            )
        else:
            logger.info(
                "[Publish Safety] blocked: content=%s mode=%s errors=%s",
                item.id,
                resolved_mode,
                [e["id"] for e in errors],
            )

        return await PublishSafetyService._build_response(
            db,
            item,
            errors=errors,
            passed=passed,
            mode=resolved_mode,
            target_platforms=target_platforms,
            account_id=account_id,
        )

    @staticmethod
    async def _build_response(
        db: AsyncSession,
        item: ContentItem,
        *,
        errors: list[dict],
        passed: bool,
        mode: PublishMode | str,
        target_platforms: list[str],
        account_id: UUID | None,
    ) -> dict:
        selected = await ContentService.build_selected_media(db, item)
        has_media = bool(item.media_file_id) or len(selected) > 0
        has_caption = _has_caption(item)
        has_admin_approval = item.approved_at is not None
        has_client_approval = is_client_approved(item)
        has_scheduled_time = item.scheduled_for is not None
        client_tg_dest = await PublishSafetyService._client_publish_chat_id(db, item)

        blockers = [e["message"] for e in errors if e.get("critical", True)]
        warnings = [e["message"] for e in errors if not e.get("critical", True)]
        required_actions: list[str] = []
        seen_actions: set[str] = set()
        for err in errors:
            action = _REQUIRED_ACTIONS.get(err["id"])
            if not action:
                if err["id"].startswith("account_"):
                    action = err["message"]
                elif err["id"] not in seen_actions:
                    action = err["message"]
            if action and action not in seen_actions:
                seen_actions.add(action)
                required_actions.append(action)

        platform_status: dict[str, dict] = {}
        explicit_account = account_id if len(target_platforms) == 1 else None
        has_connected_account = False

        for platform in target_platforms:
            account = None
            account_error: str | None = None
            try:
                account = await PublishingAccountService.resolve_for_platform(
                    db,
                    platform,
                    explicit_account,
                    client_publish_chat_id=(
                        client_tg_dest if platform == "telegram" else None
                    ),
                )
                has_connected_account = True
            except HTTPException as exc:
                account_error = _http_detail_str(exc.detail)

            dest_status = tenant_destination_status(
                platform,
                has_account=account is not None,
                account_status=account.status if account else None,
                telegram_publish_chat_id=client_tg_dest,
            )
            impl = platform_implementation(
                platform,
                dest_status=dest_status,
                account_status=account.status if account else None,
            )
            entry: dict = {
                "status": dest_status,
                "global_status": global_destination_status(platform),
                "account_name": account.account_name if account else None,
                "account_status": account.status if account else "missing",
                "account_scope": "global",  # TODO: tenant-scoped publishing accounts
                "implementation": impl,
                "blockers": [account_error] if account_error else [],
            }
            if impl == "mock":
                if platform == "telegram":
                    entry["blockers"].append(
                        "Telegram account is mock — test publish returns fake post id",
                    )
                else:
                    entry["blockers"].append(
                        "Platform adapter is mock-only — no real post is created",
                    )
            elif impl == "blocked" and platform == "telegram":
                if not telegram_bot_configured():
                    entry["blockers"].append("TELEGRAM_BOT_TOKEN not configured")
                if not client_tg_dest and not (account and account.account_id):
                    entry["blockers"].append(
                        "Telegram publish chat not configured on client or account",
                    )
                elif account and account.status == "connected" and not client_tg_dest:
                    pass  # account.account_id is the destination
            elif impl == "blocked" and platform in ("facebook", "instagram") and account:
                entry["blockers"].extend(MetaConnectionService.readiness_blockers(account))
            platform_status[platform] = entry

        return {
            "passed": passed,
            "can_publish": passed,
            "errors": errors,
            "blockers": blockers,
            "warnings": warnings,
            "required_actions": required_actions,
            "platform_status": platform_status,
            "message": errors[0]["message"] if errors else None,
            "mode": mode,
            "ready": {
                "has_media": has_media,
                "has_caption": has_caption,
                "has_admin_approval": has_admin_approval,
                "has_client_approval": has_client_approval,
                "has_scheduled_time": has_scheduled_time,
                "has_connected_account": has_connected_account,
                "telegram_publish_chat_configured": bool(client_tg_dest),
            },
        }

    @staticmethod
    async def _check_platforms_and_accounts(
        db: AsyncSession,
        *,
        item: ContentItem,
        add_error,
        target_platforms: list[str],
        account_id: UUID | None,
    ) -> None:
        explicit_account = account_id if len(target_platforms) == 1 else None
        client_tg_dest = (
            None if explicit_account
            else await PublishSafetyService._client_publish_chat_id(db, item)
        )
        if not target_platforms:
            add_error("platforms", "Select at least one platform to publish")
        else:
            unknown = [p for p in target_platforms if p not in SUPPORTED_PLATFORMS]
            for platform in unknown:
                add_error("platforms", f"Unsupported platform: {platform}")
            for platform in target_platforms:
                if platform not in SUPPORTED_PLATFORMS:
                    continue
                try:
                    account = await PublishingAccountService.resolve_for_platform(
                        db,
                        platform,
                        explicit_account,
                        client_publish_chat_id=(
                            client_tg_dest if platform == "telegram" else None
                        ),
                    )
                except HTTPException as exc:
                    add_error(f"account_{platform}", _http_detail_str(exc.detail))
                    continue
                if platform in ("facebook", "instagram"):
                    meta_blockers = MetaConnectionService.readiness_blockers(account)
                    for idx, blocker in enumerate(meta_blockers):
                        add_error(
                            f"account_{platform}" if idx == 0 else f"account_{platform}_{idx}",
                            blocker,
                        )
                    if meta_blockers:
                        continue
                if platform == "telegram" and account.status == "connected":
                    effective_chat = client_tg_dest or account.account_id
                    if not effective_chat:
                        add_error(
                            "account_telegram",
                            "Telegram publish chat not configured on client or account",
                        )
                    elif not telegram_bot_configured():
                        add_error(
                            "account_telegram",
                            "TELEGRAM_BOT_TOKEN not configured for live Telegram publish",
                        )

    @staticmethod
    async def _check_media_or_caption(
        db: AsyncSession,
        item: ContentItem,
        add_error,
    ) -> None:
        selected = await ContentService.build_selected_media(db, item)
        has_media = bool(item.media_file_id) or len(selected) > 0
        if not has_media and not _has_caption(item):
            add_error(
                "content",
                "At least one media file or text caption is required",
            )

    @staticmethod
    async def _evaluate_test_publish(
        db: AsyncSession,
        item: ContentItem,
        *,
        add_error,
        target_platforms: list[str],
        account_id: UUID | None,
    ) -> None:
        if item.status == "publishing":
            add_error(
                "status",
                "Content is currently publishing — wait before running a test",
            )
        await PublishSafetyService._check_media_or_caption(db, item, add_error)
        await PublishSafetyService._check_platforms_and_accounts(
            db,
            item=item,
            add_error=add_error,
            target_platforms=target_platforms,
            account_id=account_id,
        )

    @staticmethod
    async def _evaluate_manual_publish(
        db: AsyncSession,
        item: ContentItem,
        *,
        add_error,
        target_platforms: list[str],
        account_id: UUID | None,
    ) -> None:
        if item.status == "published":
            add_error("status", "Content is already published")

        if item.status == "publishing":
            add_error("status", "Content is already being published")

        if item.status == "draft":
            add_error("status", "Draft content cannot be published — approve first")

        if not item.approved_at:
            add_error("admin_approved", "Content must be admin approved before publishing")

        if item.status == "changes_requested" or item.client_review_status == "changes_requested":
            feedback = (item.client_review_feedback or "").strip()
            msg = "Client requested changes — resolve before publishing"
            if feedback:
                snippet = feedback[:120] + ("…" if len(feedback) > 120 else "")
                msg = f"{msg}: {snippet}"
            add_error("client_changes", msg)

        if client_review_required(item) or (
            item.client_review_status and not is_client_approved(item)
        ):
            add_error(
                "client_approved",
                "Client must approve content before publishing",
            )

        await PublishSafetyService._check_media_or_caption(db, item, add_error)

        readiness = await ContentReadinessService.evaluate(db, item, intent="approve")
        if not readiness["ready_for_approve"]:
            for check in readiness["items"]:
                if check["critical"] and not check["ready"]:
                    add_error(
                        check["id"],
                        check["message"] or f"{check['label']} — not ready",
                    )

        await PublishSafetyService._check_platforms_and_accounts(
            db,
            item=item,
            add_error=add_error,
            target_platforms=target_platforms,
            account_id=account_id,
        )

    @staticmethod
    async def _evaluate_scheduled_publish(
        db: AsyncSession,
        item: ContentItem,
        *,
        add_error,
        target_platforms: list[str],
        account_id: UUID | None,
    ) -> None:
        if item.status != "scheduled":
            add_error("status", "Scheduled publish requires status=scheduled")

        if not item.approved_at:
            add_error("admin_approved", "Content must be admin approved before publishing")

        if item.status == "changes_requested" or item.client_review_status == "changes_requested":
            feedback = (item.client_review_feedback or "").strip()
            msg = "Client requested changes — resolve before publishing"
            if feedback:
                snippet = feedback[:120] + ("…" if len(feedback) > 120 else "")
                msg = f"{msg}: {snippet}"
            add_error("client_changes", msg)

        if client_review_required(item) or (
            item.client_review_status and not is_client_approved(item)
        ):
            add_error(
                "client_approved",
                "Client must approve content before publishing",
            )

        await PublishSafetyService._check_media_or_caption(db, item, add_error)

        if not item.scheduled_for:
            add_error(
                "scheduled_for",
                "Scheduled publish requires a valid scheduled_for date/time",
            )
        else:
            scheduled_for = item.scheduled_for
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
            if scheduled_for > datetime.now(timezone.utc):
                add_error(
                    "scheduled_for",
                    "Scheduled time is still in the future",
                )

        await PublishSafetyService._check_platforms_and_accounts(
            db,
            item=item,
            add_error=add_error,
            target_platforms=target_platforms,
            account_id=account_id,
        )

    @staticmethod
    async def record_blocked(
        db: AsyncSession,
        content_id: UUID,
        errors: list[dict],
        *,
        target_platforms: list[str],
        revert_status: str | None = None,
        mode: PublishMode | str | None = None,
    ) -> None:
        """Record a failed publish_attempt; revert publishing status if needed."""
        reason = "; ".join(e["message"] for e in errors)[:2000]
        platform = target_platforms[0] if target_platforms else "safety"
        mode_label = mode or "unknown"

        attempt = PublishAttempt(
            content_id=content_id,
            platform=platform,
            account_id=None,
            status="failed",
            response=json.dumps(
                {"safety_block": True, "errors": errors, "mode": mode_label},
                ensure_ascii=False,
            ),
            error=f"[Publish Safety] {reason}",
        )
        db.add(attempt)

        result = await db.execute(
            select(ContentItem).where(ContentItem.id == content_id)
        )
        item = result.scalar_one_or_none()
        if item and item.status == "publishing" and revert_status:
            item.status = revert_status

        await db.commit()
        logger.info(
            "[Publish Safety] blocked attempt recorded: content=%s platform=%s mode=%s",
            content_id,
            platform,
            mode_label,
        )

    @staticmethod
    async def enforce_or_block(
        db: AsyncSession,
        item: ContentItem,
        *,
        content_id: UUID,
        target_platforms: list[str],
        account_id: UUID | None = None,
        mode: PublishMode | str | None = None,
        from_scheduler: bool = False,
        test: bool = False,
        previous_status: str | None = None,
    ) -> None:
        """Run safety checks; on failure record attempt and raise HTTPException."""
        resolved_mode = _normalize_mode(mode, from_scheduler=from_scheduler, test=test)
        safety = await PublishSafetyService.evaluate(
            db,
            item,
            target_platforms=target_platforms,
            account_id=account_id,
            mode=resolved_mode,
        )
        if safety["passed"]:
            return

        revert = previous_status if previous_status in (
            "scheduled", "approved", "failed", "partial_failed",
        ) else None
        if item.status == "publishing" or revert:
            await PublishSafetyService.record_blocked(
                db,
                content_id,
                safety["errors"],
                target_platforms=target_platforms,
                revert_status=revert or ("scheduled" if resolved_mode == "scheduled_publish" else previous_status),
                mode=resolved_mode,
            )
        else:
            await PublishSafetyService.record_blocked(
                db,
                content_id,
                safety["errors"],
                target_platforms=target_platforms,
                mode=resolved_mode,
            )

        raise HTTPException(
            status_code=400,
            detail={
                "message": safety["message"] or "Publish blocked by safety guard",
                "can_publish": False,
                "errors": safety["errors"],
                "blockers": safety["blockers"],
                "mode": resolved_mode,
            },
        )
