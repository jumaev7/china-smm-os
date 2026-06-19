"""Platform integration links — content ↔ sales CRM, comm hub ↔ sales CRM."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing

revision = "20260820_add_platform_integrations"
down_revision = "20260819_add_telegram_ingestion_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col_name, fk_table in (
        ("linked_sales_lead_id", "sales_leads"),
        ("linked_buyer_id", "buyers"),
        ("linked_sales_deal_id", "sales_deals"),
    ):
        add_column_if_missing(
            "content_items",
            sa.Column(
                col_name,
                UUID(as_uuid=True),
                sa.ForeignKey(f"{fk_table}.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        create_index_if_missing(f"ix_content_items_{col_name}", "content_items", [col_name])

    for table in ("communication_threads", "communication_contacts"):
        for col_name, fk_table in (
            ("sales_lead_id", "sales_leads"),
            ("sales_deal_id", "sales_deals"),
        ):
            add_column_if_missing(
                table,
                sa.Column(
                    col_name,
                    UUID(as_uuid=True),
                    sa.ForeignKey(f"{fk_table}.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )
            create_index_if_missing(f"ix_{table}_{col_name}", table, [col_name])


def downgrade() -> None:
    for table in ("communication_threads", "communication_contacts"):
        for col in ("sales_deal_id", "sales_lead_id"):
            op.drop_column(table, col)
    for col in ("linked_sales_deal_id", "linked_buyer_id", "linked_sales_lead_id"):
        op.drop_column("content_items", col)
