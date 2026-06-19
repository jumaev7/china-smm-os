"""add telegram group fields

Revision ID: 20260522_tg_group
Revises: 20260522_brand
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.helpers import add_column_if_missing, create_index_if_missing, drop_column_if_exists

revision: str = "20260522_tg_group"
down_revision: Union[str, None] = "20260522_brand"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    add_column_if_missing("clients", sa.Column("telegram_group_id", sa.String(length=50), nullable=True))
    add_column_if_missing("clients", sa.Column("telegram_group_title", sa.String(length=255), nullable=True))
    create_index_if_missing("ix_clients_telegram_group_id", "clients", ["telegram_group_id"], unique=False)
    add_column_if_missing("content_items", sa.Column("telegram_group_title", sa.String(length=255), nullable=True))


def downgrade() -> None:
    drop_column_if_exists("content_items", "telegram_group_title")
    op.drop_index("ix_clients_telegram_group_id", table_name="clients")
    drop_column_if_exists("clients", "telegram_group_title")
    drop_column_if_exists("clients", "telegram_group_id")
