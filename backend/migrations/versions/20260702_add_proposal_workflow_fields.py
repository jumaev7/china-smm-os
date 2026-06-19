"""Add proposal workflow timestamps and buyer feedback."""
import sqlalchemy as sa
from alembic import op

from migrations.helpers import add_column_if_missing

revision = "20260702_add_proposal_workflow_fields"
down_revision = "20260701_add_proposal_export_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "proposal_documents",
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "proposal_documents",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "proposal_documents",
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "proposal_documents",
        sa.Column("follow_up_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "proposal_documents",
        sa.Column("buyer_feedback", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("proposal_documents", "buyer_feedback")
    op.drop_column("proposal_documents", "follow_up_at")
    op.drop_column("proposal_documents", "rejected_at")
    op.drop_column("proposal_documents", "accepted_at")
    op.drop_column("proposal_documents", "sent_at")
