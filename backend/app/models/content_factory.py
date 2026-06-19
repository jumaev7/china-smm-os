"""AI Content Factory — multiple content variations from one source asset."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class ContentFactory(Base):
    __tablename__ = "content_factories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    source_media_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_files.id", ondelete="CASCADE"), nullable=True,
    )
    source_content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="generated", server_default="generated")
    input_type: Mapped[str | None] = mapped_column(String(20), nullable=True, default="image")
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_languages_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    client: Mapped["Client"] = relationship(foreign_keys=[client_id])  # noqa: F821
    source_media: Mapped["MediaFile | None"] = relationship(foreign_keys=[source_media_id])  # noqa: F821
    items: Mapped[list["ContentFactoryItem"]] = relationship(
        back_populates="factory",
        cascade="all, delete-orphan",
        order_by="ContentFactoryItem.created_at",
    )


class ContentFactoryItem(Base):
    __tablename__ = "content_factory_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    factory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_factories.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    theme: Mapped[str] = mapped_column(String(500), nullable=False)
    angle: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    platforms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    captions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True,
    )
    review_status: Mapped[str | None] = mapped_column(String(30), nullable=True, default="generated")
    headline: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cta_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_scores_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform_variants_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    factory: Mapped["ContentFactory"] = relationship(back_populates="items")
