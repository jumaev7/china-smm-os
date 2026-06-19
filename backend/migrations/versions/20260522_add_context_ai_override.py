"""add context_ai_override to content_items

Revision ID: 20260522_context_override
Revises: 20260522_telegram_instructions
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa
from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision = "20260522_context_override"
down_revision = "20260522_tg_instructions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "content_items",
        sa.Column("context_ai_override", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    drop_column_if_exists("content_items", "context_ai_override")
