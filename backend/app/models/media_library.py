"""Media library — centralized client media repository (links to media_files storage)."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

LIBRARY_FILE_TYPES = frozenset({
    "image", "video", "document", "logo", "certificate", "catalog", "other",
})


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    media_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False, unique=True, index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    tags_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ai_labels_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    client: Mapped["Client"] = relationship(foreign_keys=[client_id])  # noqa: F821
    campaign: Mapped["Campaign | None"] = relationship(  # noqa: F821
        back_populates="media_assets",
        foreign_keys=[campaign_id],
    )
    media_file: Mapped["MediaFile"] = relationship(foreign_keys=[media_file_id])  # noqa: F821
