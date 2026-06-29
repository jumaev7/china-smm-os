"""Tenant-scoped Sales CRM — leads, customers, deals, activities."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

LEAD_STATUSES = frozenset({"new", "contacted", "qualified", "converted", "lost"})
LEAD_PRIORITIES = frozenset({"high", "medium", "low"})
LEAD_SOURCES = frozenset({"manual", "website", "referral", "exhibition", "social", "other"})
PIPELINE_STAGES = frozenset({
    "lead",
    "qualified",
    "contacted",
    "meeting_scheduled",
    "proposal_sent",
    "negotiation",
    "contract_pending",
    "client_active",
    "publishing_active",
    "expansion_upsell",
    "closed_won",
    "closed_lost",
})
# Backward-compatible alias used across services
DEAL_STAGES = PIPELINE_STAGES
LEGACY_STAGE_MAP: dict[str, str] = {
    "new_lead": "lead",
    "contacted": "contacted",
    "negotiation": "negotiation",
    "proposal_sent": "proposal_sent",
    "won": "closed_won",
    "lost": "closed_lost",
}
DEFAULT_STAGE_PROBABILITY: dict[str, int] = {
    "lead": 5,
    "qualified": 15,
    "contacted": 20,
    "meeting_scheduled": 30,
    "proposal_sent": 40,
    "negotiation": 55,
    "contract_pending": 70,
    "client_active": 85,
    "publishing_active": 90,
    "expansion_upsell": 75,
    "closed_won": 100,
    "closed_lost": 0,
}
TERMINAL_STAGES = frozenset({"closed_won", "closed_lost"})
STAGE_SOURCES = frozenset({"manual", "auto", "proposal"})
ACTIVITY_TYPES = frozenset({"call", "email", "meeting", "note", "task", "other"})
PROPOSAL_STATUSES = frozenset({"draft", "sent", "viewed", "accepted", "rejected", "expired"})


class SalesCustomer(Base):
    __tablename__ = "sales_customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram: Mapped[str | None] = mapped_column(String(100), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    wechat: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    primary_publishing_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publishing_accounts.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    deals: Mapped[list["SalesDeal"]] = relationship(back_populates="customer")
    leads: Mapped[list["SalesLead"]] = relationship(back_populates="customer")


class SalesLead(Base):
    __tablename__ = "sales_leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram: Mapped[str | None] = mapped_column(String(100), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    wechat: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="manual", server_default="manual")
    status: Mapped[str] = mapped_column(String(30), default="new", server_default="new", index=True)
    priority: Mapped[str] = mapped_column(String(10), default="medium", server_default="medium")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    customer: Mapped["SalesCustomer | None"] = relationship(back_populates="leads")
    deals: Mapped[list["SalesDeal"]] = relationship(back_populates="lead")


class SalesDeal(Base):
    __tablename__ = "sales_deals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_leads.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD", server_default="USD")
    stage: Mapped[str] = mapped_column(String(30), default="lead", server_default="lead", index=True)
    probability: Mapped[int] = mapped_column(default=5, server_default="5")
    expected_close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    stage_source: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")
    stage_override: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    customer: Mapped["SalesCustomer | None"] = relationship(back_populates="deals", foreign_keys=[customer_id])
    lead: Mapped["SalesLead | None"] = relationship(back_populates="deals", foreign_keys=[lead_id])


class SalesActivity(Base):
    __tablename__ = "sales_activities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_leads.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_deals.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    activity_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


class SalesProposal(Base):
    __tablename__ = "sales_proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    proposal_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_leads.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_deals.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    issue_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD", server_default="USD")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    discount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attachment_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_history: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    customer: Mapped["SalesCustomer | None"] = relationship(foreign_keys=[customer_id])
    lead: Mapped["SalesLead | None"] = relationship(foreign_keys=[lead_id])
    deal: Mapped["SalesDeal | None"] = relationship(foreign_keys=[deal_id])
    items: Mapped[list["SalesProposalItem"]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan", order_by="SalesProposalItem.sort_order",
    )


class SalesProposalItem(Base):
    __tablename__ = "sales_proposal_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_proposals.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    product_or_service_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("1"), server_default="1")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    discount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    proposal: Mapped["SalesProposal"] = relationship(back_populates="items")
