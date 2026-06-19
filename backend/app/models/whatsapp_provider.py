"""WhatsApp Provider v1 — provider registry, configuration, webhook framework (no message sending)."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

WHATSAPP_PROVIDER_TYPES = (
    "meta_cloud_api",
    "whatsapp_business_api",
    "third_party_connector",
    "custom_provider",
)
WHATSAPP_PROVIDER_STATUSES = ("pending", "active", "inactive", "error")
WHATSAPP_PROVIDER_CONFIG_STATUSES = ("draft", "configured", "validated", "error")
WHATSAPP_PROVIDER_WEBHOOK_EVENTS = (
    "inbound_message",
    "contact_update",
    "conversation_update",
    "delivery_status_update",
    "template_status_update",
)
WHATSAPP_PROVIDER_WEBHOOK_STATUSES = ("architecture_only", "pending", "processed", "failed")


class WhatsAppProvider(Base):
    __tablename__ = "whatsapp_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    provider_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False, index=True,
    )
    capabilities_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class WhatsAppProviderConfiguration(Base):
    __tablename__ = "whatsapp_provider_configurations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    config_status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", nullable=False, index=True,
    )
    phone_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    business_account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False, index=True,
    )
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_connection_test: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class WhatsAppProviderWebhookEvent(Base):
    """Webhook framework placeholder — architecture only, no live processing in v1."""

    __tablename__ = "whatsapp_provider_webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_providers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30),
        default="architecture_only",
        server_default="architecture_only",
        nullable=False,
        index=True,
    )
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
