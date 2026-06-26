import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base

ACCOUNT_STATUSES = (
    "connected",
    "disconnected",
    "mock",
    "expired",
    "invalid",
    "missing_permissions",
    "blocked",
)
PLATFORMS = ("telegram", "facebook", "instagram", "tiktok", "linkedin")


class PublishingAccount(Base):
    __tablename__ = "publishing_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    facebook_page_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instagram_business_account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    permissions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="mock", server_default="mock")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
