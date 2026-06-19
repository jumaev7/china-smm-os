"""AI Command Center tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260627_add_ai_command_center"
down_revision = "20260626_add_buyer_finder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "ai_commands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("raw_command", sa.Text(), nullable=False),
        sa.Column("parsed_intent", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("action_plan_json", JSONB(), nullable=True),
        sa.Column("result_json", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_ai_commands_user_id", "ai_commands", ["user_id"])
    create_index_if_missing("ix_ai_commands_status", "ai_commands", ["status"])

    create_table_if_missing(
        "ai_command_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("command_id", UUID(as_uuid=True), sa.ForeignKey("ai_commands.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("result_json", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_ai_command_actions_command_id", "ai_command_actions", ["command_id"])
    create_index_if_missing("ix_ai_command_actions_action_type", "ai_command_actions", ["action_type"])
    create_index_if_missing("ix_ai_command_actions_status", "ai_command_actions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ai_command_actions_status", table_name="ai_command_actions")
    op.drop_index("ix_ai_command_actions_action_type", table_name="ai_command_actions")
    op.drop_index("ix_ai_command_actions_command_id", table_name="ai_command_actions")
    op.drop_table("ai_command_actions")
    op.drop_index("ix_ai_commands_status", table_name="ai_commands")
    op.drop_index("ix_ai_commands_user_id", table_name="ai_commands")
    op.drop_table("ai_commands")
