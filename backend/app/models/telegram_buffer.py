"""Telegram group message buffer and update deduplication."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class TelegramGroupBufferMessage(Base):
    __tablename__ = "telegram_group_buffer_messages"
    __table_args__ = (
        UniqueConstraint("group_id", "message_id", name="uq_tg_buffer_group_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    group_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_id: Mapped[str] = mapped_column(String(50), nullable=False)
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)  # admin | client | unknown
    message_type: Mapped[str] = mapped_column(String(20), nullable=False)  # text | photo | video | document
    telegram_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True,
    )
    storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    # Operator inbox: new | used | ignored
    inbox_status: Mapped[str] = mapped_column(
        String(20), default="new", server_default="new", nullable=False,
    )
    linked_content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    ai_suggestion_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_suggested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    auto_drafted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    # Smart Inbox v2
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(10), nullable=True)
    suggested_publish_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    suggested_platforms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_deadline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detected_offer: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    grouped_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
    )
    smart_analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # AI Account Manager — client-facing assistant + operator task metadata
    account_manager_intent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    account_manager_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_manager_recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_manager_priority: Mapped[str | None] = mapped_column(String(10), nullable=True)
    account_manager_reply_sent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    account_manager_reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_manager_related_content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True,
    )
    account_manager_processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    client: Mapped["Client"] = relationship(  # noqa: F821
        foreign_keys=[client_id],
    )


class TelegramProcessedUpdate(Base):
    __tablename__ = "telegram_processed_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
