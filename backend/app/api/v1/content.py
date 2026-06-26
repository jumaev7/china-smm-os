from uuid import UUID
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit
from app.core.storage import storage
from app.services.content_service import ContentService
from app.schemas.content import (
    ContentCreate, ContentUpdate, ContentResponse, ContentListResponse,
    ContentReadinessResponse, ReviewLinkResponse, ClientReviewPreviewResponse,
    PublishContentResponse,
    PublishSafetyResponse,
    BurnSubtitlesRequest,
    VoiceoverRequest,
    FinalVideoRequest,
    MediaRequestBody,
    MediaRequestResponse,
)
from app.schemas.platform_relationships import ContentLinksUpdate, PlatformRelationshipsResponse
from app.services.platform_relationships_service import PlatformRelationshipsService
from app.schemas.publishing import PublishContentRequest, PublishAttemptListResponse
from app.services.content_readiness_service import ContentReadinessService
from app.services.content_review_service import ContentReviewService
from app.services.publish_safety_service import PublishSafetyService
from app.services.publish_service import PublishService
from app.services.media_request_service import MediaRequestService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["content"])


@router.post("", response_model=ContentResponse, status_code=201)
async def create_content(data: ContentCreate, db: AsyncSession = Depends(get_db)):
    item = await ContentService.create(db, data)
    return ContentService.serialize(item)


