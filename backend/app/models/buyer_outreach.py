"""AI Buyer Outreach — draft messages for export sales (no auto-send)."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BuyerOutreachMessage(Base):
    __tablename__ = "buyer_outreach_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposal_documents.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    sales_playbook_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_playbooks.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    sales_playbook_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_playbook_steps.id", ondelete="SET NULL"), nullable=True,
    )
    buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en", server_default="en")
    outreach_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft", index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    communication_thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("communication_threads.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    follow_up_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operator_tasks.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    copied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    client: Mapped["Client"] = relationship(foreign_keys=[client_id])  # noqa: F821
    lead: Mapped["CrmLead | None"] = relationship(foreign_keys=[lead_id])  # noqa: F821
    product: Mapped["Product | None"] = relationship(foreign_keys=[product_id])  # noqa: F821
    proposal: Mapped["ProposalDocument | None"] = relationship(foreign_keys=[proposal_id])  # noqa: F821
    communication_thread: Mapped["CommunicationThread | None"] = relationship(  # noqa: F821
        foreign_keys=[communication_thread_id],
    )
    follow_up_task: Mapped["OperatorTask | None"] = relationship(  # noqa: F821
        foreign_keys=[follow_up_task_id],
    )
    sales_playbook: Mapped["SalesPlaybook | None"] = relationship(  # noqa: F821
        foreign_keys=[sales_playbook_id],
    )
    events: Mapped[list["OutreachEvent"]] = relationship(
        back_populates="outreach",
        cascade="all, delete-orphan",
        order_by="OutreachEvent.created_at.asc()",
    )


class OutreachEvent(Base):
    __tablename__ = "outreach_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    outreach_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buyer_outreach_messages.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    outreach: Mapped["BuyerOutreachMessage"] = relationship(back_populates="events")
