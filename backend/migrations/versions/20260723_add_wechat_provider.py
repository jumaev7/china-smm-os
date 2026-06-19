"""WeChat Provider v1 — provider registry, configurations, webhook framework."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260723_add_wechat_provider"
down_revision = "20260722_add_tenant_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "wechat_providers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_name", sa.String(length=255), nullable=False),
        sa.Column("provider_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("capabilities_json", JSONB(), nullable=True),
        sa.Column("config_json", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_wechat_providers_provider_type",
        "wechat_providers",
        ["provider_type"],
    )
    create_index_if_missing(
        "ix_wechat_providers_status",
        "wechat_providers",
        ["status"],
    )

    create_table_if_missing(
        "wechat_provider_configurations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            UUID(as_uuid=True),
            sa.ForeignKey("wechat_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("config_status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("config_json", JSONB(), nullable=True),
        sa.Column("last_connection_test", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_wechat_provider_configurations_provider_id",
        "wechat_provider_configurations",
        ["provider_id"],
    )
    create_index_if_missing(
        "ix_wechat_provider_configurations_tenant_id",
        "wechat_provider_configurations",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_wechat_provider_configurations_config_status",
        "wechat_provider_configurations",
        ["config_status"],
    )

    create_table_if_missing(
        "wechat_provider_webhook_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            UUID(as_uuid=True),
            sa.ForeignKey("wechat_providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="architecture_only",
        ),
        sa.Column("payload_json", JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_wechat_provider_webhook_events_provider_id",
        "wechat_provider_webhook_events",
        ["provider_id"],
    )
    create_index_if_missing(
        "ix_wechat_provider_webhook_events_event_type",
        "wechat_provider_webhook_events",
        ["event_type"],
    )
    create_index_if_missing(
        "ix_wechat_provider_webhook_events_status",
        "wechat_provider_webhook_events",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("wechat_provider_webhook_events")
    op.drop_table("wechat_provider_configurations")
    op.drop_table("wechat_providers")
