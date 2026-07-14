"""Automation Reliability Phase 2 — execution idempotency and retry fields."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import (
    add_column_if_missing,
    column_exists,
    create_index_if_missing,
    drop_column_if_exists,
    drop_index_if_exists,
    table_exists,
)

revision = "20260903_automation_reliability"
down_revision = "20260902_automation_center"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("tenant_automation_flows"):
        return

    add_column_if_missing(
        "tenant_automation_flows",
        sa.Column("max_retry_attempts", sa.Integer(), nullable=False, server_default="1"),
    )
    add_column_if_missing(
        "tenant_automation_flows",
        sa.Column("retry_delay_seconds", sa.Integer(), nullable=False, server_default="60"),
    )
    add_column_if_missing(
        "tenant_automation_flows",
        sa.Column("retry_backoff", sa.String(20), nullable=False, server_default="fixed"),
    )

    if not table_exists("tenant_automation_executions"):
        return

    add_column_if_missing(
        "tenant_automation_executions",
        sa.Column("execution_kind", sa.String(20), nullable=False, server_default="event"),
    )
    add_column_if_missing(
        "tenant_automation_executions",
        sa.Column("deduplication_key", sa.String(160), nullable=True),
    )
    add_column_if_missing(
        "tenant_automation_executions",
        sa.Column("root_execution_id", UUID(as_uuid=True), nullable=True),
    )
    add_column_if_missing(
        "tenant_automation_executions",
        sa.Column("retry_of_execution_id", UUID(as_uuid=True), nullable=True),
    )
    add_column_if_missing(
        "tenant_automation_executions",
        sa.Column("retry_number", sa.Integer(), nullable=False, server_default="0"),
    )
    add_column_if_missing(
        "tenant_automation_executions",
        sa.Column("error_category", sa.String(40), nullable=True),
    )
    add_column_if_missing(
        "tenant_automation_executions",
        sa.Column("is_retryable", sa.Boolean(), nullable=True),
    )

    bind = op.get_bind()

    # Backfill execution identity fields for Phase 1 rows.
    bind.execute(
        sa.text(
            """
            UPDATE tenant_automation_executions
            SET execution_kind = CASE
                WHEN COALESCE((input_payload->>'manual_test')::boolean, false) THEN 'manual'
                ELSE 'event'
            END
            """
        ),
    )
    bind.execute(
        sa.text(
            """
            UPDATE tenant_automation_executions
            SET deduplication_key = CASE
                WHEN COALESCE((input_payload->>'manual_test')::boolean, false)
                    THEN 'manual:' || id::text
                ELSE 'event:' || event_id::text
            END
            WHERE deduplication_key IS NULL OR BTRIM(deduplication_key) = ''
            """
        ),
    )
    bind.execute(
        sa.text(
            """
            UPDATE tenant_automation_executions
            SET root_execution_id = id
            WHERE root_execution_id IS NULL
            """
        ),
    )
    bind.execute(
        sa.text(
            """
            UPDATE tenant_automation_executions
            SET retry_number = GREATEST(0, COALESCE(attempt_number, 1) - 1)
            WHERE COALESCE(attempt_number, 1) > 1
            """
        ),
    )

    # Resolve duplicate automatic event executions before unique index.
    # Preserve the earliest row; rewrite later duplicates to unique legacy keys.
    dup_result = bind.execute(
        sa.text(
            """
            SELECT tenant_id, automation_flow_id, deduplication_key, COUNT(*) AS cnt
            FROM tenant_automation_executions
            WHERE deduplication_key IS NOT NULL
            GROUP BY tenant_id, automation_flow_id, deduplication_key
            HAVING COUNT(*) > 1
            """
        ),
    ).mappings().all()

    duplicate_groups = len(dup_result)
    rewritten = 0
    for group in dup_result:
        rows = bind.execute(
            sa.text(
                """
                SELECT id
                FROM tenant_automation_executions
                WHERE tenant_id = :tenant_id
                  AND automation_flow_id = :flow_id
                  AND deduplication_key = :dedup_key
                ORDER BY created_at ASC, id ASC
                """
            ),
            {
                "tenant_id": group["tenant_id"],
                "flow_id": group["automation_flow_id"],
                "dedup_key": group["deduplication_key"],
            },
        ).mappings().all()
        for row in rows[1:]:
            bind.execute(
                sa.text(
                    """
                    UPDATE tenant_automation_executions
                    SET deduplication_key = 'legacy_duplicate:' || id::text,
                        error_code = COALESCE(error_code, 'duplicate_superseded'),
                        error_category = COALESCE(error_category, 'conflict'),
                        is_retryable = COALESCE(is_retryable, false)
                    WHERE id = :id
                    """
                ),
                {"id": row["id"]},
            )
            rewritten += 1

    print(
        f"[20260903_automation_reliability] duplicate_groups={duplicate_groups} "
        f"rewritten={rewritten}"
    )

    # NOT NULL after backfill
    if column_exists("tenant_automation_executions", "deduplication_key"):
        op.alter_column(
            "tenant_automation_executions",
            "deduplication_key",
            existing_type=sa.String(160),
            nullable=False,
        )

    create_index_if_missing(
        "uq_tenant_automation_executions_dedup",
        "tenant_automation_executions",
        ["tenant_id", "automation_flow_id", "deduplication_key"],
        unique=True,
    )
    create_index_if_missing(
        "ix_tenant_automation_executions_root",
        "tenant_automation_executions",
        ["root_execution_id"],
    )
    create_index_if_missing(
        "ix_tenant_automation_executions_retry_of",
        "tenant_automation_executions",
        ["retry_of_execution_id"],
    )
    create_index_if_missing(
        "ix_tenant_automation_executions_kind_created",
        "tenant_automation_executions",
        ["tenant_id", "execution_kind", "created_at"],
    )


def downgrade() -> None:
    if not table_exists("tenant_automation_executions"):
        drop_column_if_exists("tenant_automation_flows", "retry_backoff")
        drop_column_if_exists("tenant_automation_flows", "retry_delay_seconds")
        drop_column_if_exists("tenant_automation_flows", "max_retry_attempts")
        return

    drop_index_if_exists(
        "ix_tenant_automation_executions_kind_created",
        "tenant_automation_executions",
    )
    drop_index_if_exists(
        "ix_tenant_automation_executions_retry_of",
        "tenant_automation_executions",
    )
    drop_index_if_exists(
        "ix_tenant_automation_executions_root",
        "tenant_automation_executions",
    )
    drop_index_if_exists(
        "uq_tenant_automation_executions_dedup",
        "tenant_automation_executions",
    )

    drop_column_if_exists("tenant_automation_executions", "is_retryable")
    drop_column_if_exists("tenant_automation_executions", "error_category")
    drop_column_if_exists("tenant_automation_executions", "retry_number")
    drop_column_if_exists("tenant_automation_executions", "retry_of_execution_id")
    drop_column_if_exists("tenant_automation_executions", "root_execution_id")
    drop_column_if_exists("tenant_automation_executions", "deduplication_key")
    drop_column_if_exists("tenant_automation_executions", "execution_kind")

    drop_column_if_exists("tenant_automation_flows", "retry_backoff")
    drop_column_if_exists("tenant_automation_flows", "retry_delay_seconds")
    drop_column_if_exists("tenant_automation_flows", "max_retry_attempts")
