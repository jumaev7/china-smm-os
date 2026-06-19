"""CRM deals — central workspace for sales opportunities."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CrmDeal(Base):
    __tablename__ = "crm_deals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_leads.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="new", server_default="new", index=True)
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    probability: Mapped[int] = mapped_column(default=10, server_default="10")
    expected_close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deal_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="UZS", server_default="UZS")
    commission_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    commission_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    commission_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    partner_commission_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    partner_commission_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    lead: Mapped["CrmLead"] = relationship(foreign_keys=[lead_id])  # noqa: F821
    client: Mapped["Client"] = relationship(foreign_keys=[client_id])  # noqa: F821
    events: Mapped[list["CrmDealEvent"]] = relationship(
        back_populates="deal",
        cascade="all, delete-orphan",
        order_by="CrmDealEvent.created_at.desc()",
    )


class CrmDealEvent(Base):
    __tablename__ = "crm_deal_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_deals.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    deal: Mapped["CrmDeal"] = relationship(back_populates="events")
