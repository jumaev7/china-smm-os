"""Bootstrap ORM base schema for greenfield databases.

Historical migrations assumed tables created via dev create_tables(); this revision
lets `alembic upgrade head` run on an empty PostgreSQL database.
"""
from __future__ import annotations

from alembic import op

revision = "20260521_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def _register_models() -> None:
    import app.models  # noqa: F401 — register all ORM tables on Base.metadata


def upgrade() -> None:
    from app.core.database import Base

    _register_models()
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from app.core.database import Base

    _register_models()
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
