"""Executive CRM pipeline timeline events — tenant-scoped audit trail."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PIPELINE_EVENT_TYPES = frozenset({
    "deal_created",
    "lead_created",
    "status_changed",
    "stage_changed",
    "proposal_sent",
    "proposal_accepted",
    "proposal_rejected",
    "meeting_added",
    "publishing_connected",
    "campaign_launched",
    "client_message",
    "manual_note",
    "ai_recommendation",
    "owner_changed",
    "client_linked",
})


class CrmPipelineEvent(Base):
    __tablename__ = "crm_pipeline_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_leads.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_deals.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
