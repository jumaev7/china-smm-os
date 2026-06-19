"""Operator user settings — UI language and future content language prefs."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DEFAULT_OPERATOR_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
SUPPORTED_UI_LANGUAGES = frozenset({"ru", "en", "zh"})


class OperatorUser(Base):
    __tablename__ = "operator_users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    preferred_language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="ru", server_default="ru",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
