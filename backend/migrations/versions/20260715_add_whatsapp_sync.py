"""WhatsApp Sync v1 — account registry and sync jobs."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260715_add_whatsapp_sync"
down_revision = "20260714_add_wechat_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "whatsapp_sync_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("account_name", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("phone_number", sa.String(length=50), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("external_account_id", sa.String(length=100), nullable=True),
        sa.Column("config_json", JSONB(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    create_index_if_missing(
        "ix_whatsapp_sync_accounts_account_type",
        "whatsapp_sync_accounts",
        ["account_type"],
    )
    create_index_if_missing(
        "ix_whatsapp_sync_accounts_status",
        "whatsapp_sync_accounts",
        ["status"],
    )
    create_index_if_missing(
        "ix_whatsapp_sync_accounts_phone_number",
        "whatsapp_sync_accounts",
        ["phone_number"],
    )
    create_index_if_missing(
        "ix_whatsapp_sync_accounts_external_account_id",
        "whatsapp_sync_accounts",
        ["external_account_id"],
    )

    create_table_if_missing(
        "whatsapp_sync_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("whatsapp_sync_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("stats_json", JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing("ix_whatsapp_sync_jobs_account_id", "whatsapp_sync_jobs", ["account_id"])
    create_index_if_missing("ix_whatsapp_sync_jobs_job_type", "whatsapp_sync_jobs", ["job_type"])
    create_index_if_missing("ix_whatsapp_sync_jobs_status", "whatsapp_sync_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("whatsapp_sync_jobs")
    op.drop_table("whatsapp_sync_accounts")
