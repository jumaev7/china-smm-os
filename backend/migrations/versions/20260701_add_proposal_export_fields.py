"""Add proposal export file paths and timestamp."""
import sqlalchemy as sa
from alembic import op

from migrations.helpers import add_column_if_missing

revision = "20260701_add_proposal_export_fields"
down_revision = "20260630_add_proposal_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "proposal_documents",
        sa.Column("exported_pdf_path", sa.String(500), nullable=True),
    )
    add_column_if_missing(
        "proposal_documents",
        sa.Column("exported_docx_path", sa.String(500), nullable=True),
    )
    add_column_if_missing(
        "proposal_documents",
        sa.Column("last_exported_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("proposal_documents", "last_exported_at")
    op.drop_column("proposal_documents", "exported_docx_path")
    op.drop_column("proposal_documents", "exported_pdf_path")
