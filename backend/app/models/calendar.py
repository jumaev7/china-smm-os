import uuid
from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, ForeignKey, func, Text, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class CalendarEntry(Base):
    __tablename__ = "calendar_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    content_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("content_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    time_slot: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "09:00"
    platforms: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    content_item: Mapped["ContentItem"] = relationship(back_populates="calendar_entry")  # noqa: F821
