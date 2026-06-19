"""Communication Hub MVP — follow-ups, templates, tenant links."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260817_add_communication_hub_mvp"
down_revision = "20260816_add_buyer_crm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, col in (
        ("communication_contacts", "tenant_id"),
        ("communication_threads", "tenant_id"),
    ):
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id UUID "
                f"REFERENCES tenants(id) ON DELETE CASCADE"
            )
        )
        create_index_if_missing(f"ix_{table}_tenant_id", table, ["tenant_id"])

    op.execute(
        sa.text(
            "ALTER TABLE communication_threads ADD COLUMN IF NOT EXISTS buyer_id UUID "
            "REFERENCES buyers(id) ON DELETE SET NULL"
        )
    )
    create_index_if_missing("ix_communication_threads_buyer_id", "communication_threads", ["buyer_id"])

    op.execute(
        sa.text(
            "ALTER TABLE communication_threads ADD COLUMN IF NOT EXISTS customer_id UUID "
            "REFERENCES sales_customers(id) ON DELETE SET NULL"
        )
    )
    create_index_if_missing("ix_communication_threads_customer_id", "communication_threads", ["customer_id"])

    op.execute(
        sa.text(
            "ALTER TABLE communication_messages ADD COLUMN IF NOT EXISTS status VARCHAR(20) "
            "NOT NULL DEFAULT 'sent'"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE communication_messages ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ "
            "DEFAULT NOW()"
        )
    )
    create_index_if_missing("ix_communication_messages_status", "communication_messages", ["status"])

    create_table_if_missing(
        "communication_follow_ups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "communication_id",
            UUID(as_uuid=True),
            sa.ForeignKey("communication_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "thread_id",
            UUID(as_uuid=True),
            sa.ForeignKey("communication_threads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("assigned_user", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_communication_follow_ups_tenant_id", "communication_follow_ups", ["tenant_id"])
    create_index_if_missing("ix_communication_follow_ups_communication_id", "communication_follow_ups", ["communication_id"])
    create_index_if_missing("ix_communication_follow_ups_thread_id", "communication_follow_ups", ["thread_id"])
    create_index_if_missing("ix_communication_follow_ups_due_date", "communication_follow_ups", ["due_date"])
    create_index_if_missing("ix_communication_follow_ups_status", "communication_follow_ups", ["status"])
    create_index_if_missing("ix_communication_follow_ups_assigned_user", "communication_follow_ups", ["assigned_user"])

    create_table_if_missing(
        "communication_message_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_communication_message_templates_tenant_id", "communication_message_templates", ["tenant_id"])
    create_index_if_missing("ix_communication_message_templates_category", "communication_message_templates", ["category"])


def downgrade() -> None:
    op.drop_table("communication_message_templates")
    op.drop_table("communication_follow_ups")
    op.drop_column("communication_messages", "updated_at")
    op.drop_column("communication_messages", "status")
    op.drop_column("communication_threads", "customer_id")
    op.drop_column("communication_threads", "buyer_id")
    op.drop_column("communication_threads", "tenant_id")
    op.drop_column("communication_contacts", "tenant_id")
