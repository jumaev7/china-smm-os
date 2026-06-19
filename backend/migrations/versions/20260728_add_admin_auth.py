"""Admin Authentication & RBAC v1 — admin_users, admin_sessions, admin_audit_logs."""
import sqlalchemy as sa
from alembic import op

from migrations.helpers import create_index_if_missing, create_table_if_missing, drop_table_if_exists

revision = "20260728_add_admin_auth"
down_revision = "20260727_add_buyer_network"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "admin_users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    create_index_if_missing("ix_admin_users_email", "admin_users", ["email"], unique=True)
    create_index_if_missing("ix_admin_users_role", "admin_users", ["role"])
    create_index_if_missing("ix_admin_users_status", "admin_users", ["status"])

    create_table_if_missing(
        "admin_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("admin_user_id", sa.UUID(), nullable=False),
        sa.Column("login_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["admin_user_id"], ["admin_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index_if_missing("ix_admin_sessions_admin_user_id", "admin_sessions", ["admin_user_id"])
    create_index_if_missing("ix_admin_sessions_session_status", "admin_sessions", ["session_status"])

    create_table_if_missing(
        "admin_audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("admin_user_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("success", sa.String(length=10), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["admin_user_id"], ["admin_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index_if_missing("ix_admin_audit_logs_admin_user_id", "admin_audit_logs", ["admin_user_id"])
    create_index_if_missing("ix_admin_audit_logs_event_type", "admin_audit_logs", ["event_type"])
    create_index_if_missing("ix_admin_audit_logs_created_at", "admin_audit_logs", ["created_at"])


def downgrade() -> None:
    drop_table_if_exists("admin_audit_logs")
    drop_table_if_exists("admin_sessions")
    drop_table_if_exists("admin_users")