@router.get("", response_model=ContentListResponse)
async def list_content(
    client_id: UUID | None = None,
    status: str | None = None,
    source: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    await PublishService.recover_stale_publishing(db)
    limit = clamp_limit(limit)
    items, total = await ContentService.list_all(db, client_id, status, skip, limit, source)
    return {"items": [ContentService.serialize(i) for i in items], "total": total}


@router.post("/{content_id}/review-link", response_model=ReviewLinkResponse)
async def create_review_link(content_id: UUID, db: AsyncSession = Depends(get_db)):
    return await ContentReviewService.create_review_link(db, content_id)


@router.get("/{content_id}/readiness", response_model=ContentReadinessResponse)
async def get_content_readiness(
    content_id: UUID,
    intent: str = "approve",
    db: AsyncSession = Depends(get_db),
):
    item = await ContentService.get(db, content_id)
    return await ContentReadinessService.evaluate(db, item, intent=intent)


@router.get("/{content_id}/publish-safety", response_model=PublishSafetyResponse)
async def get_publish_safety(
    content_id: UUID,
    mode: str | None = None,
    platform: str | None = None,
    account_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    item = await ContentService.get(db, content_id)
    target_platforms = [platform] if platform else list(item.platforms or [])
    resolved_mode = mode or "manual_publish"
    return await PublishSafetyService.evaluate(
        db,
        item,
        target_platforms=target_platforms,
        account_id=account_id,
        mode=resolved_mode,
    )


@router.get("/{content_id}", response_model=ContentResponse)
async def get_content(content_id: UUID, db: AsyncSession = Depends(get_db)):
    await PublishService.recover_stale_publishing(db, content_id=content_id)
    item = await ContentService.get(db, content_id)
    return await ContentService.serialize_detail(db, item)


@router.patch("/{content_id}", response_model=ContentResponse)
async def update_content(
    content_id: UUID, data: ContentUpdate, db: AsyncSession = Depends(get_db)
):
    item = await ContentService.update(db, content_id, data)
    return await ContentService.serialize_detail(db, item)


@router.post("/{content_id}/approve", response_model=ContentResponse)
async def approve_content(content_id: UUID, db: AsyncSession = Depends(get_db)):
    item = await ContentService.approve(db, content_id)
    return await ContentService.serialize_detail(db, item)


@router.post("/{content_id}/request-media", response_model=MediaRequestResponse)
async def request_media_from_client(
    content_id: UUID,
    body: MediaRequestBody | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or MediaRequestBody()
    return await MediaRequestService.request_media(db, content_id, required_format=req.format)


@router.post("/{content_id}/client-review/send-preview", response_model=ClientReviewPreviewResponse)
async def send_client_review_preview(content_id: UUID, db: AsyncSession = Depends(get_db)):
    """Send Telegram client-review preview only (no publishing)."""
    result = await ContentReviewService.send_client_review_preview_manual(db, content_id, force=True)
    return ClientReviewPreviewResponse(
        sent=bool(result.get("sent")),
        sent_at=result.get("sent_at"),
        error=result.get("error"),
        skipped=bool(result.get("skipped")),
        reason=result.get("reason"),
    )


@router.post("/{content_id}/publish", response_model=PublishContentResponse)
async def publish_content(
    content_id: UUID,
    data: PublishContentRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = data or PublishContentRequest()
    logger.info(
        "[Publish] API called: content_id=%s mode=%s test=%s platforms=%s account_id=%s",
        content_id,
        req.mode,
        req.test,
        req.platforms,
        req.account_id,
    )
    try:
        result = await PublishService.publish_content(db, content_id, request=req)
        logger.info(
            "[Publish] API called: content_id=%s completed status=%s all_success=%s",
            content_id,
            result.get("status"),
            result.get("all_success"),
        )
        return result
    except HTTPException:
        logger.info("[Publish] API called: content_id=%s rejected", content_id)
        raise


@router.get("/{content_id}/publish-history", response_model=PublishAttemptListResponse)
async def get_publish_history(content_id: UUID, db: AsyncSession = Depends(get_db)):
    await ContentService.get(db, content_id)
    items, total = await PublishService.list_history(db, content_id)
    return {"items": items, "total": total}


@router.post("/{content_id}/burn-subtitles", response_model=ContentResponse)
async def burn_subtitles_into_video(
    content_id: UUID,
    data: BurnSubtitlesRequest,
    db: AsyncSession = Depends(get_db),
):
    """Burn selected translated SRT into a new MP4; original video is preserved."""
    item = await ContentService.burn_subtitled_video(db, content_id, data.lang)
    return ContentService.serialize(item)


@router.post("/{content_id}/generate-voiceover", response_model=ContentResponse)
async def generate_voiceover(
    content_id: UUID,
    data: VoiceoverRequest,
    db: AsyncSession = Depends(get_db),
):
    """AI voice dub from translated subtitles; original video is preserved."""
    logger.info(
        "[Voiceover] mode received: %s (lang=%s content=%s)",
        data.mode,
        data.lang,
        content_id,
    )
    item = await ContentService.generate_voiceover(db, content_id, data.lang, mode=data.mode)
    payload = ContentService.serialize(item)
    logger.info(
        "[Voiceover] response URLs: fitted_ru=%s extended_ru=%s",
        payload.get("dubbed_video_url_ru"),
        payload.get("dubbed_video_extended_url_ru"),
    )
    return payload


@router.post("/{content_id}/generate-final-video", response_model=ContentResponse)
async def generate_final_video_endpoint(
    content_id: UUID,
    data: FinalVideoRequest,
    db: AsyncSession = Depends(get_db),
):
    """Combined export: burned subtitles + dubbed voice (auto-generates dub if missing)."""
    logger.info("[Final Export] subtitle: %s", data.subtitle_lang)
    logger.info("[Final Export] voice: %s", data.voice_lang)
    logger.info("[Final Export] mode: %s", data.voice_mode)
    item, output_key = await ContentService.generate_final_export(
        db,
        content_id,
        data.subtitle_lang,
        data.voice_lang,
        data.voice_mode,
    )
    payload = ContentService.serialize(item)
    payload["generated_final_video_url"] = storage.get_url(output_key)
    logger.info("[Final Export] output: %s", output_key)
    return payload


@router.delete("/{content_id}", status_code=204)
async def delete_content(content_id: UUID, db: AsyncSession = Depends(get_db)):
    await ContentService.delete(db, content_id)


@router.get("/{content_id}/related", response_model=PlatformRelationshipsResponse)
async def get_content_related(content_id: UUID, db: AsyncSession = Depends(get_db)):
    return await PlatformRelationshipsService.for_content(db, content_id)


@router.patch("/{content_id}/links", response_model=ContentResponse)
async def update_content_links(
    content_id: UUID,
    body: ContentLinksUpdate,
    db: AsyncSession = Depends(get_db),
):
    updates = body.model_dump(exclude_unset=True)
    item = await ContentService.update_links(
        db,
        content_id,
        linked_sales_lead_id=updates.get("linked_sales_lead_id", ...),
        linked_buyer_id=updates.get("linked_buyer_id", ...),
        linked_sales_deal_id=updates.get("linked_sales_deal_id", ...),
    )
    return ContentService.serialize(item)
