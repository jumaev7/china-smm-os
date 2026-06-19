"""Marketing campaigns — organizational grouping for content items."""
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

CAMPAIGN_STATUSES = frozenset({"draft", "active", "completed", "archived"})

CAMPAIGN_OBJECTIVES = (
    "Brand Awareness",
    "Product Launch",
    "Trade Show",
    "Lead Generation",
    "Distributor Recruitment",
)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    objective: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", nullable=False, index=True,
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    client: Mapped["Client"] = relationship(foreign_keys=[client_id])  # noqa: F821
    content_items: Mapped[list["ContentItem"]] = relationship(  # noqa: F821
        back_populates="campaign",
        foreign_keys="ContentItem.campaign_id",
    )
    media_assets: Mapped[list["MediaAsset"]] = relationship(  # noqa: F821
        back_populates="campaign",
        foreign_keys="MediaAsset.campaign_id",
    )
