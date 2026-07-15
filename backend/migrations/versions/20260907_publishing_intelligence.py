"""Publishing Intelligence — deterministic pre-publish reviews and scores."""
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

revision = "20260907_publishing_intelligence"
down_revision = "20260906_marketing_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("tenants") or not table_exists("content_items"):
        return

    if not table_exists("tenant_publishing_reviews"):
        op.create_table(
            "tenant_publishing_reviews",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "content_id",
                UUID(as_uuid=True),
                sa.ForeignKey("content_items.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("review_version", sa.Integer(), nullable=False),
            sa.Column(
                "review_engine_version",
                sa.String(20),
                nullable=False,
                server_default="1.0.0",
            ),
            sa.Column("content_fingerprint", sa.String(64), nullable=False),
            sa.Column("overall_score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
            sa.Column("primary_language", sa.String(10), nullable=True),
            sa.Column("target_platforms", JSONB(), nullable=True),
            sa.Column("summary", JSONB(), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "content_id",
                "review_version",
                name="uq_tenant_publishing_reviews_content_version",
            ),
        )

    create_index_if_missing(
        "ix_tenant_publishing_reviews_tenant_id",
        "tenant_publishing_reviews",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_publishing_reviews_content_id",
        "tenant_publishing_reviews",
        ["content_id"],
    )
    create_index_if_missing(
        "ix_tenant_publishing_reviews_tenant_content_created",
        "tenant_publishing_reviews",
        ["tenant_id", "content_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_publishing_reviews_tenant_status_created",
        "tenant_publishing_reviews",
        ["tenant_id", "status", "created_at"],
    )

    if not table_exists("tenant_publishing_review_checks"):
        op.create_table(
            "tenant_publishing_review_checks",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "publishing_review_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_publishing_reviews.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("check_key", sa.String(80), nullable=False),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("recommendation_key", sa.String(80), nullable=True),
            sa.Column("recommendation_params", JSONB(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    create_index_if_missing(
        "ix_tenant_publishing_review_checks_tenant_id",
        "tenant_publishing_review_checks",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_publishing_review_checks_publishing_review_id",
        "tenant_publishing_review_checks",
        ["publishing_review_id"],
    )
    create_index_if_missing(
        "ix_tenant_publishing_review_checks_review_category",
        "tenant_publishing_review_checks",
        ["publishing_review_id", "category"],
    )
    create_index_if_missing(
        "ix_tenant_publishing_review_checks_tenant_review",
        "tenant_publishing_review_checks",
        ["tenant_id", "publishing_review_id"],
    )

    if not table_exists("tenant_publishing_platform_reviews"):
        op.create_table(
            "tenant_publishing_platform_reviews",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "publishing_review_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_publishing_reviews.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("platform", sa.String(40), nullable=False),
            sa.Column("platform_score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("caption_score", sa.Integer(), nullable=True),
            sa.Column("media_score", sa.Integer(), nullable=True),
            sa.Column("cta_score", sa.Integer(), nullable=True),
            sa.Column("hashtag_score", sa.Integer(), nullable=True),
            sa.Column("language_score", sa.Integer(), nullable=True),
            sa.Column("compliance_score", sa.Integer(), nullable=True),
            sa.Column("recommendations", JSONB(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "publishing_review_id",
                "platform",
                name="uq_tenant_publishing_platform_reviews_review_platform",
            ),
        )

    create_index_if_missing(
        "ix_tenant_publishing_platform_reviews_tenant_id",
        "tenant_publishing_platform_reviews",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_publishing_platform_reviews_publishing_review_id",
        "tenant_publishing_platform_reviews",
        ["publishing_review_id"],
    )
    create_index_if_missing(
        "ix_tenant_publishing_platform_reviews_tenant_review",
        "tenant_publishing_platform_reviews",
        ["tenant_id", "publishing_review_id"],
    )


def downgrade() -> None:
    drop_index_if_exists(
        "ix_tenant_publishing_platform_reviews_tenant_review",
        "tenant_publishing_platform_reviews",
    )
    drop_index_if_exists(
        "ix_tenant_publishing_platform_reviews_publishing_review_id",
        "tenant_publishing_platform_reviews",
    )
    drop_index_if_exists(
        "ix_tenant_publishing_platform_reviews_tenant_id",
        "tenant_publishing_platform_reviews",
    )
    drop_table_if_exists("tenant_publishing_platform_reviews")

    drop_index_if_exists(
        "ix_tenant_publishing_review_checks_tenant_review",
        "tenant_publishing_review_checks",
    )
    drop_index_if_exists(
        "ix_tenant_publishing_review_checks_review_category",
        "tenant_publishing_review_checks",
    )
    drop_index_if_exists(
        "ix_tenant_publishing_review_checks_publishing_review_id",
        "tenant_publishing_review_checks",
    )
    drop_index_if_exists(
        "ix_tenant_publishing_review_checks_tenant_id",
        "tenant_publishing_review_checks",
    )
    drop_table_if_exists("tenant_publishing_review_checks")

    drop_index_if_exists(
        "ix_tenant_publishing_reviews_tenant_status_created",
        "tenant_publishing_reviews",
    )
    drop_index_if_exists(
        "ix_tenant_publishing_reviews_tenant_content_created",
        "tenant_publishing_reviews",
    )
    drop_index_if_exists(
        "ix_tenant_publishing_reviews_content_id",
        "tenant_publishing_reviews",
    )
    drop_index_if_exists(
        "ix_tenant_publishing_reviews_tenant_id",
        "tenant_publishing_reviews",
    )
    drop_table_if_exists("tenant_publishing_reviews")
