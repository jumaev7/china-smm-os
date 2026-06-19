"""Add sales playbooks and link fields for apply tracking."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing

revision = "20260706_add_sales_playbooks"
down_revision = "20260705_add_outreach_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "sales_playbooks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("product_category", sa.String(100), nullable=True),
        sa.Column("buyer_type", sa.String(100), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_sales_playbooks_client_id", "sales_playbooks", ["client_id"])
    create_index_if_missing("ix_sales_playbooks_product_category", "sales_playbooks", ["product_category"])
    create_index_if_missing("ix_sales_playbooks_buyer_type", "sales_playbooks", ["buyer_type"])
    create_index_if_missing("ix_sales_playbooks_country", "sales_playbooks", ["country"])
    create_index_if_missing("ix_sales_playbooks_channel", "sales_playbooks", ["channel"])
    create_index_if_missing("ix_sales_playbooks_status", "sales_playbooks", ["status"])

    create_table_if_missing(
        "sales_playbook_steps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "playbook_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sales_playbooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("step_type", sa.String(30), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("template_text", sa.Text(), nullable=True),
        sa.Column("delay_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_sales_playbook_steps_playbook_id", "sales_playbook_steps", ["playbook_id"])
    create_index_if_missing("ix_sales_playbook_steps_step_type", "sales_playbook_steps", ["step_type"])

    add_column_if_missing(
        "buyer_outreach_messages",
        sa.Column(
            "sales_playbook_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sales_playbooks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    add_column_if_missing(
        "buyer_outreach_messages",
        sa.Column(
            "sales_playbook_step_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sales_playbook_steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    create_index_if_missing(
        "ix_buyer_outreach_messages_sales_playbook_id",
        "buyer_outreach_messages",
        ["sales_playbook_id"],
    )

    add_column_if_missing(
        "proposal_documents",
        sa.Column(
            "sales_playbook_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sales_playbooks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    add_column_if_missing(
        "proposal_documents",
        sa.Column(
            "sales_playbook_step_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sales_playbook_steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    create_index_if_missing(
        "ix_proposal_documents_sales_playbook_id",
        "proposal_documents",
        ["sales_playbook_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_proposal_documents_sales_playbook_id", table_name="proposal_documents")
    op.drop_column("proposal_documents", "sales_playbook_step_id")
    op.drop_column("proposal_documents", "sales_playbook_id")
    op.drop_index("ix_buyer_outreach_messages_sales_playbook_id", table_name="buyer_outreach_messages")
    op.drop_column("buyer_outreach_messages", "sales_playbook_step_id")
    op.drop_column("buyer_outreach_messages", "sales_playbook_id")
    op.drop_index("ix_sales_playbook_steps_step_type", table_name="sales_playbook_steps")
    op.drop_index("ix_sales_playbook_steps_playbook_id", table_name="sales_playbook_steps")
    op.drop_table("sales_playbook_steps")
    op.drop_index("ix_sales_playbooks_status", table_name="sales_playbooks")
    op.drop_index("ix_sales_playbooks_channel", table_name="sales_playbooks")
    op.drop_index("ix_sales_playbooks_country", table_name="sales_playbooks")
    op.drop_index("ix_sales_playbooks_buyer_type", table_name="sales_playbooks")
    op.drop_index("ix_sales_playbooks_product_category", table_name="sales_playbooks")
    op.drop_index("ix_sales_playbooks_client_id", table_name="sales_playbooks")
    op.drop_table("sales_playbooks")
