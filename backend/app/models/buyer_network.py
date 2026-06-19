"""Export Buyer Network v1 — global buyer intelligence profiles and tenant relationships."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BuyerNetworkProfile(Base):
    __tablename__ = "buyer_network_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    classification: Mapped[str] = mapped_column(
        String(30), nullable=False, default="watchlist", server_default="watchlist", index=True,
    )
    opportunity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    network_strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    buyer_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="watchlist", server_default="watchlist", index=True,
    )
    score_factors_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    recalculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class BuyerRelationship(Base):
    __tablename__ = "buyer_relationships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("buyer_network_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    relationship_strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
