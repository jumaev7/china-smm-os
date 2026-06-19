"""Client AI knowledge base table."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260603_add_client_knowledge_base"
down_revision = "20260602_add_media_request"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "client_knowledge_base",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("importance", sa.String(length=10), nullable=False, server_default="medium"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_client_knowledge_base_client_id", "client_knowledge_base", ["client_id"])
    create_index_if_missing("ix_client_knowledge_base_section", "client_knowledge_base", ["section"])


def downgrade() -> None:
    op.drop_index("ix_client_knowledge_base_section", table_name="client_knowledge_base")
    op.drop_index("ix_client_knowledge_base_client_id", table_name="client_knowledge_base")
    op.drop_table("client_knowledge_base")
