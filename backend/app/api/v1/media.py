from uuid import UUID
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.media_service import MediaService
from app.schemas.content import MediaFileResponse

router = APIRouter(prefix="/media", tags=["media"])


@router.post("/upload/{client_id}", status_code=201)
async def upload_media(
    client_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload an image or video for a client.
    - Images: JPG, PNG, WebP — max 20 MB
    - Videos: MP4, MOV, WebM — max 200 MB
    Returns media metadata including a usable URL.
    """
    media = await MediaService.upload(db, client_id, file)
    return MediaService.with_url(media)


@router.get("/client/{client_id}")
async def list_client_media(
    client_id: UUID,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    items = await MediaService.list_for_client(db, client_id, skip, limit)
    return [MediaService.with_url(m) for m in items]


@router.delete("/{media_id}", status_code=204)
async def delete_media(media_id: UUID, db: AsyncSession = Depends(get_db)):
    await MediaService.delete(db, media_id)
