"""WhatsApp Sync v1 — account registry and sync jobs (integration-ready, no auto-send)."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

WHATSAPP_ACCOUNT_TYPES = (
    "whatsapp_business_api",
    "whatsapp_cloud_api",
    "third_party_connector",
    "manual_import",
)
WHATSAPP_ACCOUNT_STATUSES = ("not_connected", "connected", "sync_error", "disabled")
WHATSAPP_SYNC_JOB_STATUSES = ("pending", "running", "completed", "failed")
WHATSAPP_SYNC_JOB_TYPES = (
    "contacts",
    "conversations",
    "test_connection",
    "scheduled_contacts",
    "scheduled_conversations",
)
WHATSAPP_SYNC_TRIGGERS = ("manual", "scheduled")


class WhatsAppSyncAccount(Base):
    __tablename__ = "whatsapp_sync_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="not_connected", server_default="not_connected", index=True,
    )
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    business_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_account_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class WhatsAppSyncJob(Base):
    __tablename__ = "whatsapp_sync_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_sync_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", index=True)
    stats_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
