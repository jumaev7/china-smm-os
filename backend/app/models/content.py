import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, ForeignKey, func, ARRAY, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    media_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True
    )

    # Platforms: ['instagram', 'facebook', 'tiktok', 'telegram', 'linkedin']
    platforms: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    # Status workflow: new/needs_review/needs_caption → ready → approved → scheduled → published | rejected
    status: Mapped[str] = mapped_column(String(30), default="draft")

    # Origin: manual | telegram | telegram_group
    source: Mapped[str] = mapped_column(String(20), default="manual")

    # Set when source=telegram_group (group title at import time)
    telegram_group_title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Telegram group workflow — link to source message & instruction history
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    telegram_excluded: Mapped[bool] = mapped_column(default=False, server_default="false")
    telegram_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Manual override for Context AI category (food, auto_service, …)
    context_ai_override: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Telegram ingestion enrichment
    telegram_original_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_classification: Mapped[str | None] = mapped_column(String(50), nullable=True)
    suggestions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_media_group_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    telegram_forward_from: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # JSON list of buffered message/media refs when source=tg_group_buffer
    telegram_buffer_refs: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Short captions (≤150 chars each, for caption line)
    caption_short_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_short_uz: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_short_en: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Long captions (full post body)
    caption_long_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_long_uz: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_long_en: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Hashtags (comma-separated or raw string)
    hashtags: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Operator notes
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Client public review link (no login)
    review_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    client_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    client_review_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending | approved | changes_requested — set when admin approves and client review starts
    client_review_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    client_review_preview_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    client_review_preview_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Media request assistant — ask client for materials via Telegram intake group
    media_request_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    media_request_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_request_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    media_request_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    parent_content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    parent_media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    linked_sales_lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_leads.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    linked_buyer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buyers.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    linked_sales_deal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_deals.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    client: Mapped["Client"] = relationship(
        back_populates="content_items",
        foreign_keys=[client_id],
    )  # noqa: F821
    media_file: Mapped["MediaFile | None"] = relationship(back_populates="content_items")  # noqa: F821
    calendar_entry: Mapped["CalendarEntry | None"] = relationship(  # noqa: F821
        back_populates="content_item", cascade="all, delete-orphan", uselist=False
    )
    campaign: Mapped["Campaign | None"] = relationship(  # noqa: F821
        back_populates="content_items",
        foreign_keys=[campaign_id],
    )
