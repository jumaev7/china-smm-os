import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Boolean, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class PublishAttempt(Base):
    __tablename__ = "publish_attempts"
    __table_args__ = (
        Index("ix_publish_attempts_idempotency_key", "idempotency_key"),
        Index("ix_publish_attempts_retry_claim", "status", "next_retry_at"),
        Index(
            "uq_publish_attempts_active_claim",
            "idempotency_key",
            unique=True,
            postgresql_where=text("status = 'in_progress' AND idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("content_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    # Resilience fields (Alembic 20260921)
    idempotency_key: Mapped[str | None] = mapped_column(String(220), nullable=True)
    publish_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_post_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    account: Mapped["PublishingAccount | None"] = relationship()  # noqa: F821
