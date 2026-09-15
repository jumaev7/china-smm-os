"""Publish Write Coordination Registry — schema/model only (R1).

Durable coordination row for one LogicalWriteIdentity:
  DestinationIdentity + publication_intent_id

Dormant: no acquire/transition/service wiring. State-machine enforcement is R2.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Persisted registry states only. AVAILABLE is not stored — "no row" is acquireable.
PUBLISH_WRITE_COORDINATION_STATES = frozenset({
    "RESERVED",
    "WRITE_STARTED",
    "SUCCEEDED",
    "FAILED_SAFE",
    "AMBIGUOUS",
    "RESOLVED_SUCCEEDED",
    "RESOLVED_FAILED",
    "SUPERSEDED",
})

_LOGICAL_WRITE_KEY_PREFIX = "pwr_v1"


def build_logical_write_key(
    tenant_id: UUID,
    content_id: UUID,
    platform: str,
    account_id: UUID | None,
    publication_intent_id: UUID,
) -> str:
    """Pure deterministic key helper for tests / future service use.

    Not invoked by PublishService, retry executor, or any runtime path in R1.
    """
    account_token = str(account_id) if account_id is not None else "none"
    platform_norm = (platform or "").strip().lower()
    payload = "|".join(
        [
            _LOGICAL_WRITE_KEY_PREFIX,
            str(tenant_id),
            str(content_id),
            platform_norm,
            account_token,
            str(publication_intent_id),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PublishWriteCoordinationRegistry(Base):
    """One registry row per LogicalWriteIdentity. No lifecycle side effects."""

    __tablename__ = "publish_write_coordination_registry"
    __table_args__ = (
        UniqueConstraint(
            "logical_write_key",
            name="uq_publish_write_coordination_registry_logical_write_key",
        ),
        # NULLS NOT DISTINCT: account_id NULL must not allow duplicate
        # account-less destinations for the same intent (PG 15+).
        Index(
            "uq_publish_write_coordination_registry_destination_intent",
            "tenant_id",
            "content_id",
            "platform",
            "account_id",
            "publication_intent_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_publish_write_coordination_registry_tenant_state",
            "tenant_id",
            "state",
        ),
        Index(
            "ix_publish_write_coordination_registry_content_platform",
            "content_id",
            "platform",
        ),
        Index(
            "ix_publish_write_coordination_registry_state_lease_expires",
            "state",
            "lease_expires_at",
        ),
        Index(
            "ix_publish_write_coordination_registry_publication_intent_id",
            "publication_intent_id",
        ),
        Index(
            "ix_publish_write_coordination_registry_current_attempt_id",
            "current_attempt_id",
        ),
        Index(
            "ix_publish_write_coordination_registry_current_command_id",
            "current_command_id",
        ),
        CheckConstraint(
            "state IN ("
            "'RESERVED', 'WRITE_STARTED', 'SUCCEEDED', 'FAILED_SAFE', "
            "'AMBIGUOUS', 'RESOLVED_SUCCEEDED', 'RESOLVED_FAILED', 'SUPERSEDED'"
            ")",
            name="ck_publish_write_coordination_registry_state",
        ),
        CheckConstraint(
            "generation >= 0",
            name="ck_publish_write_coordination_registry_generation_nonneg",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_publish_write_coordination_registry_version_nonneg",
        ),
        # Invariant only: WRITE_STARTED must carry the barrier timestamp.
        # Full state machine remains service-enforced in R2.
        CheckConstraint(
            "state <> 'WRITE_STARTED' OR provider_write_started_at IS NOT NULL",
            name="ck_publish_write_coordination_registry_write_started_ts",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    logical_write_key: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("content_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("publishing_accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    publication_intent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False,
    )
    root_intent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    owner_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    provider_write_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # Soft references: avoid attempt/command lifecycle coupling that could
    # erase or block coordination history (no FK).
    current_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True,
    )
    current_command_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True,
    )
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "publish_write_coordination_registry.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
