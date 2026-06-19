"""Telegram ingestion settings and album assembly buffer."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DEFAULT_SETTINGS_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class TelegramIngestionSettings(Base):
    __tablename__ = "telegram_ingestion_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=DEFAULT_SETTINGS_ID,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    allowed_group_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    default_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True,
    )
    default_status: Mapped[str] = mapped_column(
        String(30), default="needs_review", server_default="needs_review",
    )
    default_target_languages: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    auto_classification: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    auto_enrichment: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    quality_checks_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class TelegramAlbumPending(Base):
    __tablename__ = "telegram_album_pending"
    __table_args__ = (
        UniqueConstraint("group_id", "message_id", name="uq_tg_album_group_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    group_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    media_group_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True,
    )
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_type: Mapped[str] = mapped_column(String(20), nullable=False)
    refs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
