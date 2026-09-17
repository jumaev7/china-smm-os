"""Add publish_intentional_publication_requests (I2a dormant schema).

Revision ID: 20260928_publish_intentional_publication_requests
Revises: 20260927_publish_write_coordination_registry

Additive only. No backfill, no attempt/command/registry mutation, no runtime
wiring. Historical publish rows remain untouched.

Downgrade drops this table. Safe only on throwaway DBs / before real request
rows exist — dropping a populated table destroys those records.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.helpers import (
    create_foreign_key_if_missing,
    create_index_if_missing,
    create_table_if_missing,
    drop_index_if_exists,
    drop_table_if_exists,
    foreign_key_exists,
    index_exists,
    table_exists,
)

revision = "20260928_publish_intentional_publication_requests"
down_revision = "20260927_publish_write_coordination_registry"
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
        "publish_intentional_publication_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("client_idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "publication_intent_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("publish_version", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="accepted",
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
            "publication_intent_id",
            name="uq_pipr_publication_intent_id",
        ),
        sa.CheckConstraint(
            "operation IN ('initial_publish', 'intentional_republish')",
            name="ck_pipr_operation",
        ),
        sa.CheckConstraint(
            "status IN ('accepted')",
            name="ck_pipr_status",
        ),
        sa.CheckConstraint(
            "char_length(btrim(client_idempotency_key)) > 0",
            name="ck_pipr_client_key_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(request_fingerprint) = 64 "
            "AND request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_pipr_fingerprint_sha256_hex",
        ),
    )

    if table_exists("publish_intentional_publication_requests"):
        # Request identity with NULLS NOT DISTINCT so multiple account_id NULL
        # rows for the same request-key scope cannot coexist (PG 15+/16).
        if not index_exists(
            "publish_intentional_publication_requests",
            "uq_pipr_request_identity",
        ):
            op.execute(
                sa.text(
                    "CREATE UNIQUE INDEX uq_pipr_request_identity "
                    "ON publish_intentional_publication_requests "
                    "(tenant_id, content_id, platform, account_id, "
                    "operation, client_idempotency_key) "
                    "NULLS NOT DISTINCT"
                )
            )

        create_foreign_key_if_missing(
            "fk_pipr_tenant_id",
            "publish_intentional_publication_requests",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        create_foreign_key_if_missing(
            "fk_pipr_content_id",
            "publish_intentional_publication_requests",
            "content_items",
            ["content_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        create_foreign_key_if_missing(
            "fk_pipr_account_id",
            "publish_intentional_publication_requests",
            "publishing_accounts",
            ["account_id"],
            ["id"],
            ondelete="RESTRICT",
        )

        create_index_if_missing(
            "ix_pipr_tenant_content",
            "publish_intentional_publication_requests",
            ["tenant_id", "content_id"],
        )
        create_index_if_missing(
            "ix_pipr_client_idempotency_key",
            "publish_intentional_publication_requests",
            ["client_idempotency_key"],
        )


def downgrade() -> None:
    if table_exists("publish_intentional_publication_requests"):
        drop_index_if_exists(
            "ix_pipr_client_idempotency_key",
            "publish_intentional_publication_requests",
        )
        drop_index_if_exists(
            "ix_pipr_tenant_content",
            "publish_intentional_publication_requests",
        )
        drop_index_if_exists(
            "uq_pipr_request_identity",
            "publish_intentional_publication_requests",
        )

        for fk_name in (
            "fk_pipr_account_id",
            "fk_pipr_content_id",
            "fk_pipr_tenant_id",
        ):
            if foreign_key_exists(fk_name):
                op.drop_constraint(
                    fk_name,
                    "publish_intentional_publication_requests",
                    type_="foreignkey",
                )

        for ck_name in (
            "ck_pipr_fingerprint_sha256_hex",
            "ck_pipr_client_key_nonempty",
            "ck_pipr_status",
            "ck_pipr_operation",
        ):
            if _check_constraint_exists(
                ck_name, "publish_intentional_publication_requests"
            ):
                op.drop_constraint(
                    ck_name,
                    "publish_intentional_publication_requests",
                    type_="check",
                )

    drop_table_if_exists("publish_intentional_publication_requests")
