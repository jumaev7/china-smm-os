"""Pre-launch platform ops — pilot factories, feedback, audit logs, error reports."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260825_add_platform_ops"
down_revision = "20260824_extend_content_factory_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "pilot_factories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("factory_name", sa.String(255), nullable=False),
        sa.Column("country", sa.String(100), nullable=False, server_default=""),
        sa.Column("industry", sa.String(100), nullable=False, server_default=""),
        sa.Column("pilot_status", sa.String(30), nullable=False, server_default="invited"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("success_score", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_pilot_factories_factory_name", "pilot_factories", ["factory_name"])
    create_index_if_missing("ix_pilot_factories_pilot_status", "pilot_factories", ["pilot_status"])
    create_index_if_missing("ix_pilot_factories_tenant_id", "pilot_factories", ["tenant_id"])

    create_table_if_missing(
        "platform_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "pilot_factory_id",
            UUID(as_uuid=True),
            sa.ForeignKey("pilot_factories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("feedback_type", sa.String(30), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_platform_feedback_tenant_id", "platform_feedback", ["tenant_id"])
    create_index_if_missing("ix_platform_feedback_feedback_type", "platform_feedback", ["feedback_type"])
    create_index_if_missing("ix_platform_feedback_category", "platform_feedback", ["category"])
    create_index_if_missing("ix_platform_feedback_status", "platform_feedback", ["status"])

    create_table_if_missing(
        "platform_audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_platform_audit_logs_actor_type", "platform_audit_logs", ["actor_type"])
    create_index_if_missing("ix_platform_audit_logs_actor_id", "platform_audit_logs", ["actor_id"])
    create_index_if_missing("ix_platform_audit_logs_tenant_id", "platform_audit_logs", ["tenant_id"])
    create_index_if_missing("ix_platform_audit_logs_event_type", "platform_audit_logs", ["event_type"])
    create_index_if_missing("ix_platform_audit_logs_created_at", "platform_audit_logs", ["created_at"])

    create_table_if_missing(
        "platform_error_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("path", sa.String(500), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("error_context", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_platform_error_reports_source", "platform_error_reports", ["source"])
    create_index_if_missing("ix_platform_error_reports_tenant_id", "platform_error_reports", ["tenant_id"])
    create_index_if_missing("ix_platform_error_reports_created_at", "platform_error_reports", ["created_at"])


def downgrade() -> None:
    op.drop_table("platform_error_reports")
    op.drop_table("platform_audit_logs")
    op.drop_table("platform_feedback")
    op.drop_table("pilot_factories")
