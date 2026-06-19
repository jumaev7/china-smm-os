"""Admin Security Hardening v1 — session nonce, login lockout columns."""
import sqlalchemy as sa
from alembic import op

revision = "20260729_admin_security_hardening"
down_revision = "20260728_add_admin_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0",
    )
    op.execute(
        "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ",
    )
    op.execute(
        "ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS access_token_nonce VARCHAR(64)",
    )


def downgrade() -> None:
    op.drop_column("admin_sessions", "access_token_nonce")
    op.drop_column("admin_users", "locked_until")
    op.drop_column("admin_users", "failed_login_attempts")
