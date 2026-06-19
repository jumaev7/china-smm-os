from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

MediaLibraryFileType = Literal[
    "image", "video", "document", "logo", "certificate", "catalog", "other",
]


class MediaAssetAiLabels(BaseModel):
    objects: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    source: str | None = None


class MediaAssetRelatedContent(BaseModel):
    id: UUID
    status: str
    source: str
    created_at: datetime
    caption_preview: str | None = None


class MediaAssetListItem(BaseModel):
    id: UUID
    client_id: UUID
    campaign_id: UUID | None
    title: str
    description: str | None
    file_type: str
    original_filename: str
    storage_path: str
    tags_json: list[str] | None
    ai_labels_json: dict[str, Any] | None
    uploaded_by: str | None
    created_at: datetime
    client_name: str | None = None
    campaign_name: str | None = None
    url: str | None = None
    thumbnail_url: str | None = None
    usage_count: int = 0


class MediaAssetListResponse(BaseModel):
    items: list[MediaAssetListItem]
    total: int


class MediaAssetDetailResponse(MediaAssetListItem):
    mime_type: str | None = None
    file_size: int | None = None
    related_content: list[MediaAssetRelatedContent] = Field(default_factory=list)


class MediaAssetUploadResponse(MediaAssetDetailResponse):
    pass
