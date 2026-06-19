"""Rename content_plan_items.content_item_id to linked_content_id."""
from alembic import op
import sqlalchemy as sa

revision = "20260601_content_plan_linked_content"
down_revision = "20260531_add_content_planner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "content_plan_items" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("content_plan_items")}
    if "content_item_id" in cols and "linked_content_id" not in cols:
        op.alter_column(
            "content_plan_items",
            "content_item_id",
            new_column_name="linked_content_id",
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "content_plan_items" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("content_plan_items")}
    if "linked_content_id" in cols and "content_item_id" not in cols:
        op.alter_column(
            "content_plan_items",
            "linked_content_id",
            new_column_name="content_item_id",
        )
