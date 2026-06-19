"""Factory tenant onboarding — progress tracking and analytics per tenant."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ONBOARDING_STATUSES = frozenset({"not_started", "in_progress", "completed"})


class TenantOnboardingProgress(Base):
    __tablename__ = "tenant_onboarding_progress"

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
    progress_percent: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False,
    )
    steps_completed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    milestone_messages: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    company_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    demo_data_generated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    demo_data_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    manually_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    manually_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_content_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_lead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_buyer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_deal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_proposal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    growth_center_viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
