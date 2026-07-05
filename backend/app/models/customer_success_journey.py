"""Customer Success Journey — post-onboarding 30-day adoption engine (separate from onboarding)."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JOURNEY_STATUSES = frozenset({"not_started", "active", "completed"})


class TenantCustomerSuccessJourney(Base):
    __tablename__ = "tenant_customer_success_journey"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="not_started", server_default="not_started", nullable=False, index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_checkpoint: Mapped[str | None] = mapped_column(String(20), nullable=True)
    milestones_achieved: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timeline_entries: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    weekly_wins: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dismissed_recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
