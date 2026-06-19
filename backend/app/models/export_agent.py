"""Export Agent — export opportunities and product insights (advisory only)."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ExportOpportunity(Base):
    __tablename__ = "export_opportunities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    country: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    market_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    demand_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recommended_partner_types_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    recommended_channels_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    client: Mapped["Client"] = relationship(foreign_keys=[client_id])  # noqa: F821
    product: Mapped["Product"] = relationship(foreign_keys=[product_id])  # noqa: F821


class ExportInsight(Base):
    __tablename__ = "export_insights"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    insight_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    product: Mapped["Product"] = relationship(foreign_keys=[product_id])  # noqa: F821
