import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, Boolean, Integer, Numeric, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from app.core.database import Base


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_language: Mapped[str] = mapped_column(String(10), default="zh")  # zh, en, ru
    business_category: Mapped[str] = mapped_column(String(100), nullable=False)
    content_style: Mapped[str] = mapped_column(String(100), default="professional")
    # professional | casual | luxury | educational | promotional
    status: Mapped[str] = mapped_column(String(20), default="active")
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Brand profile
    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    products_services: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    tone_of_voice: Mapped[str] = mapped_column(String(30), default="friendly")
    preferred_languages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cta_phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cta_telegram: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cta_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cta_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    words_to_avoid: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtag_preferences: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Telegram sender ID — set when client sends via Telegram bot (private chat)
    telegram_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # Telegram group chat — client + admin + bot workflow
    telegram_group_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    telegram_group_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Separate Telegram channel/supergroup for publishing (not the intake group)
    telegram_publish_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_publish_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_publish_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # auto_create_from_media | admin_controlled_buffer
    telegram_workflow_mode: Mapped[str] = mapped_column(
        String(40), default="auto_create_from_media", server_default="auto_create_from_media",
    )
    # When true, new Telegram inbox items auto-create draft content via AI (never publish)
    operator_auto_draft_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    # Active draft/ready content task for Telegram group workflow
    telegram_active_content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True,
    )
    # Billing / subscription package
    plan_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    monthly_fee: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    monthly_post_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    billing_status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False,
    )
    billing_cycle_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    billing_cycle_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    media_files: Mapped[list["MediaFile"]] = relationship(  # noqa: F821
        back_populates="client", cascade="all, delete-orphan"
    )
    content_items: Mapped[list["ContentItem"]] = relationship(  # noqa: F821
        back_populates="client",
        cascade="all, delete-orphan",
        foreign_keys="ContentItem.client_id",
    )
    active_content: Mapped["ContentItem | None"] = relationship(  # noqa: F821
        foreign_keys=[telegram_active_content_id],
    )
