"""Durable intentional publication-request identity — schema/model only (I2a).

Stores client request identity for future idempotent publication-intent
materialization (I2b+). Dormant in I2a: no minting, no PublishService wiring,
no API routes, no provider I/O.

Request-key uniqueness scope (UNIQUE, account_id NULLS NOT DISTINCT):
  (tenant_id, content_id, platform, account_id, operation, client_idempotency_key)

Uniqueness applies to a client request at the selected destination and
operation. It does NOT establish distinctness of external provider destinations;
alias collision protection remains future I2b/I2c destination-resolution work.

Same client_idempotency_key reused under a different documented scope component
(different operation, destination, content, or tenant) is a distinct request
row and is allowed by the database. Same full scope key is rejected.

Fingerprint contract (immutable at accept; encoding only — not a content blob):
  SHA-256 hex digest, length 64, lowercase ASCII hex.
  Future accept-path fields that MUST contribute (I2.0):
    resolved destination (tenant_id, content_id, normalized platform, account_id),
    operation, publish_version (content snapshot id), intent_mode.
  Does NOT store an immutable content snapshot body.

Intent identity: each request row carries one immutable publication_intent_id
(UNIQUE). I2a does not mint intents; callers that later mint must assign a
fresh UUID per new request row unless a separately designed mapping permits
sharing.

Tenant integrity: ordinary FKs match R1 registry pattern (tenants /
content_items / publishing_accounts by id only). PostgreSQL does NOT enforce
that content_id or account_id belong to tenant_id — content_items has no
tenant_id column, and no composite (tenant_id, id) uniqueness exists on
parents for a composite FK. Cross-tenant consistency is service-layer only.
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
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PUBLICATION_REQUEST_OPERATIONS = frozenset({
    "initial_publish",
    "intentional_republish",
})

PUBLICATION_REQUEST_STATUSES = frozenset({
    "accepted",
})

_REQUEST_FINGERPRINT_PREFIX = "pipr_fp_v1"
REQUEST_FINGERPRINT_LENGTH = 64


def build_request_fingerprint(
    *,
    tenant_id: UUID,
    content_id: UUID,
    platform: str,
    account_id: UUID | None,
    operation: str,
    publish_version: str,
    intent_mode: str,
) -> str:
    """Pure SHA-256 hex helper documenting the I2.0 fingerprint field set.

    Not invoked by PublishService, APIs, workers, or any runtime path in I2a.
    """
    account_token = str(account_id) if account_id is not None else "none"
    platform_norm = (platform or "").strip().lower()
    payload = "|".join(
        [
            _REQUEST_FINGERPRINT_PREFIX,
            str(tenant_id),
            str(content_id),
            platform_norm,
            account_token,
            operation,
            publish_version,
            intent_mode,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PublishIntentionalPublicationRequest(Base):
    """One durable client request identity row. No lifecycle side effects."""

    __tablename__ = "publish_intentional_publication_requests"
    __table_args__ = (
        UniqueConstraint(
            "publication_intent_id",
            name="uq_pipr_publication_intent_id",
        ),
        # NULLS NOT DISTINCT: account_id NULL must collide with account_id NULL
        # under the same request-key scope (PG 15+ / 16).
        Index(
            "uq_pipr_request_identity",
            "tenant_id",
            "content_id",
            "platform",
            "account_id",
            "operation",
            "client_idempotency_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_pipr_tenant_content",
            "tenant_id",
            "content_id",
        ),
        Index(
            "ix_pipr_client_idempotency_key",
            "client_idempotency_key",
        ),
        CheckConstraint(
            "operation IN ('initial_publish', 'intentional_republish')",
            name="ck_pipr_operation",
        ),
        CheckConstraint(
            "status IN ('accepted')",
            name="ck_pipr_status",
        ),
        CheckConstraint(
            "char_length(btrim(client_idempotency_key)) > 0",
            name="ck_pipr_client_key_nonempty",
        ),
        CheckConstraint(
            "char_length(request_fingerprint) = 64 "
            "AND request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_pipr_fingerprint_sha256_hex",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
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
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    client_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    publication_intent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False,
    )
    publish_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="accepted",
        server_default="accepted",
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
