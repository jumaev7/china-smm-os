"""Subscription & Billing v1 — plans, subscriptions, invoices (architecture only)."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

SUBSCRIPTION_STATUSES = frozenset({"trial", "active", "suspended", "expired", "cancelled"})
BILLING_CYCLES = frozenset({"monthly", "yearly"})
INVOICE_STATUSES = frozenset({"draft", "unpaid", "paid", "cancelled"})


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    monthly_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    yearly_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    max_users: Mapped[int | None] = mapped_column(nullable=True)
    max_leads: Mapped[int | None] = mapped_column(nullable=True)
    max_buyers: Mapped[int | None] = mapped_column(nullable=True)
    max_deals: Mapped[int | None] = mapped_column(nullable=True)
    features: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="trial", server_default="trial", nullable=False, index=True,
    )
    billing_cycle: Mapped[str] = mapped_column(
        String(20), default="monthly", server_default="monthly", nullable=False,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    plan: Mapped["Plan"] = relationship("Plan", lazy="joined")
    invoices: Mapped[list["Invoice"]] = relationship("Invoice", back_populates="subscription")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", server_default="USD", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", nullable=False, index=True,
    )
    invoice_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    subscription: Mapped["Subscription"] = relationship("Subscription", back_populates="invoices")
