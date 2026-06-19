"""add client brand profile columns

Revision ID: 20260522_brand
Revises:
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision: str = "20260522_brand"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    add_column_if_missing("clients", sa.Column("brand_name", sa.String(length=255), nullable=True))
    add_column_if_missing("clients", sa.Column("business_description", sa.Text(), nullable=True))
    add_column_if_missing("clients", sa.Column("products_services", sa.Text(), nullable=True))
    add_column_if_missing("clients", sa.Column("target_audience", sa.Text(), nullable=True))
    add_column_if_missing(
        "clients",
        sa.Column("tone_of_voice", sa.String(length=30), nullable=False, server_default="friendly"),
    )
    add_column_if_missing(
        "clients",
        sa.Column("preferred_languages", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    add_column_if_missing("clients", sa.Column("cta_phone", sa.String(length=100), nullable=True))
    add_column_if_missing("clients", sa.Column("cta_telegram", sa.String(length=100), nullable=True))
    add_column_if_missing("clients", sa.Column("cta_website", sa.String(length=500), nullable=True))
    add_column_if_missing("clients", sa.Column("cta_address", sa.String(length=500), nullable=True))
    add_column_if_missing("clients", sa.Column("words_to_avoid", sa.Text(), nullable=True))
    add_column_if_missing("clients", sa.Column("hashtag_preferences", sa.Text(), nullable=True))
    add_column_if_missing("clients", sa.Column("logo_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    drop_column_if_exists("clients", "logo_url")
    drop_column_if_exists("clients", "hashtag_preferences")
    drop_column_if_exists("clients", "words_to_avoid")
    drop_column_if_exists("clients", "cta_address")
    drop_column_if_exists("clients", "cta_website")
    drop_column_if_exists("clients", "cta_telegram")
    drop_column_if_exists("clients", "cta_phone")
    drop_column_if_exists("clients", "preferred_languages")
    drop_column_if_exists("clients", "tone_of_voice")
    drop_column_if_exists("clients", "target_audience")
    drop_column_if_exists("clients", "products_services")
    drop_column_if_exists("clients", "business_description")
    drop_column_if_exists("clients", "brand_name")
