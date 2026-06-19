"""Media library — centralized repository reusing media_files storage."""
from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.storage import storage
from app.models.campaign import Campaign
from app.models.client import Client
from app.models.content import ContentItem
from app.models.media import MediaFile
from app.models.media_library import LIBRARY_FILE_TYPES, MediaAsset
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.media_service import MediaService

logger = logging.getLogger(__name__)

_DOC_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_MAX_DOC_BYTES = 50 * 1024 * 1024

_TAG_SYSTEM = """\
Analyze this media asset for a B2B factory / industrial marketing library.
Return ONLY JSON:
{
  "objects": ["tag", "..."],
  "products": ["tag", "..."],
  "equipment": ["tag", "..."],
  "industries": ["tag", "..."],
  "suggested_tags": ["tag", "..."]
}
Rules:
- 2-6 items per category when applicable
- Use concise English tags
- products = manufactured goods or product categories visible
- equipment = machinery, tools, production lines
- industries = target industry verticals
"""


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,;\n]+", raw)
    return [p.strip() for p in parts if p.strip()]


def _caption_preview(item: ContentItem) -> str | None:
    for field in ("caption_short_en", "caption_short_ru", "caption_short_uz", "internal_notes"):
        val = getattr(item, field, None)
        if val and str(val).strip():
            text = str(val).strip()
            return text[:100] + ("…" if len(text) > 100 else "")
    return None


def _asset_urls(asset: MediaAsset) -> tuple[str | None, str | None]:
    mf = asset.media_file
    if not mf:
        url = storage.get_url(asset.storage_path)
        return url, None
    url = storage.get_url(mf.storage_path)
    thumb = storage.get_url(mf.thumbnail_path) if mf.thumbnail_path else None
    return url, thumb


def _serialize_asset(
    asset: MediaAsset,
    *,
    usage_count: int = 0,
) -> dict[str, Any]:
    url, thumb = _asset_urls(asset)
    tags = asset.tags_json if isinstance(asset.tags_json, list) else []
    return {
        "id": asset.id,
        "client_id": asset.client_id,
        "campaign_id": asset.campaign_id,
        "title": asset.title,
        "description": asset.description,
        "file_type": asset.file_type,
        "original_filename": asset.original_filename,
        "storage_path": asset.storage_path,
        "tags_json": tags,
        "ai_labels_json": asset.ai_labels_json,
        "uploaded_by": asset.uploaded_by,
        "created_at": asset.created_at,
        "client_name": asset.client.name if asset.client else None,
        "campaign_name": asset.campaign.name if asset.campaign else None,
        "url": url,
        "thumbnail_url": thumb or (url if asset.file_type in ("image", "logo") else None),
        "usage_count": usage_count,
        "mime_type": asset.media_file.mime_type if asset.media_file else None,
        "file_size": asset.media_file.file_size if asset.media_file else None,
    }


