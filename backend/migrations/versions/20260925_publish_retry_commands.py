"""Add publish_retry_commands durable retry-intent table (Phase 3C.1B).

Revision ID: 20260925_publish_retry_commands
Revises: 20260818_add_caption_zh_fields

Additive only: new table + optional nullable FK on publish_attempts.
No data rewrite. Creating a command must not publish.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.helpers import (
    add_column_if_missing,
    create_foreign_key_if_missing,
    create_index_if_missing,
    create_table_if_missing,
    drop_column_if_exists,
    drop_index_if_exists,
    drop_table_if_exists,
    index_exists,
    table_exists,
)

revision = "20260925_publish_retry_commands"
down_revision = "20260818_add_caption_zh_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "publish_retry_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "original_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("publish_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resulting_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("publish_attempts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column(
            "publishing_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("publish_version", sa.String(length=64), nullable=False),
        sa.Column("destination_key", sa.String(length=120), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_source", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=420), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("provider_outcome", sa.String(length=40), nullable=True),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_write_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint(
            "status IN ("
            "'pending', 'claimed', 'provider_write_started', "
            "'succeeded', 'failed', 'ambiguous', "
            "'blocked', 'superseded', 'cancelled'"
            ")",
            name="ck_publish_retry_commands_status",
        ),
    )

    if table_exists("publish_retry_commands"):
        create_index_if_missing(
            "ix_publish_retry_commands_tenant_id",
            "publish_retry_commands",
            ["tenant_id"],
        )
        create_index_if_missing(
            "ix_publish_retry_commands_client_id",
            "publish_retry_commands",
            ["client_id"],
        )
        create_index_if_missing(
            "ix_publish_retry_commands_content_id",
            "publish_retry_commands",
            ["content_id"],
        )
        create_index_if_missing(
            "ix_publish_retry_commands_status",
            "publish_retry_commands",
            ["status"],
        )
        create_index_if_missing(
            "ix_publish_retry_commands_tenant_status",
            "publish_retry_commands",
            ["tenant_id", "status"],
        )
        create_index_if_missing(
            "ix_publish_retry_commands_tenant_content",
            "publish_retry_commands",
            ["tenant_id", "content_id"],
        )
        create_index_if_missing(
            "ix_publish_retry_commands_original_attempt",
            "publish_retry_commands",
            ["original_attempt_id"],
        )
        create_index_if_missing(
            "ix_publish_retry_commands_correlation",
            "publish_retry_commands",
            ["correlation_id"],
        )
        if not index_exists(
            "publish_retry_commands",
            "uq_publish_retry_commands_active_idempotency",
        ):
            op.create_index(
                "uq_publish_retry_commands_active_idempotency",
                "publish_retry_commands",
                ["idempotency_key"],
                unique=True,
                postgresql_where=sa.text(
                    "status IN ('pending', 'claimed', 'provider_write_started')"
                ),
            )

    # Optional lineage pointer on attempts — additive nullable only.
    if table_exists("publish_attempts"):
        add_column_if_missing(
            "publish_attempts",
            sa.Column(
                "retry_command_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        create_foreign_key_if_missing(
            "fk_publish_attempts_retry_command_id",
            "publish_attempts",
            "publish_retry_commands",
            ["retry_command_id"],
            ["id"],
            ondelete="SET NULL",
        )
        create_index_if_missing(
            "ix_publish_attempts_retry_command_id",
            "publish_attempts",
            ["retry_command_id"],
        )


def downgrade() -> None:
    drop_index_if_exists("ix_publish_attempts_retry_command_id", "publish_attempts")
    # Drop FK by name if present, then column.
    bind = op.get_bind()
    fk = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = :name AND constraint_type = 'FOREIGN KEY'"
        ),
        {"name": "fk_publish_attempts_retry_command_id"},
    ).first()
    if fk is not None and table_exists("publish_attempts"):
        op.drop_constraint(
            "fk_publish_attempts_retry_command_id",
            "publish_attempts",
            type_="foreignkey",
        )
    drop_column_if_exists("publish_attempts", "retry_command_id")

    drop_index_if_exists(
        "uq_publish_retry_commands_active_idempotency",
        "publish_retry_commands",
    )
    drop_index_if_exists(
        "ix_publish_retry_commands_correlation",
        "publish_retry_commands",
    )
    drop_index_if_exists(
        "ix_publish_retry_commands_original_attempt",
        "publish_retry_commands",
    )
    drop_index_if_exists(
        "ix_publish_retry_commands_tenant_content",
        "publish_retry_commands",
    )
    drop_index_if_exists(
        "ix_publish_retry_commands_tenant_status",
        "publish_retry_commands",
    )
    drop_index_if_exists(
        "ix_publish_retry_commands_status",
        "publish_retry_commands",
    )
    drop_index_if_exists(
        "ix_publish_retry_commands_content_id",
        "publish_retry_commands",
    )
    drop_index_if_exists(
        "ix_publish_retry_commands_client_id",
        "publish_retry_commands",
    )
    drop_index_if_exists(
        "ix_publish_retry_commands_tenant_id",
        "publish_retry_commands",
    )
    drop_table_if_exists("publish_retry_commands")
