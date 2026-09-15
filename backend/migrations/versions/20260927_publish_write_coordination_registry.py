"""Add publish_write_coordination_registry + publication_intent_id storage (R1).

Revision ID: 20260927_publish_write_coordination_registry
Revises: 20260926_publish_retry_command_lineage

Schema only. No backfill, no runtime wiring, no data rewrite of intents.
Historical attempt/command rows keep publication_intent_id NULL until a later
enforcement stage.
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
    foreign_key_exists,
    index_exists,
    table_exists,
)

revision = "20260927_publish_write_coordination_registry"
down_revision = "20260926_publish_retry_command_lineage"
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
    create_table_if_missing(
        "publish_write_coordination_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("logical_write_key", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("publication_intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column(
            "generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("owner_type", sa.String(length=40), nullable=True),
        sa.Column("owner_id", sa.String(length=120), nullable=True),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "provider_write_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("current_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            "logical_write_key",
            name="uq_publish_write_coordination_registry_logical_write_key",
        ),
        sa.CheckConstraint(
            "state IN ("
            "'RESERVED', 'WRITE_STARTED', 'SUCCEEDED', 'FAILED_SAFE', "
            "'AMBIGUOUS', 'RESOLVED_SUCCEEDED', 'RESOLVED_FAILED', 'SUPERSEDED'"
            ")",
            name="ck_publish_write_coordination_registry_state",
        ),
        sa.CheckConstraint(
            "generation >= 0",
            name="ck_publish_write_coordination_registry_generation_nonneg",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_publish_write_coordination_registry_version_nonneg",
        ),
        sa.CheckConstraint(
            "state <> 'WRITE_STARTED' OR provider_write_started_at IS NOT NULL",
            name="ck_publish_write_coordination_registry_write_started_ts",
        ),
    )

    if table_exists("publish_write_coordination_registry"):
        # Destination+intent uniqueness with NULLS NOT DISTINCT so multiple
        # account_id NULL rows for the same destination+intent cannot coexist.
        # Chosen over paired partial indexes: single constraint, PG 16 supports it.
        if not index_exists(
            "publish_write_coordination_registry",
            "uq_publish_write_coordination_registry_destination_intent",
        ):
            op.execute(
                sa.text(
                    "CREATE UNIQUE INDEX "
                    "uq_publish_write_coordination_registry_destination_intent "
                    "ON publish_write_coordination_registry "
                    "(tenant_id, content_id, platform, account_id, "
                    "publication_intent_id) "
                    "NULLS NOT DISTINCT"
                )
            )

        create_foreign_key_if_missing(
            "fk_publish_write_coordination_registry_tenant_id",
            "publish_write_coordination_registry",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        create_foreign_key_if_missing(
            "fk_publish_write_coordination_registry_content_id",
            "publish_write_coordination_registry",
            "content_items",
            ["content_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        create_foreign_key_if_missing(
            "fk_publish_write_coordination_registry_account_id",
            "publish_write_coordination_registry",
            "publishing_accounts",
            ["account_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        create_foreign_key_if_missing(
            "fk_publish_write_coordination_registry_supersedes_id",
            "publish_write_coordination_registry",
            "publish_write_coordination_registry",
            ["supersedes_id"],
            ["id"],
            ondelete="RESTRICT",
        )

        create_index_if_missing(
            "ix_publish_write_coordination_registry_tenant_state",
            "publish_write_coordination_registry",
            ["tenant_id", "state"],
        )
        create_index_if_missing(
            "ix_publish_write_coordination_registry_content_platform",
            "publish_write_coordination_registry",
            ["content_id", "platform"],
        )
        create_index_if_missing(
            "ix_publish_write_coordination_registry_state_lease_expires",
            "publish_write_coordination_registry",
            ["state", "lease_expires_at"],
        )
        create_index_if_missing(
            "ix_publish_write_coordination_registry_publication_intent_id",
            "publish_write_coordination_registry",
            ["publication_intent_id"],
        )
        create_index_if_missing(
            "ix_publish_write_coordination_registry_current_attempt_id",
            "publish_write_coordination_registry",
            ["current_attempt_id"],
        )
        create_index_if_missing(
            "ix_publish_write_coordination_registry_current_command_id",
            "publish_write_coordination_registry",
            ["current_command_id"],
        )

    # Durable intent storage on attempt/command — nullable for historical rows.
    # No backfill in R1. Soft columns (no FK to a dedicated intent table).
    if table_exists("publish_attempts"):
        add_column_if_missing(
            "publish_attempts",
            sa.Column(
                "publication_intent_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        create_index_if_missing(
            "ix_publish_attempts_publication_intent_id",
            "publish_attempts",
            ["publication_intent_id"],
        )

    if table_exists("publish_retry_commands"):
        add_column_if_missing(
            "publish_retry_commands",
            sa.Column(
                "publication_intent_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        create_index_if_missing(
            "ix_publish_retry_commands_publication_intent_id",
            "publish_retry_commands",
            ["publication_intent_id"],
        )


def downgrade() -> None:
    drop_index_if_exists(
        "ix_publish_retry_commands_publication_intent_id",
        "publish_retry_commands",
    )
    drop_column_if_exists("publish_retry_commands", "publication_intent_id")

    drop_index_if_exists(
        "ix_publish_attempts_publication_intent_id",
        "publish_attempts",
    )
    drop_column_if_exists("publish_attempts", "publication_intent_id")

    if table_exists("publish_write_coordination_registry"):
        drop_index_if_exists(
            "ix_publish_write_coordination_registry_current_command_id",
            "publish_write_coordination_registry",
        )
        drop_index_if_exists(
            "ix_publish_write_coordination_registry_current_attempt_id",
            "publish_write_coordination_registry",
        )
        drop_index_if_exists(
            "ix_publish_write_coordination_registry_publication_intent_id",
            "publish_write_coordination_registry",
        )
        drop_index_if_exists(
            "ix_publish_write_coordination_registry_state_lease_expires",
            "publish_write_coordination_registry",
        )
        drop_index_if_exists(
            "ix_publish_write_coordination_registry_content_platform",
            "publish_write_coordination_registry",
        )
        drop_index_if_exists(
            "ix_publish_write_coordination_registry_tenant_state",
            "publish_write_coordination_registry",
        )
        drop_index_if_exists(
            "uq_publish_write_coordination_registry_destination_intent",
            "publish_write_coordination_registry",
        )

        for fk_name in (
            "fk_publish_write_coordination_registry_supersedes_id",
            "fk_publish_write_coordination_registry_account_id",
            "fk_publish_write_coordination_registry_content_id",
            "fk_publish_write_coordination_registry_tenant_id",
        ):
            if foreign_key_exists(fk_name):
                op.drop_constraint(
                    fk_name,
                    "publish_write_coordination_registry",
                    type_="foreignkey",
                )

        # Drop CHECKs before table if present (drop_table cascades them, but
        # explicit for clarity when inspecting downgrade paths).
        for ck_name in (
            "ck_publish_write_coordination_registry_write_started_ts",
            "ck_publish_write_coordination_registry_version_nonneg",
            "ck_publish_write_coordination_registry_generation_nonneg",
            "ck_publish_write_coordination_registry_state",
        ):
            if _check_constraint_exists(
                ck_name, "publish_write_coordination_registry"
            ):
                op.drop_constraint(
                    ck_name,
                    "publish_write_coordination_registry",
                    type_="check",
                )

    drop_table_if_exists("publish_write_coordination_registry")
