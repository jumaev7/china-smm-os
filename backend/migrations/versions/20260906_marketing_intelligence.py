"""Marketing Intelligence Platform — signals, scores, recommendations, history."""
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

revision = "20260906_marketing_intelligence"
down_revision = "20260905_workflow_definitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("tenants"):
        return

    if not table_exists("tenant_marketing_signals"):
        op.create_table(
            "tenant_marketing_signals",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("signal_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("signal_type", sa.String(80), nullable=False),
            sa.Column("entity_type", sa.String(80), nullable=True),
            sa.Column("entity_id", sa.String(120), nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column("source", sa.String(40), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="1.000"),
            sa.Column("platform_event_id", UUID(as_uuid=True), nullable=True),
            sa.Column("platform_event_type", sa.String(120), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "signal_id",
                name="uq_tenant_marketing_signals_tenant_signal",
            ),
        )

    create_index_if_missing(
        "ix_tenant_marketing_signals_tenant_id",
        "tenant_marketing_signals",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_signals_tenant_occurred",
        "tenant_marketing_signals",
        ["tenant_id", "occurred_at"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_signals_tenant_type_occurred",
        "tenant_marketing_signals",
        ["tenant_id", "signal_type", "occurred_at"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_signals_tenant_source",
        "tenant_marketing_signals",
        ["tenant_id", "source"],
    )

    if not table_exists("tenant_marketing_scores"):
        op.create_table(
            "tenant_marketing_scores",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False, server_default="50"),
            sa.Column("weight", sa.Numeric(5, 4), nullable=False, server_default="0.1000"),
            sa.Column("scoring_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("explanation", JSONB(), nullable=True),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column(
                "computed_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "category",
                name="uq_tenant_marketing_scores_tenant_category",
            ),
        )

    create_index_if_missing(
        "ix_tenant_marketing_scores_tenant_id",
        "tenant_marketing_scores",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_scores_tenant_updated",
        "tenant_marketing_scores",
        ["tenant_id", "updated_at"],
    )

    if not table_exists("tenant_marketing_score_history"):
        op.create_table(
            "tenant_marketing_score_history",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("weight", sa.Numeric(5, 4), nullable=False),
            sa.Column("scoring_version", sa.String(20), nullable=False),
            sa.Column("explanation", JSONB(), nullable=True),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    create_index_if_missing(
        "ix_tenant_marketing_score_history_tenant_id",
        "tenant_marketing_score_history",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_score_history_tenant_category_at",
        "tenant_marketing_score_history",
        ["tenant_id", "category", "recorded_at"],
    )

    if not table_exists("tenant_marketing_recommendations"):
        op.create_table(
            "tenant_marketing_recommendations",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("recommendation_key", sa.String(120), nullable=False),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("explanation", JSONB(), nullable=True),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="0.800"),
            sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("rule_id", sa.String(80), nullable=False),
            sa.Column("rule_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("action_url", sa.String(255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "recommendation_key",
                name="uq_tenant_marketing_recommendations_tenant_key",
            ),
        )

    create_index_if_missing(
        "ix_tenant_marketing_recommendations_tenant_id",
        "tenant_marketing_recommendations",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_recommendations_tenant_priority",
        "tenant_marketing_recommendations",
        ["tenant_id", "priority", "updated_at"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_recommendations_tenant_status",
        "tenant_marketing_recommendations",
        ["tenant_id", "status"],
    )

    if not table_exists("tenant_marketing_recommendation_history"):
        op.create_table(
            "tenant_marketing_recommendation_history",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("recommendation_key", sa.String(120), nullable=False),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("explanation", JSONB(), nullable=True),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
            sa.Column("priority", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("rule_id", sa.String(80), nullable=False),
            sa.Column("rule_version", sa.String(20), nullable=False),
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    create_index_if_missing(
        "ix_tenant_marketing_recommendation_history_tenant_id",
        "tenant_marketing_recommendation_history",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_rec_history_tenant_recorded",
        "tenant_marketing_recommendation_history",
        ["tenant_id", "recorded_at"],
    )

    if not table_exists("tenant_marketing_insights"):
        op.create_table(
            "tenant_marketing_insights",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("category", sa.String(40), nullable=True),
            sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
            sa.Column("explanation", JSONB(), nullable=True),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("related_signal_ids", JSONB(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    create_index_if_missing(
        "ix_tenant_marketing_insights_tenant_id",
        "tenant_marketing_insights",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_insights_tenant_created",
        "tenant_marketing_insights",
        ["tenant_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_insights_tenant_kind",
        "tenant_marketing_insights",
        ["tenant_id", "kind"],
    )

    if not table_exists("tenant_marketing_trends"):
        op.create_table(
            "tenant_marketing_trends",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("metric_key", sa.String(80), nullable=False),
            sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("bucket_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("value", sa.Numeric(12, 4), nullable=False),
            sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "metric_key",
                "bucket_start",
                name="uq_tenant_marketing_trends_tenant_metric_bucket",
            ),
        )

    create_index_if_missing(
        "ix_tenant_marketing_trends_tenant_id",
        "tenant_marketing_trends",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_marketing_trends_tenant_metric_bucket",
        "tenant_marketing_trends",
        ["tenant_id", "metric_key", "bucket_start"],
    )


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_tenant_marketing_trends_tenant_metric_bucket", "tenant_marketing_trends"),
        ("ix_tenant_marketing_trends_tenant_id", "tenant_marketing_trends"),
        ("ix_tenant_marketing_insights_tenant_kind", "tenant_marketing_insights"),
        ("ix_tenant_marketing_insights_tenant_created", "tenant_marketing_insights"),
        ("ix_tenant_marketing_insights_tenant_id", "tenant_marketing_insights"),
        ("ix_tenant_marketing_rec_history_tenant_recorded", "tenant_marketing_recommendation_history"),
        ("ix_tenant_marketing_recommendation_history_tenant_id", "tenant_marketing_recommendation_history"),
        ("ix_tenant_marketing_recommendations_tenant_status", "tenant_marketing_recommendations"),
        ("ix_tenant_marketing_recommendations_tenant_priority", "tenant_marketing_recommendations"),
        ("ix_tenant_marketing_recommendations_tenant_id", "tenant_marketing_recommendations"),
        ("ix_tenant_marketing_score_history_tenant_category_at", "tenant_marketing_score_history"),
        ("ix_tenant_marketing_score_history_tenant_id", "tenant_marketing_score_history"),
        ("ix_tenant_marketing_scores_tenant_updated", "tenant_marketing_scores"),
        ("ix_tenant_marketing_scores_tenant_id", "tenant_marketing_scores"),
        ("ix_tenant_marketing_signals_tenant_source", "tenant_marketing_signals"),
        ("ix_tenant_marketing_signals_tenant_type_occurred", "tenant_marketing_signals"),
        ("ix_tenant_marketing_signals_tenant_occurred", "tenant_marketing_signals"),
        ("ix_tenant_marketing_signals_tenant_id", "tenant_marketing_signals"),
    ):
        drop_index_if_exists(index_name, table_name)

    for table in (
        "tenant_marketing_trends",
        "tenant_marketing_insights",
        "tenant_marketing_recommendation_history",
        "tenant_marketing_recommendations",
        "tenant_marketing_score_history",
        "tenant_marketing_scores",
        "tenant_marketing_signals",
    ):
        drop_table_if_exists(table)
