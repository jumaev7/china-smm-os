"""Export Buyer Discovery Engine v1 — registry of potential export buyers (intelligence only)."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BuyerDiscoveryEntry(Base):
    __tablename__ = "buyer_discovery_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    crm_lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contact_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown", server_default="unknown")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="crm_sync", server_default="crm_sync")
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    opportunity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="new", server_default="new", index=True)
    pipeline_stage: Mapped[str] = mapped_column(
        String(30), nullable=False, default="discovered", server_default="discovered", index=True,
    )
    score_factors_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recalculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
