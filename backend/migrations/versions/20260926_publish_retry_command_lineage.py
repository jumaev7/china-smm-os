"""Enforce publish retry command ↔ attempt 1:1 lineage invariants (Phase 3C.1C-A).

Revision ID: 20260926_publish_retry_command_lineage
Revises: 20260925_publish_retry_commands

Additive DB invariants only:
- unique non-null publish_attempts.retry_command_id
- unique non-null publish_retry_commands.resulting_attempt_id
- worker claim lookup index (status, created_at)
- CHECK: provider_write_started requires provider_write_started_at

No data rewrite. No worker / executor / PublishService changes.
"""
from alembic import op
import sqlalchemy as sa

from migrations.helpers import (
    create_index_if_missing,
    drop_index_if_exists,
    index_exists,
    table_exists,
)

revision = "20260926_publish_retry_command_lineage"
down_revision = "20260925_publish_retry_commands"
branch_labels = None
depends_on = None


def _check_constraint_exists(constraint_name: str, table_name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = :name "
            "AND table_name = :table "
            "AND constraint_type = 'CHECK'"
        ),
        {"name": constraint_name, "table": table_name},
    )
    return result.first() is not None


def upgrade() -> None:
    # --- Attempt side: one command → at most one PublishAttempt ---
    # Replace non-unique lookup index with unique partial (same column, stronger).
    if table_exists("publish_attempts"):
        drop_index_if_exists(
            "ix_publish_attempts_retry_command_id",
            "publish_attempts",
        )
        if not index_exists(
            "publish_attempts",
            "uq_publish_attempts_retry_command_id",
        ):
            op.create_index(
                "uq_publish_attempts_retry_command_id",
                "publish_attempts",
                ["retry_command_id"],
                unique=True,
                postgresql_where=sa.text("retry_command_id IS NOT NULL"),
            )

    if table_exists("publish_retry_commands"):
        # --- Command side: one resulting attempt → at most one command ---
        if not index_exists(
            "publish_retry_commands",
            "uq_publish_retry_commands_resulting_attempt_id",
        ):
            op.create_index(
                "uq_publish_retry_commands_resulting_attempt_id",
                "publish_retry_commands",
                ["resulting_attempt_id"],
                unique=True,
                postgresql_where=sa.text("resulting_attempt_id IS NOT NULL"),
            )

        # --- Worker claim path: status='pending' ORDER BY created_at ---
        # Reclaim (claimed + lease_expires_at < now) remains covered by
        # existing status index until reclaim volume warrants a second index.
        create_index_if_missing(
            "ix_publish_retry_commands_status_created_at",
            "publish_retry_commands",
            ["status", "created_at"],
        )

        # --- Structural: provider_write_started must carry a durable timestamp ---
        if not _check_constraint_exists(
            "ck_publish_retry_commands_provider_write_ts",
            "publish_retry_commands",
        ):
            op.create_check_constraint(
                "ck_publish_retry_commands_provider_write_ts",
                "publish_retry_commands",
                "status <> 'provider_write_started' "
                "OR provider_write_started_at IS NOT NULL",
            )


def downgrade() -> None:
    if table_exists("publish_retry_commands"):
        if _check_constraint_exists(
            "ck_publish_retry_commands_provider_write_ts",
            "publish_retry_commands",
        ):
            op.drop_constraint(
                "ck_publish_retry_commands_provider_write_ts",
                "publish_retry_commands",
                type_="check",
            )
        drop_index_if_exists(
            "ix_publish_retry_commands_status_created_at",
            "publish_retry_commands",
        )
        drop_index_if_exists(
            "uq_publish_retry_commands_resulting_attempt_id",
            "publish_retry_commands",
        )

    if table_exists("publish_attempts"):
        drop_index_if_exists(
            "uq_publish_attempts_retry_command_id",
            "publish_attempts",
        )
        # Restore pre-3C.1C-A non-unique lookup index from 20260925.
        create_index_if_missing(
            "ix_publish_attempts_retry_command_id",
            "publish_attempts",
            ["retry_command_id"],
        )
