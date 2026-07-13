"""Bootstrap ORM base schema for greenfield databases.

Historical migrations assumed tables created via dev create_tables(); this revision
creates a frozen baseline schema derived from head minus later migration deltas.
"""
from __future__ import annotations

from alembic import op

from migrations.baseline_loader import apply_baseline_schema, drop_baseline_schema

revision = "20260521_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    apply_baseline_schema()


def downgrade() -> None:
    drop_baseline_schema()
