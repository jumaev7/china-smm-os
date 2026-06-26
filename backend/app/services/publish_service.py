"""Orchestrate multi-platform content publishing via platform adapters."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client import Client
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.models.publishing_account import PublishingAccount
from app.schemas.publishing import PublishContentRequest
from app.services.content_service import ContentService
from app.services.publish_context import PublishContext
from app.services.publishing_account_service import PublishingAccountService
from app.services.publishing_tenant_scope import tenant_id_for_content
from app.utils.telegram_publish_destination import validate_telegram_publish_chat_id
from app.services.meta_connection_service import MetaConnectionService
from app.services.meta_graph_client import token_is_expired
from app.utils.token_vault import decrypt_token
from app.services import (
    telegram_publisher,
    facebook_publisher,
    instagram_publisher,
    tiktok_publisher,
    linkedin_publisher,
)

logger = logging.getLogger(__name__)

PUBLISHABLE_STATUSES = frozenset({"approved", "scheduled", "failed", "partial_failed"})
SUPPORTED_PLATFORMS = frozenset({"telegram", "facebook", "instagram", "tiktok", "linkedin"})
STALE_PUBLISHING_MINUTES = 5

PlatformPublishFn = Callable[[PublishContext], Awaitable[dict]]

ADAPTERS: dict[str, PlatformPublishFn] = {
    "telegram": telegram_publisher.publish,
    "facebook": facebook_publisher.publish,
    "instagram": instagram_publisher.publish,
    "tiktok": tiktok_publisher.publish,
    "linkedin": linkedin_publisher.publish,
}


def _pick_caption(item: ContentItem) -> str:
    for field in (
        "caption_long_ru", "caption_long_uz", "caption_long_en",
        "caption_short_ru", "caption_short_uz", "caption_short_en",
    ):
        value = getattr(item, field, None)
        if value and str(value).strip():
            return str(value).strip()
    return ""


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


def _compose_post_text(caption: str, hashtags: str | None) -> str:
    parts = [caption] if caption else []
    if hashtags and str(hashtags).strip():
        parts.append(str(hashtags).strip())
    return "\n\n".join(parts)


def _append_publish_note(item: ContentItem, line: str) -> None:
    notes = item.internal_notes or ""
    item.internal_notes = f"{notes}\n{line}".strip() if notes else line


def _failure_result(platform: str, error: str, account: PublishingAccount | None = None) -> dict:
    is_mock = account.status == "mock" if account else True
    return {
        "platform": platform,
        "success": False,
        "error": error,
        "platform_post_id": None,
        "mock": is_mock,
        "account_id": str(account.id) if account else None,
        "account_name": account.account_name if account else None,
    }


class PublishService:
    @staticmethod
    async def _get_content(db: AsyncSession, content_id: UUID) -> ContentItem:
        result = await db.execute(
            select(ContentItem)
            .where(ContentItem.id == content_id)
            .options(
                selectinload(ContentItem.media_file),
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Content item not found")
        return item

    @staticmethod
    def _validate_publishable(
        item: ContentItem,
        *,
        mode: str = "manual_publish",
        from_scheduler: bool = False,
    ) -> None:
        from app.services.publish_safety_service import _normalize_mode

        resolved = _normalize_mode(mode, from_scheduler=from_scheduler)
        if resolved == "test_publish":
            if item.status == "publishing":
                raise HTTPException(
                    status_code=409,
                    detail="Content is currently publishing — wait before running a test",
                )
            return

        if item.status == "publishing" and resolved != "scheduled_publish":
            raise HTTPException(
                status_code=409,
                detail="Content is already being published — wait or retry after timeout recovery",
            )
        allowed = PUBLISHABLE_STATUSES | (
            {"publishing"} if resolved == "scheduled_publish" else set()
        )
        if item.status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Content must be approved or scheduled before publishing (status={item.status})",
            )
        if not item.approved_at:
            raise HTTPException(
                status_code=400,
                detail="Content must be approved before publishing",
            )
        from app.services.content_review_service import client_review_required, is_client_approved
        if client_review_required(item) or (item.client_review_status and not is_client_approved(item)):
            raise HTTPException(
                status_code=400,
                detail="Client must approve content before publishing",
            )
        if not item.platforms and resolved == "manual_publish":
            raise HTTPException(status_code=400, detail="Select at least one platform to publish")

    @staticmethod
    async def recover_stale_publishing(
        db: AsyncSession,
        *,
        content_id: UUID | None = None,
    ) -> int:
        """Mark publishing items older than 5 minutes as failed."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PUBLISHING_MINUTES)
        query = select(ContentItem).where(
            ContentItem.status == "publishing",
            ContentItem.updated_at < cutoff,
        )
        if content_id:
            query = query.where(ContentItem.id == content_id)
        result = await db.execute(query)
        items = list(result.scalars().all())
        if not items:
            return 0

        recovered = 0
        for item in items:
            item.status = "failed"
            _append_publish_note(item, "[Publish] Publishing timeout — auto-recovered to failed")
            attempt = PublishAttempt(
                content_id=item.id,
                platform=(item.platforms[0] if item.platforms else "unknown"),
                account_id=None,
                status="failed",
                response=None,
                error="Publishing timeout",
            )
            db.add(attempt)
            recovered += 1
            logger.warning(
                "[Publish] failed: content=%s error=Publishing timeout (stale recovery)",
                item.id,
            )
        await db.commit()
        logger.info("[Publish] finally: recovered %s stale publishing item(s)", recovered)
        return recovered

    @staticmethod
    async def _client_publish_context(db: AsyncSession, item: ContentItem) -> dict:
        """Load client publish fields via explicit query — never lazy-load item.client."""
        if not item.client_id:
            return {"chat_id": None, "company_name": "", "publish_title": None}
        result = await db.execute(
            select(
                Client.company_name,
                Client.telegram_publish_chat_id,
                Client.telegram_publish_title,
            ).where(Client.id == item.client_id)
        )
        row = result.one_or_none()
        if not row:
            return {"chat_id": None, "company_name": "", "publish_title": None}
        company_name, raw_chat, publish_title = row
        chat_id: str | None = None
        if raw_chat:
            try:
                chat_id = validate_telegram_publish_chat_id(raw_chat)
            except ValueError:
                chat_id = None
        return {
            "chat_id": chat_id,
            "company_name": company_name or "",
            "publish_title": publish_title,
        }

    @staticmethod
    async def _build_context(
        item: ContentItem,
        platform: str,
        payload: dict,
        account: PublishingAccount,
        *,
        telegram_destination_chat_id: str | None = None,
        company_name: str = "",
        telegram_publish_title: str | None = None,
    ) -> PublishContext:
        media_type = payload.get("media_file_type")
        final_video = _pick_final_video_url(payload)
        media_url = final_video if media_type == "video" and final_video else payload.get("media_url")
        caption = _compose_post_text(_pick_caption(item), item.hashtags)
        effective_chat_id = telegram_destination_chat_id or account.account_id
        effective_name = account.account_name
        if telegram_destination_chat_id and telegram_publish_title:
            effective_name = telegram_publish_title

        facebook_page_id = None
        page_access_token = None
        permissions: list[str] = []
        token_expired = token_is_expired(account.expires_at)
        if platform == "facebook":
            facebook_page_id = account.facebook_page_id
            if account.access_token_encrypted:
                try:
                    page_access_token = decrypt_token(account.access_token_encrypted)
                except Exception:
                    page_access_token = None
            permissions = MetaConnectionService.account_permissions(account)

        return PublishContext(
            content_id=str(item.id),
            client_id=str(item.client_id),
            company_name=company_name,
            platform=platform,
            caption=caption,
            hashtags=item.hashtags,
            media_url=media_url,
            media_type=media_type,
            final_video_url=final_video,
            account_id=effective_chat_id,
            account_name=effective_name,
            publishing_account_id=str(account.id),
            account_status=account.status,
            selected_media=list(payload.get("selected_media") or []),
            facebook_page_id=facebook_page_id,
            page_access_token=page_access_token,
            permissions=permissions,
            token_expired=token_expired,
        )

    @staticmethod
    async def _record_attempt(
        db: AsyncSession,
        *,
        content_id: UUID,
        platform: str,
        account: PublishingAccount | None,
        result: dict,
    ) -> PublishAttempt:
        attempt = PublishAttempt(
            content_id=content_id,
            platform=platform,
            account_id=account.id if account else None,
            status="success" if result.get("success") else "failed",
            response=json.dumps(result, ensure_ascii=False, default=str),
            error=result.get("error"),
        )
        db.add(attempt)
        await db.flush()
        logger.info(
            "[Publish] publish_attempt saved: content=%s platform=%s status=%s attempt_id=%s",
            content_id,
            platform,
            attempt.status,
            attempt.id,
        )
        return attempt

    @staticmethod
    async def _force_terminal_status(
        db: AsyncSession,
        content_id: UUID,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        """Safety net: never leave content in publishing."""
        try:
            item = await PublishService._get_content(db, content_id)
            if item.status != "publishing":
                return
            item.status = status
            if status == "published":
                item.published_at = datetime.now(timezone.utc)
            if error:
                _append_publish_note(item, f"[Publish] {error}")
            await db.commit()
            logger.info("[Publish] finally: forced status=%s content=%s", status, content_id)
        except Exception:
            logger.exception("[Publish] finally: force terminal status failed content=%s", content_id)
            await db.rollback()

    @staticmethod
    async def list_history(db: AsyncSession, content_id: UUID) -> tuple[list[dict], int]:
        query = (
            select(PublishAttempt)
            .where(PublishAttempt.content_id == content_id)
            .options(selectinload(PublishAttempt.account))
            .order_by(PublishAttempt.created_at.desc())
        )
        count_q = (
            select(func.count())
            .select_from(PublishAttempt)
            .where(PublishAttempt.content_id == content_id)
        )
        total = (await db.execute(count_q)).scalar() or 0
        result = await db.execute(query)
        items = []
        for attempt in result.scalars().all():
            extras = PublishService._parse_attempt_response(attempt.response)
            items.append({
                "id": attempt.id,
                "content_id": attempt.content_id,
                "platform": attempt.platform,
                "account_id": attempt.account_id,
                "account_name": attempt.account.account_name if attempt.account else None,
                "status": attempt.status,
                "response": attempt.response,
                "error": attempt.error,
                "created_at": attempt.created_at,
                "platform_post_id": extras.get("platform_post_id"),
                "post_url": extras.get("post_url"),
            })
        return items, total

    @staticmethod
    def _parse_attempt_response(response: str | None) -> dict:
        if not response:
            return {}
        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        platform_post_id = data.get("platform_post_id")
        post_url = data.get("post_url")
        account_id = data.get("account_id")
        if (
            platform_post_id
            and isinstance(platform_post_id, str)
            and platform_post_id.startswith("tg:")
        ):
            parts = platform_post_id.split(":", 2)
            if len(parts) == 3:
                account_id = account_id or parts[1]
                platform_post_id = parts[2]
        if not post_url and platform_post_id and data.get("platform") == "telegram":
            from app.services.telegram_publisher import _telegram_post_url
            if account_id:
                post_url = _telegram_post_url(str(account_id), platform_post_id)
        return {
            "platform_post_id": str(platform_post_id) if platform_post_id is not None else None,
            "post_url": post_url,
        }

    @staticmethod
    async def publish_content(
        db: AsyncSession,
        content_id: UUID,
        *,
        request: PublishContentRequest | None = None,
        platforms: list[str] | None = None,
        from_scheduler: bool = False,
    ) -> dict:
        req = request or PublishContentRequest()
        from app.services.publish_safety_service import PublishSafetyService, _normalize_mode

        publish_mode = _normalize_mode(
            req.mode,
            from_scheduler=from_scheduler,
            test=req.test,
        )
        test_mode = publish_mode == "test_publish"
        await PublishService.recover_stale_publishing(db, content_id=content_id)

        item = await PublishService._get_content(db, content_id)
        PublishService._validate_publishable(
            item,
            mode=publish_mode,
            from_scheduler=from_scheduler,
        )

        target_platforms = req.platforms or platforms or list(item.platforms or [])
        unknown = [p for p in target_platforms if p not in SUPPORTED_PLATFORMS]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unsupported platforms: {', '.join(unknown)}")
        if not target_platforms:
            raise HTTPException(status_code=400, detail="No platforms selected for publishing")
        if req.account_id and len(target_platforms) > 1:
            raise HTTPException(status_code=400, detail="account_id can only be used with a single platform")

        previous_status = item.status

        await PublishSafetyService.enforce_or_block(
            db,
            item,
            content_id=content_id,
            target_platforms=target_platforms,
            account_id=req.account_id,
            mode=publish_mode,
            from_scheduler=from_scheduler,
            test=req.test,
            previous_status=previous_status,
        )

        payload = await ContentService.serialize_detail(db, item)
        results: list[dict] = []
        all_ok = True
        finalized = False
        terminal_status: str | None = None

        logger.info(
            "[Publish] started: content=%s platforms=%s mode=%s previous_status=%s",
            content_id,
            target_platforms,
            publish_mode,
            previous_status,
        )

        try:
            if not test_mode and not from_scheduler:
                item.status = "publishing"
                await db.flush()
                logger.info("[Publish] status set publishing: content=%s", content_id)
            elif not test_mode and from_scheduler:
                logger.info("[Publish] scheduler claim active: content=%s", content_id)

            explicit_account = req.account_id if len(target_platforms) == 1 else None
            client_ctx = await PublishService._client_publish_context(db, item)
            client_tg_dest = None if explicit_account else client_ctx["chat_id"]
            content_tenant_id = await tenant_id_for_content(db, item)
            if client_tg_dest and "telegram" in target_platforms:
                logger.info(
                    "[Publish] telegram destination: client=%s chat=%s",
                    item.client_id,
                    client_tg_dest,
                )

            for platform in target_platforms:
                logger.info("[Publish] adapter start: content=%s platform=%s", content_id, platform)
                account: PublishingAccount | None = None
                result: dict

                try:
                    account = await PublishingAccountService.resolve_for_platform(
                        db,
                        content_tenant_id,
                        platform,
                        explicit_account,
                        client_publish_chat_id=(
                            client_tg_dest if platform == "telegram" else None
                        ),
                    )
                except HTTPException as exc:
                    result = _failure_result(platform, str(exc.detail))
                    all_ok = False
                    await PublishService._record_attempt(
                        db, content_id=content_id, platform=platform, account=None, result=result,
                    )
                    results.append(result)
                    logger.info(
                        "[Publish] adapter result: content=%s platform=%s success=False error=%s",
                        content_id,
                        platform,
                        exc.detail,
                    )
                    continue

                adapter = ADAPTERS.get(platform)
                if not adapter:
                    result = _failure_result(platform, "No adapter configured", account)
                    all_ok = False
                else:
                    tg_override = (
                        client_tg_dest
                        if platform == "telegram" and not explicit_account
                        else None
                    )
                    ctx = await PublishService._build_context(
                        item,
                        platform,
                        payload,
                        account,
                        telegram_destination_chat_id=tg_override,
                        company_name=client_ctx["company_name"],
                        telegram_publish_title=client_ctx["publish_title"],
                    )
                    try:
                        result = await adapter(ctx)
                    except Exception as exc:
                        logger.exception(
                            "[Publish] adapter result: content=%s platform=%s exception",
                            content_id,
                            platform,
                        )
                        result = _failure_result(platform, str(exc), account)
                    result.setdefault("platform", platform)
                    result.setdefault("account_id", str(account.id))
                    result.setdefault("account_name", account.account_name)
                    if not result.get("success"):
                        all_ok = False

                await PublishService._record_attempt(
                    db, content_id=content_id, platform=platform, account=account, result=result,
                )
                results.append(result)
                logger.info(
                    "[Publish] adapter result: content=%s platform=%s success=%s post_id=%s",
                    content_id,
                    platform,
                    result.get("success"),
                    result.get("platform_post_id"),
                )

            if test_mode:
                await db.commit()
                finalized = True
                refreshed = await PublishService._get_content(db, content_id)
                logger.info("[Publish] success: content=%s test=true", content_id)
                return {
                    "content_id": content_id,
                    "status": refreshed.status,
                    "previous_status": previous_status,
                    "published_at": refreshed.published_at,
                    "results": results,
                    "all_success": all_ok,
                    "test": True,
                }

            item = await PublishService._get_content(db, content_id)
            success_count = sum(1 for r in results if r.get("success"))
            fail_count = len(results) - success_count
            if all_ok:
                item.status = "published"
                item.published_at = datetime.now(timezone.utc)
                terminal_status = "published"
                logger.info("[Publish] success: content=%s platforms=%s", content_id, target_platforms)
            elif success_count > 0 and fail_count > 0:
                item.status = "partial_failed"
                item.published_at = datetime.now(timezone.utc)
                terminal_status = "partial_failed"
                logger.info(
                    "[Publish] partial_failed: content=%s ok=%s fail=%s",
                    content_id,
                    success_count,
                    fail_count,
                )
            else:
                item.status = "failed"
                terminal_status = "failed"
                logger.info("[Publish] failed: content=%s platforms=%s", content_id, target_platforms)

            parts = []
            for r in results:
                st = "ok" if r.get("success") else "fail"
                post_id = r.get("platform_post_id") or r.get("error") or "n/a"
                parts.append(f"{r['platform']}: {st} {post_id}")
            _append_publish_note(item, f"[Publish] {' | '.join(parts)}")
            await db.commit()
            finalized = True

            refreshed = await PublishService._get_content(db, content_id)
            return {
                "content_id": content_id,
                "status": refreshed.status,
                "previous_status": previous_status,
                "published_at": refreshed.published_at,
                "results": results,
                "all_success": all_ok,
                "test": False,
            }

        except HTTPException as exc:
            logger.info(
                "[Publish] failed: content=%s http_error=%s",
                content_id,
                exc.detail,
            )
            # Safety blocks commit via record_blocked — rollback would fault the session.
            if exc.status_code != 400:
                await db.rollback()
            raise

        except Exception as exc:
            logger.exception("[Publish] failed: content=%s error=%s", content_id, exc)
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Publishing failed: {exc}") from exc

        finally:
            logger.info(
                "[Publish] finally: content=%s finalized=%s terminal_status=%s",
                content_id,
                finalized,
                terminal_status,
            )
            if not test_mode and not finalized:
                try:
                    if not results:
                        fail_result = _failure_result(
                            target_platforms[0] if target_platforms else "unknown",
                            "Publishing interrupted",
                        )
                        await PublishService._record_attempt(
                            db,
                            content_id=content_id,
                            platform=fail_result["platform"],
                            account=None,
                            result=fail_result,
                        )
                    await PublishService._force_terminal_status(
                        db,
                        content_id,
                        status="failed",
                        error="Publishing interrupted",
                    )
                except Exception:
                    logger.exception(
                        "[Publish] finally: recovery failed content=%s",
                        content_id,
                    )
