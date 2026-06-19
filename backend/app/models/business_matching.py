"""Business Matching Center — tenant-scoped B2B matching opportunities."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

OPPORTUNITY_STATUSES = frozenset({
    "new", "contacted", "qualified", "negotiation", "won", "lost",
})
OPPORTUNITY_TYPES = frozenset({
    "import", "distribution", "government", "retail", "general",
})


class BusinessMatchingOpportunity(Base):
    __tablename__ = "business_matching_opportunities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    buyer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buyers.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    supplier_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    confidence_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="new", server_default="new", index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_factors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    match_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
