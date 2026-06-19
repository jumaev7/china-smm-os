from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.content_factory import (
    ContentFactoryCreateDraftRequest,
    ContentFactoryDraftResponse,
    ContentFactoryGenerateRequest,
    ContentFactoryResponse,
    ContentFactoryReviewUpdateRequest,
    ContentFactoryScheduleRequest,
    ContentFactoryTelegramGenerateRequest,
    ContentFactoryTextGenerateRequest,
)
from app.services.content_factory_dashboard_service import ContentFactoryDashboardService
from app.services.content_factory_service import ContentFactoryService

router = APIRouter(prefix="/content-factory", tags=["content-factory"])


@router.get("/dashboard")
async def content_factory_dashboard(
    client_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryDashboardService.dashboard(db, client_id=client_id)


@router.get("/library")
async def content_factory_library(
    client_id: UUID | None = Query(None),
    language: str | None = Query(None),
    content_type: str | None = Query(None),
    content_category: str | None = Query(None),
    platform: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryDashboardService.library(
        db,
        client_id=client_id,
        language=language,
        content_type=content_type,
        content_category=content_category,
        platform=platform,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/review")
async def content_factory_review(
    client_id: UUID | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryDashboardService.review_queue(
        db, client_id=client_id, status=status,
    )


@router.get("/list")
async def content_factory_list(
    client_id: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryDashboardService.list_factories(
        db, client_id=client_id, limit=limit,
    )


@router.get("/recommendations/{client_id}")
async def content_factory_recommendations(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryDashboardService.recommendations(db, client_id=client_id)


@router.get("/demo/{client_id}")
async def content_factory_demo(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryDashboardService.demo_samples(db, client_id=client_id)


@router.post("/generate", response_model=ContentFactoryResponse)
async def generate_content_factory(
    body: ContentFactoryGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryService.generate(db, body)


@router.post("/generate-text", response_model=ContentFactoryResponse)
async def generate_content_factory_text(
    body: ContentFactoryTextGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryService.generate_from_text(db, body)


@router.post("/from-telegram/{content_id}", response_model=ContentFactoryResponse)
async def generate_from_telegram_content(
    content_id: UUID,
    body: ContentFactoryTelegramGenerateRequest = Body(default=ContentFactoryTelegramGenerateRequest()),
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryService.generate_from_telegram(
        db,
        content_id,
        number_of_variations=body.number_of_variations,
        target_languages=body.target_languages,
    )


@router.patch("/items/{item_id}/review")
async def update_factory_item_review(
    item_id: UUID,
    body: ContentFactoryReviewUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryDashboardService.update_review_status(
        db, item_id, review_status=body.review_status, notes=body.notes,
    )


@router.post("/items/{item_id}/schedule")
async def schedule_factory_item(
    item_id: UUID,
    body: ContentFactoryScheduleRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryService.schedule_item(
        db, item_id, scheduled_for=body.scheduled_for, platforms=body.platforms,
    )


@router.post("/items/{item_id}/create-draft", response_model=ContentFactoryDraftResponse)
async def create_draft_from_factory_item(
    item_id: UUID,
    body: ContentFactoryCreateDraftRequest = Body(default=ContentFactoryCreateDraftRequest()),
    db: AsyncSession = Depends(get_db),
):
    return await ContentFactoryService.create_draft_from_item(
        db, item_id, generate_ai=body.generate_ai,
    )


@router.get("/{factory_id}", response_model=ContentFactoryResponse)
async def get_content_factory(
    factory_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ContentFactoryService.get_factory(db, factory_id),
        label="content-factory.get",
    )