class MediaLibraryService:
    @staticmethod
    async def _usage_counts(db: AsyncSession, media_file_ids: list[UUID]) -> dict[UUID, int]:
        if not media_file_ids:
            return {}
        direct_r = await db.execute(
            select(ContentItem.media_file_id, func.count())
            .where(ContentItem.media_file_id.in_(media_file_ids))
            .group_by(ContentItem.media_file_id)
        )
        counts = {row[0]: int(row[1]) for row in direct_r.all()}
        return counts

    @staticmethod
    async def _related_content(db: AsyncSession, media_file_id: UUID) -> list[dict[str, Any]]:
        r = await db.execute(
            select(ContentItem)
            .where(ContentItem.media_file_id == media_file_id)
            .order_by(ContentItem.created_at.desc())
            .limit(50)
        )
        items = list(r.scalars().all())
        return [
            {
                "id": item.id,
                "status": item.status,
                "source": item.source,
                "created_at": item.created_at,
                "caption_preview": _caption_preview(item),
            }
            for item in items
        ]

    @staticmethod
    async def list_assets(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        campaign_id: UUID | None = None,
        file_type: str | None = None,
        search: str | None = None,
        tag: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        q = (
            select(MediaAsset)
            .options(
                selectinload(MediaAsset.client),
                selectinload(MediaAsset.campaign),
                selectinload(MediaAsset.media_file),
            )
            .order_by(MediaAsset.created_at.desc())
        )
        count_q = select(func.count()).select_from(MediaAsset)

        if client_id:
            q = q.where(MediaAsset.client_id == client_id)
            count_q = count_q.where(MediaAsset.client_id == client_id)
        if campaign_id:
            q = q.where(MediaAsset.campaign_id == campaign_id)
            count_q = count_q.where(MediaAsset.campaign_id == campaign_id)
        if file_type:
            q = q.where(MediaAsset.file_type == file_type)
            count_q = count_q.where(MediaAsset.file_type == file_type)
        if search:
            pattern = f"%{search.strip()}%"
            filt = or_(
                MediaAsset.title.ilike(pattern),
                MediaAsset.description.ilike(pattern),
                MediaAsset.original_filename.ilike(pattern),
            )
            q = q.where(filt)
            count_q = count_q.where(filt)
        if tag:
            q = q.where(MediaAsset.tags_json.contains([tag.strip()]))
            count_q = count_q.where(MediaAsset.tags_json.contains([tag.strip()]))

        total = (await db.execute(count_q)).scalar_one()
        rows = list((await db.execute(q.offset(skip).limit(limit))).scalars().all())
        mf_ids = [a.media_file_id for a in rows]
        usage_map = await MediaLibraryService._usage_counts(db, mf_ids)

        items = [
            _serialize_asset(a, usage_count=usage_map.get(a.media_file_id, 0))
            for a in rows
        ]
        logger.info("[Media Library] listed: total=%s returned=%s", total, len(items))
        return {"items": items, "total": total}

    @staticmethod
    async def get_asset(db: AsyncSession, asset_id: UUID) -> dict[str, Any]:
        r = await db.execute(
            select(MediaAsset)
            .options(
                selectinload(MediaAsset.client),
                selectinload(MediaAsset.campaign),
                selectinload(MediaAsset.media_file),
            )
            .where(MediaAsset.id == asset_id)
        )
        asset = r.scalar_one_or_none()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found")

        usage_map = await MediaLibraryService._usage_counts(db, [asset.media_file_id])
        data = _serialize_asset(asset, usage_count=usage_map.get(asset.media_file_id, 0))
        data["related_content"] = await MediaLibraryService._related_content(db, asset.media_file_id)
        logger.info("[Media Library] detail: id=%s usage=%s", asset_id, data["usage_count"])
        return data

    @staticmethod
    async def _validate_campaign(db: AsyncSession, campaign_id: UUID | None, client_id: UUID) -> None:
        if not campaign_id:
            return
        r = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
        campaign = r.scalar_one_or_none()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if campaign.client_id != client_id:
            raise HTTPException(status_code=400, detail="Campaign belongs to a different client")

    @staticmethod
    def _resolve_library_type(
        mime: str,
        filename: str,
        requested: str | None,
        media_file_type: str,
    ) -> str:
        if requested and requested in LIBRARY_FILE_TYPES:
            return requested
        lower = filename.lower()
        if "logo" in lower:
            return "logo"
        if "cert" in lower:
            return "certificate"
        if "catalog" in lower or "catalogue" in lower:
            return "catalog"
        if mime in _DOC_MIMES or lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
            return "document"
        if media_file_type == "video":
            return "video"
        if media_file_type == "image":
            return "image"
        return "other"

    @staticmethod
    async def _save_document_media(
        db: AsyncSession,
        client_id: UUID,
        file: UploadFile,
    ) -> MediaFile:
        client_r = await db.execute(select(Client).where(Client.id == client_id))
        if not client_r.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Client not found")

        mime = (file.content_type or "application/octet-stream").lower().split(";")[0].strip()
        fname = file.filename or "document"
        lower = fname.lower()
        if mime not in _DOC_MIMES and not lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
            raise HTTPException(
                status_code=415,
                detail="Document uploads support PDF, Word, and Excel files",
            )

        data = await file.read()
        if len(data) > _MAX_DOC_BYTES:
            raise HTTPException(status_code=413, detail="Document too large (max 50 MB)")
        if not data:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        folder = f"clients/{client_id}/library"
        path = await storage.save_file(data, fname, folder)

        media = MediaFile(
            client_id=client_id,
            original_filename=fname,
            file_type="document",
            mime_type=mime,
            storage_path=path,
            thumbnail_path=None,
            file_size=len(data),
        )
        db.add(media)
        await db.flush()
        return media

    @staticmethod
    async def _ensure_not_registered(db: AsyncSession, media_file_id: UUID) -> None:
        existing = await db.execute(
            select(MediaAsset.id).where(MediaAsset.media_file_id == media_file_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="File already registered in media library")

    @staticmethod
    async def _generate_ai_labels(
        asset: MediaAsset,
        media: MediaFile,
        *,
        image_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        labels: dict[str, Any] = {
            "objects": [],
            "products": [],
            "equipment": [],
            "industries": [],
            "source": "fallback",
        }
        try:
            if media.file_type == "image" and image_bytes:
                _validate_api_key()
                from app.services.ocr_service import _resize_for_vision

                jpeg_bytes, mime = _resize_for_vision(image_bytes)
                import base64

                b64 = base64.b64encode(jpeg_bytes).decode()
                openai = get_openai()
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": _TAG_SYSTEM},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        f"Title: {asset.title}\n"
                                        f"Filename: {asset.original_filename}\n"
                                        f"Library type: {asset.file_type}\n"
                                        f"Tags: {', '.join(asset.tags_json or [])}"
                                    ),
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                                },
                            ],
                        },
                    ],
                    temperature=0.2,
                    max_tokens=600,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                labels = {
                    "objects": list(parsed.get("objects") or [])[:8],
                    "products": list(parsed.get("products") or [])[:8],
                    "equipment": list(parsed.get("equipment") or [])[:8],
                    "industries": list(parsed.get("industries") or [])[:8],
                    "source": "ai",
                }
                suggested = parsed.get("suggested_tags") or []
                if suggested and asset.tags_json is None:
                    asset.tags_json = [str(t) for t in suggested[:10]]
            else:
                text_blob = f"{asset.title} {asset.original_filename} {asset.description or ''}"
                tokens = {t for t in re.findall(r"[a-z0-9]{4,}", text_blob.lower())}
                if asset.file_type in ("catalog", "document"):
                    labels["objects"].append("document")
                if asset.file_type == "logo":
                    labels["objects"].append("logo")
                labels["products"] = [t for t in tokens if t in ("steel", "pipe", "valve", "pump", "motor")][:5]
                labels["source"] = "fallback"
        except Exception as exc:
            logger.info("[Media Library] AI tagging fallback: %s", exc)
        return labels

    @staticmethod
    async def upload(
        db: AsyncSession,
        *,
        client_id: UUID,
        file: UploadFile,
        title: str | None = None,
        description: str | None = None,
        campaign_id: UUID | None = None,
        file_type: str | None = None,
        tags: str | None = None,
        uploaded_by: str | None = None,
        run_ai_tagging: bool = True,
    ) -> dict[str, Any]:
        await MediaLibraryService._validate_campaign(db, campaign_id, client_id)

        mime = (file.content_type or "").lower()
        fname = file.filename or "upload"
        lower = fname.lower()
        is_doc = mime in _DOC_MIMES or lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx"))
        image_bytes: bytes | None = None

        if is_doc:
            media = await MediaLibraryService._save_document_media(db, client_id, file)
        else:
            media = await MediaService.upload(db, client_id, file)
            if media.file_type == "image":
                try:
                    image_bytes = await storage.read_file_bytes(media.storage_path)
                except Exception:
                    image_bytes = None

        await MediaLibraryService._ensure_not_registered(db, media.id)

        library_type = MediaLibraryService._resolve_library_type(
            mime, fname, file_type, media.file_type,
        )
        tag_list = _parse_tags(tags)

        asset = MediaAsset(
            client_id=client_id,
            campaign_id=campaign_id,
            media_file_id=media.id,
            title=(title or fname).strip()[:255],
            description=description,
            file_type=library_type,
            original_filename=media.original_filename,
            storage_path=media.storage_path,
            tags_json=tag_list or None,
            uploaded_by=uploaded_by,
        )
        db.add(asset)
        await db.flush()

        if run_ai_tagging:
            asset.ai_labels_json = await MediaLibraryService._generate_ai_labels(
                asset, media, image_bytes=image_bytes,
            )

        await db.commit()
        await db.refresh(asset)
        logger.info("[Media Library] upload: asset=%s media_file=%s", asset.id, media.id)
        return await MediaLibraryService.get_asset(db, asset.id)
