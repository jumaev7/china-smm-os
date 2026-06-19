from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.media_library import (
    MediaAssetDetailResponse,
    MediaAssetListResponse,
    MediaAssetUploadResponse,
)
from app.services.media_library_service import MediaLibraryService

router = APIRouter(prefix="/media-library", tags=["media-library"])


@router.get("", response_model=MediaAssetListResponse)
async def list_media_assets(
    client_id: UUID | None = None,
    campaign_id: UUID | None = None,
    file_type: str | None = None,
    search: str | None = None,
    tag: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MediaLibraryService.list_assets(
            db,
            client_id=client_id,
            campaign_id=campaign_id,
            file_type=file_type,
            search=search,
            tag=tag,
            skip=skip,
            limit=limit,
        ),
        label="media-library.list",
    )


@router.post("/upload", response_model=MediaAssetUploadResponse, status_code=201)
async def upload_media_asset(
    client_id: UUID = Form(...),
    file: UploadFile = File(...),
    title: str | None = Form(None),
    description: str | None = Form(None),
    campaign_id: UUID | None = Form(None),
    file_type: str | None = Form(None),
    tags: str | None = Form(None),
    uploaded_by: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MediaLibraryService.upload(
            db,
            client_id=client_id,
            file=file,
            title=title,
            description=description,
            campaign_id=campaign_id,
            file_type=file_type,
            tags=tags,
            uploaded_by=uploaded_by,
        ),
        label="media-library.upload",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/{asset_id}", response_model=MediaAssetDetailResponse)
async def get_media_asset(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await MediaLibraryService.get_asset(db, asset_id)
