import io
import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, UploadFile
from app.models.media import MediaFile
from app.models.client import Client
from app.core.storage import storage
from app.services.subtitle_service import all_subtitle_paths, all_burned_video_paths, all_dubbed_video_paths, all_final_video_paths

logger = logging.getLogger(__name__)

ALLOWED_IMAGES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEOS = {"video/mp4", "video/quicktime", "video/webm"}
# Also accept by extension when browser sends wrong mime
EXT_TO_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
}

MAX_IMAGE_BYTES = 20 * 1024 * 1024   # 20 MB
MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MB


def _resolve_mime(file: UploadFile) -> str:
    """Return canonical mime type; fall back to extension detection."""
    mime = (file.content_type or "").lower().split(";")[0].strip()
    if mime in ALLOWED_IMAGES | ALLOWED_VIDEOS:
        return mime
    # Try extension
    fname = (file.filename or "").lower()
    for ext, resolved in EXT_TO_MIME.items():
        if fname.endswith(ext):
            return resolved
    return mime  # Return as-is so the error message is meaningful


class MediaService:

    @staticmethod
    async def upload(db: AsyncSession, client_id: UUID, file: UploadFile) -> MediaFile:
        # Verify client exists
        result = await db.execute(select(Client).where(Client.id == client_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Client not found")

        mime = _resolve_mime(file)

        if mime in ALLOWED_IMAGES:
            file_type = "image"
            max_size = MAX_IMAGE_BYTES
        elif mime in ALLOWED_VIDEOS:
            file_type = "video"
            max_size = MAX_VIDEO_BYTES
        else:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"Unsupported file type: '{mime}'. "
                    "Allowed images: JPG, PNG, WebP. "
                    "Allowed videos: MP4, MOV, WebM."
                ),
            )

        data = await file.read()
        size_mb = len(data) / (1024 * 1024)
        limit_mb = max_size / (1024 * 1024)

        if len(data) > max_size:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File too large: {size_mb:.1f} MB. "
                    f"Maximum for {file_type}s: {limit_mb:.0f} MB."
                ),
            )

        if len(data) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # Save original under clients/<client_id>/
        folder = f"clients/{client_id}"
        path = await storage.save_file(data, file.filename or "upload", folder)

        # Generate thumbnail for images
        thumb_path: str | None = None
        if file_type == "image":
            thumb_path = await MediaService._make_thumbnail(data, path)

        # Run OCR on images — extract text (especially Chinese) for AI pre-fill
        # Result is returned in with_url() as ocr_text; not persisted in DB
        ocr_text: str = ""
        if file_type == "image":
            try:
                from app.services.ocr_service import extract_text
                ocr_text = await extract_text(data)
                if ocr_text:
                    logger.info(
                        "Upload OCR: extracted %d chars from '%s'",
                        len(ocr_text), file.filename,
                    )
            except Exception as exc:
                logger.warning("Upload OCR failed (non-fatal): %s", exc)

        media = MediaFile(
            client_id=client_id,
            original_filename=file.filename or "upload",
            file_type=file_type,
            mime_type=mime,
            storage_path=path,
            thumbnail_path=thumb_path,
            file_size=len(data),
        )
        # Stash ocr_text as a transient attribute so with_url() can include it
        media._ocr_text = ocr_text  # type: ignore[attr-defined]
        db.add(media)
        await db.commit()
        await db.refresh(media)
        media._ocr_text = ocr_text  # refresh clears instance attrs; restore  # type: ignore[attr-defined]
        return media

    @staticmethod
    async def _make_thumbnail(image_data: bytes, original_path: str) -> str | None:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_data))
            img.thumbnail((400, 400))
            # Convert palette/RGBA to RGB for JPEG
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=82)
            # Store thumbnail alongside original, with _thumb suffix
            import os
            base = os.path.splitext(original_path)[0]
            thumb_key = f"{base}_thumb.jpg"
            return await storage.save_file(buf.getvalue(), "thumb.jpg",
                                           os.path.dirname(thumb_key))
        except Exception:
            return None

    @staticmethod
    async def list_for_client(
        db: AsyncSession, client_id: UUID, skip: int = 0, limit: int = 50
    ) -> list[MediaFile]:
        result = await db.execute(
            select(MediaFile)
            .where(MediaFile.client_id == client_id)
            .order_by(MediaFile.uploaded_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def get(db: AsyncSession, media_id: UUID) -> MediaFile:
        result = await db.execute(select(MediaFile).where(MediaFile.id == media_id))
        media = result.scalar_one_or_none()
        if not media:
            raise HTTPException(status_code=404, detail="Media file not found")
        return media

    @staticmethod
    async def delete(db: AsyncSession, media_id: UUID) -> None:
        media = await MediaService.get(db, media_id)
        await storage.delete_file(media.storage_path)
        for sub_path in all_subtitle_paths(media.storage_path):
            if storage.exists(sub_path):
                await storage.delete_file(sub_path)
        for burned_path in all_burned_video_paths(media.storage_path):
            if storage.exists(burned_path):
                await storage.delete_file(burned_path)
        for dubbed_path in all_dubbed_video_paths(media.storage_path):
            if storage.exists(dubbed_path):
                await storage.delete_file(dubbed_path)
        for final_path in all_final_video_paths(media.storage_path):
            if storage.exists(final_path):
                await storage.delete_file(final_path)
        if media.thumbnail_path:
            await storage.delete_file(media.thumbnail_path)
        await db.delete(media)
        await db.commit()

    @staticmethod
    def with_url(media: MediaFile) -> dict:
        return {
            "id": media.id,
            "client_id": media.client_id,
            "original_filename": media.original_filename,
            "file_type": media.file_type,
            "mime_type": media.mime_type,
            "storage_path": media.storage_path,
            "thumbnail_path": media.thumbnail_path,
            "file_size": media.file_size,
            "url": storage.get_url(media.storage_path),
            "thumbnail_url": storage.get_url(media.thumbnail_path) if media.thumbnail_path else None,
            "uploaded_at": media.uploaded_at,
            # Transient — populated after upload, empty for DB-fetched records
            "ocr_text": getattr(media, "_ocr_text", ""),
        }
