"""Social Listening Phase 2 — insight review persistence.

Adds tenant_listening_insight_reviews for analyst review of deterministic
MarketInsight identities. Analytical aggregates remain computed read models.

down_revision = "20260914_social_listening_foundation"
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import (
    create_index_if_missing,
    drop_index_if_exists,
    drop_table_if_exists,
    table_exists,
)

revision = "20260915_listening_market_intelligence"
down_revision = "20260914_social_listening_foundation"
branch_labels = None
depends_on = None


def _ts(name: str, *, default: bool = True, nullable: bool = False) -> sa.Column:
    kwargs = {"nullable": nullable}
    if default:
        kwargs["server_default"] = sa.text("now()")
    return sa.Column(name, sa.DateTime(timezone=True), **kwargs)


def upgrade() -> None:
    if not table_exists("tenants"):
        return

    if not table_exists("tenant_listening_insight_reviews"):
        op.create_table(
            "tenant_listening_insight_reviews",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("insight_key", sa.String(80), nullable=False),
            sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True),
            sa.Column("previous_state", sa.String(40), nullable=False),
            sa.Column("new_state", sa.String(40), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("window_json", JSONB(), nullable=True),
            sa.Column("methodology_version", sa.String(40), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing(
        "ix_tenant_listening_insight_reviews_tenant_id",
        "tenant_listening_insight_reviews",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_listening_insight_reviews_tenant_key_created",
        "tenant_listening_insight_reviews",
        ["tenant_id", "insight_key", "created_at"],
    )


def downgrade() -> None:
    drop_index_if_exists(
        "ix_tenant_listening_insight_reviews_tenant_key_created",
        table_name="tenant_listening_insight_reviews",
    )
    drop_index_if_exists(
        "ix_tenant_listening_insight_reviews_tenant_id",
        table_name="tenant_listening_insight_reviews",
    )
    drop_table_if_exists("tenant_listening_insight_reviews")
