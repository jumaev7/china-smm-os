"""WeChat Contact Center — communication hub extensions."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import add_column_if_missing, create_foreign_key_if_missing, create_index_if_missing

revision = "20260708_add_wechat_contact_center"
down_revision = "20260707_add_lead_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "communication_contacts",
        sa.Column("wechat_id", sa.String(length=100), nullable=True),
    )
    add_column_if_missing(
        "communication_contacts",
        sa.Column("wecom_id", sa.String(length=100), nullable=True),
    )
    add_column_if_missing(
        "communication_contacts",
        sa.Column("qr_code_url", sa.String(length=500), nullable=True),
    )
    add_column_if_missing(
        "communication_contacts",
        sa.Column("preferred_language", sa.String(length=20), nullable=True),
    )
    create_index_if_missing("ix_communication_contacts_wechat_id", "communication_contacts", ["wechat_id"])
    create_index_if_missing("ix_communication_contacts_wecom_id", "communication_contacts", ["wecom_id"])

    add_column_if_missing(
        "communication_threads",
        sa.Column("deal_id", UUID(as_uuid=True), nullable=True),
    )
    add_column_if_missing(
        "communication_threads",
        sa.Column("external_contact_id", sa.String(length=100), nullable=True),
    )
    add_column_if_missing(
        "communication_threads",
        sa.Column("last_manual_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_foreign_key_if_missing(
        "fk_communication_threads_deal_id",
        "communication_threads",
        "crm_deals",
        ["deal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    create_index_if_missing("ix_communication_threads_deal_id", "communication_threads", ["deal_id"])
    create_index_if_missing(
        "ix_communication_threads_external_contact_id",
        "communication_threads",
        ["external_contact_id"],
    )

    add_column_if_missing(
        "communication_messages",
        sa.Column("original_language", sa.String(length=20), nullable=True),
    )
    add_column_if_missing(
        "communication_messages",
        sa.Column("translated_text", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "communication_messages",
        sa.Column("copied_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "communication_messages",
        sa.Column("manual_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("communication_messages", "manual_sent_at")
    op.drop_column("communication_messages", "copied_at")
    op.drop_column("communication_messages", "translated_text")
    op.drop_column("communication_messages", "original_language")
    op.drop_index("ix_communication_threads_external_contact_id", table_name="communication_threads")
    op.drop_index("ix_communication_threads_deal_id", table_name="communication_threads")
    op.drop_constraint("fk_communication_threads_deal_id", "communication_threads", type_="foreignkey")
    op.drop_column("communication_threads", "last_manual_sync_at")
    op.drop_column("communication_threads", "external_contact_id")
    op.drop_column("communication_threads", "deal_id")
    op.drop_index("ix_communication_contacts_wecom_id", table_name="communication_contacts")
    op.drop_index("ix_communication_contacts_wechat_id", table_name="communication_contacts")
    op.drop_column("communication_contacts", "preferred_language")
    op.drop_column("communication_contacts", "qr_code_url")
    op.drop_column("communication_contacts", "wecom_id")
    op.drop_column("communication_contacts", "wechat_id")
