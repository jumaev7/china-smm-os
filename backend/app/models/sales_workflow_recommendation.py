"""Sales Workflow Automation — recommendation-only workflow engine."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SalesWorkflowRecommendation(Base):
    __tablename__ = "sales_workflow_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposal_documents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    conversation_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    workflow_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    detection_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(10), default="medium", server_default="medium", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open", index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    linked_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operator_tasks.id", ondelete="SET NULL"), nullable=True,
    )
    entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    client: Mapped["Client | None"] = relationship(foreign_keys=[client_id])  # noqa: F821
    lead: Mapped["CrmLead | None"] = relationship(foreign_keys=[lead_id])  # noqa: F821
    deal: Mapped["CrmDeal | None"] = relationship(foreign_keys=[deal_id])  # noqa: F821
