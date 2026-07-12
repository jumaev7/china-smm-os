"""Notification Center — extend tenant_event_notifications for tenant API."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from migrations.helpers import add_column_if_missing, create_index_if_missing

revision = "20260901_notification_center"
down_revision = "20260831_platform_event_bus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "tenant_event_notifications",
        sa.Column("category", sa.String(40), nullable=False, server_default="platform"),
    )
    add_column_if_missing(
        "tenant_event_notifications",
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    add_column_if_missing(
        "tenant_event_notifications",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "tenant_event_notifications",
        sa.Column("action_url", sa.String(500), nullable=True),
    )
    add_column_if_missing(
        "tenant_event_notifications",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "tenant_event_notifications",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )

    op.execute(
        sa.text(
            "UPDATE tenant_event_notifications "
            "SET is_read = true, read_at = COALESCE(read_at, created_at) "
            "WHERE status = 'read' AND is_read = false",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE tenant_event_notifications "
            "SET deleted_at = COALESCE(deleted_at, created_at) "
            "WHERE status = 'dismissed' AND deleted_at IS NULL",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE tenant_event_notifications "
            "SET category = 'platform' "
            "WHERE category IS NULL OR category = ''",
        ),
    )

    create_index_if_missing(
        "ix_tenant_event_notifications_tenant_created",
        "tenant_event_notifications",
        ["tenant_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_event_notifications_tenant_is_read",
        "tenant_event_notifications",
        ["tenant_id", "is_read"],
    )
    create_index_if_missing(
        "ix_tenant_event_notifications_tenant_category",
        "tenant_event_notifications",
        ["tenant_id", "category"],
    )
    create_index_if_missing(
        "ix_tenant_event_notifications_tenant_severity",
        "tenant_event_notifications",
        ["tenant_id", "severity"],
    )
    create_index_if_missing(
        "ix_tenant_event_notifications_tenant_deleted_at",
        "tenant_event_notifications",
        ["tenant_id", "deleted_at"],
    )
    create_index_if_missing(
        "ix_tenant_event_notifications_event_id",
        "tenant_event_notifications",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_event_notifications_event_id",
        table_name="tenant_event_notifications",
    )
    op.drop_index(
        "ix_tenant_event_notifications_tenant_deleted_at",
        table_name="tenant_event_notifications",
    )
    op.drop_index(
        "ix_tenant_event_notifications_tenant_severity",
        table_name="tenant_event_notifications",
    )
    op.drop_index(
        "ix_tenant_event_notifications_tenant_category",
        table_name="tenant_event_notifications",
    )
    op.drop_index(
        "ix_tenant_event_notifications_tenant_is_read",
        table_name="tenant_event_notifications",
    )
    op.drop_index(
        "ix_tenant_event_notifications_tenant_created",
        table_name="tenant_event_notifications",
    )
    op.drop_column("tenant_event_notifications", "updated_at")
    op.drop_column("tenant_event_notifications", "deleted_at")
    op.drop_column("tenant_event_notifications", "action_url")
    op.drop_column("tenant_event_notifications", "read_at")
    op.drop_column("tenant_event_notifications", "is_read")
    op.drop_column("tenant_event_notifications", "category")
