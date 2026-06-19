"""Add outreach workflow fields and outreach_events table."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing

revision = "20260705_add_outreach_workflow"
down_revision = "20260704_add_buyer_outreach_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "buyer_outreach_messages",
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "buyer_outreach_messages",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "buyer_outreach_messages",
        sa.Column(
            "communication_thread_id",
            UUID(as_uuid=True),
            sa.ForeignKey("communication_threads.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    add_column_if_missing(
        "buyer_outreach_messages",
        sa.Column(
            "follow_up_task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("operator_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    add_column_if_missing(
        "buyer_outreach_messages",
        sa.Column("copied_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "buyer_outreach_messages",
        sa.Column("last_action_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index_if_missing(
        "ix_buyer_outreach_messages_communication_thread_id",
        "buyer_outreach_messages",
        ["communication_thread_id"],
    )
    create_index_if_missing(
        "ix_buyer_outreach_messages_follow_up_task_id",
        "buyer_outreach_messages",
        ["follow_up_task_id"],
    )

    create_table_if_missing(
        "outreach_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "outreach_id",
            UUID(as_uuid=True),
            sa.ForeignKey("buyer_outreach_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_outreach_events_outreach_id", "outreach_events", ["outreach_id"])
    create_index_if_missing("ix_outreach_events_event_type", "outreach_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_outreach_events_event_type", table_name="outreach_events")
    op.drop_index("ix_outreach_events_outreach_id", table_name="outreach_events")
    op.drop_table("outreach_events")
    op.drop_index("ix_buyer_outreach_messages_follow_up_task_id", table_name="buyer_outreach_messages")
    op.drop_index("ix_buyer_outreach_messages_communication_thread_id", table_name="buyer_outreach_messages")
    op.drop_column("buyer_outreach_messages", "last_action_at")
    op.drop_column("buyer_outreach_messages", "copied_at")
    op.drop_column("buyer_outreach_messages", "follow_up_task_id")
    op.drop_column("buyer_outreach_messages", "communication_thread_id")
    op.drop_column("buyer_outreach_messages", "approved_at")
    op.drop_column("buyer_outreach_messages", "sent_at")
