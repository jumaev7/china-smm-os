from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
)


def _register_query_profiler_events() -> None:
    from sqlalchemy import event

    from app.core.query_profiler import on_after_cursor_execute, on_before_cursor_execute

    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        on_before_cursor_execute()

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        on_after_cursor_execute()


_register_query_profiler_events()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

_db_probe_semaphore: asyncio.Semaphore | None = None


def get_db_probe_semaphore() -> asyncio.Semaphore:
    global _db_probe_semaphore
    if _db_probe_semaphore is None:
        _db_probe_semaphore = asyncio.Semaphore(settings.DB_PROBE_CONCURRENCY)
    return _db_probe_semaphore


@asynccontextmanager
async def db_probe_slot():
    """Limit concurrent nested ASGI probes — each opens an independent DB session."""
    sem = get_db_probe_semaphore()
    await sem.acquire()
    try:
        yield
    finally:
        sem.release()


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Short-lived session for background tasks and probe helpers."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def is_pool_exhaustion_error(exc: BaseException) -> bool:
    from sqlalchemy.exc import TimeoutError as SATimeoutError

    if isinstance(exc, SATimeoutError):
        return True
    name = type(exc).__name__
    if name in ("TooManyConnectionsError", "TimeoutError"):
        return True
    msg = str(exc).lower()
    return (
        "too many clients" in msg
        or "too many connections" in msg
        or "queuepool limit" in msg
        or "connection timed out" in msg
    )


def pool_status() -> dict[str, int | float]:
    pool = engine.pool
    return {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
    }


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    try:
        async with AsyncSessionLocal() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        if is_pool_exhaustion_error(exc):
            logger.error("[DB] connection pool exhausted: %s", exc)
            from fastapi import HTTPException

            raise HTTPException(
                status_code=503,
                detail="Database temporarily overloaded — retry shortly.",
            ) from exc
        raise


async def create_tables():
    """Create all tables (dev only — use Alembic in production)."""
    async with engine.begin() as conn:
        from app.models import client, media, content, calendar, telegram_buffer, publishing_account, publish_attempt, content_plan, client_knowledge_base, operator_task, content_factory, crm_lead, crm_proposal, crm_document, crm_deal, crm_pipeline_event, deal_room, attribution_source, revenue_event, partner, partner_network, sales_agent_recommendation, sales_assistant_recommendation, sales_workflow_recommendation, product, export_agent, campaign, media_library, communication, attribution_link, landing_page, buyer_recommendation, buyer_discovery, buyer_network, buyer_crm, marketplace, ai_command, whatsapp, wechat_sync, wechat_provider, whatsapp_sync, whatsapp_provider, factory_partner_application, customer_portal_account, factory_platform_profile, factory_profile, tenant, admin_user, sales_crm  # noqa
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_client_brand_columns)
        await conn.run_sync(_ensure_telegram_buffer_columns)
        await conn.run_sync(_ensure_content_plan_columns)
        await conn.run_sync(_ensure_crm_deals_columns)
        await conn.run_sync(_ensure_crm_leads_columns)
        await conn.run_sync(_ensure_operator_tasks_columns)
        await conn.run_sync(_ensure_partners_network_columns)
        await conn.run_sync(_ensure_content_campaign_column)
        await conn.run_sync(_ensure_content_repurpose_columns)
        await conn.run_sync(_ensure_communication_wechat_columns)
        await conn.run_sync(_ensure_communication_hub_mvp_columns)
        await conn.run_sync(_ensure_whatsapp_tables)
        await conn.run_sync(_ensure_tenant_auth_columns)
        await conn.run_sync(_ensure_factory_platform_v2_management_columns)
        await conn.run_sync(_ensure_telegram_ingestion_columns)
        await conn.run_sync(_ensure_content_factory_ai_columns)


async def ensure_platform_event_bus_schema() -> None:
    """Apply idempotent DDL for platform event bus tables only."""
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_platform_event_bus_tables)


async def ensure_dev_schema_patches() -> None:
    """Dev-only idempotent DDL for legacy drift; production must use Alembic only.

    Most objects here are also covered by migrations after ``alembic upgrade head``.
    Kept for local databases that predate a stamped ``alembic_version`` row.
    """
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_crm_leads_columns)
        await conn.run_sync(_ensure_outreach_proposal_columns)
        await conn.run_sync(_ensure_operator_tasks_columns)
        await conn.run_sync(_ensure_communication_wechat_columns)
        await conn.run_sync(_ensure_communication_platform_integration_columns)
        await conn.run_sync(_ensure_communication_hub_mvp_columns)
        await conn.run_sync(_ensure_whatsapp_tables)
        await conn.run_sync(_ensure_tenant_columns)


        await conn.run_sync(_ensure_whatsapp_tables)
        await conn.run_sync(_ensure_tenant_auth_columns)
        await conn.run_sync(_ensure_admin_security_columns)
        await conn.run_sync(_ensure_factory_platform_v2_management_columns)
        await conn.run_sync(_ensure_client_briefs_columns)
        await conn.run_sync(_ensure_wechat_business_foundation_columns)
        await conn.run_sync(_ensure_whatsapp_business_foundation_columns)
        await conn.run_sync(_ensure_telegram_ingestion_columns)
        await conn.run_sync(_ensure_content_factory_ai_columns)
        await conn.run_sync(_ensure_meta_publishing_columns)
        await conn.run_sync(_ensure_publishing_accounts_tenant_id)
        await conn.run_sync(_ensure_executive_crm_pipeline_columns)
        await conn.run_sync(_ensure_tenant_onboarding_v2_columns)
        await conn.run_sync(_ensure_customer_success_journey_columns)
        await conn.run_sync(_ensure_platform_event_bus_tables)


def _ensure_platform_event_bus_tables(connection) -> None:
    """Platform event bus — activity feed, notifications, automation triggers."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())

    if "tenant_activity_events" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_activity_events ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "event_id UUID NOT NULL, "
            "event_type VARCHAR(80) NOT NULL, "
            "category VARCHAR(40) NOT NULL, "
            "title VARCHAR(255) NOT NULL, "
            "description TEXT, "
            "actor_type VARCHAR(20), "
            "actor_id UUID, "
            "resource_type VARCHAR(50), "
            "resource_id VARCHAR(100), "
            "payload JSONB, "
            "status VARCHAR(20) NOT NULL DEFAULT 'recorded', "
            "occurred_at TIMESTAMPTZ NOT NULL, "
            "created_at TIMESTAMPTZ DEFAULT NOW()"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_activity_events_tenant_id "
            "ON tenant_activity_events (tenant_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_activity_events_event_type "
            "ON tenant_activity_events (event_type)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_activity_events_occurred_at "
            "ON tenant_activity_events (occurred_at)"
        ))

    if "tenant_event_notifications" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_event_notifications ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "event_id UUID NOT NULL, "
            "event_type VARCHAR(80) NOT NULL, "
            "title VARCHAR(255) NOT NULL, "
            "body TEXT, "
            "severity VARCHAR(20) NOT NULL DEFAULT 'info', "
            "resource_type VARCHAR(50), "
            "resource_id VARCHAR(100), "
            "payload JSONB, "
            "status VARCHAR(20) NOT NULL DEFAULT 'unread', "
            "created_at TIMESTAMPTZ DEFAULT NOW()"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_event_notifications_tenant_id "
            "ON tenant_event_notifications (tenant_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_event_notifications_status "
            "ON tenant_event_notifications (status)"
        ))

    if "tenant_event_notifications" in tables:
        for sql in (
            "ALTER TABLE tenant_event_notifications "
            "ADD COLUMN IF NOT EXISTS category VARCHAR(40) NOT NULL DEFAULT 'platform'",
            "ALTER TABLE tenant_event_notifications "
            "ADD COLUMN IF NOT EXISTS is_read BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE tenant_event_notifications "
            "ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ",
            "ALTER TABLE tenant_event_notifications "
            "ADD COLUMN IF NOT EXISTS action_url VARCHAR(500)",
            "ALTER TABLE tenant_event_notifications "
            "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
            "ALTER TABLE tenant_event_notifications "
            "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
        ):
            connection.execute(text(sql))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_event_notifications_tenant_created "
            "ON tenant_event_notifications (tenant_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_event_notifications_tenant_is_read "
            "ON tenant_event_notifications (tenant_id, is_read)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_event_notifications_tenant_category "
            "ON tenant_event_notifications (tenant_id, category)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_event_notifications_tenant_severity "
            "ON tenant_event_notifications (tenant_id, severity)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_event_notifications_tenant_deleted_at "
            "ON tenant_event_notifications (tenant_id, deleted_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_event_notifications_event_id "
            "ON tenant_event_notifications (event_id)",
        ):
            connection.execute(text(sql))

    if "tenant_automation_triggers" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_automation_triggers ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "event_id UUID NOT NULL, "
            "event_type VARCHAR(80) NOT NULL, "
            "trigger_key VARCHAR(120) NOT NULL, "
            "workflow_hint VARCHAR(60), "
            "payload JSONB, "
            "status VARCHAR(20) NOT NULL DEFAULT 'pending', "
            "created_at TIMESTAMPTZ DEFAULT NOW()"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_triggers_tenant_id "
            "ON tenant_automation_triggers (tenant_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_triggers_status "
            "ON tenant_automation_triggers (status)"
        ))

    if "tenant_automation_flows" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_automation_flows ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "key VARCHAR(120) NOT NULL, "
            "name VARCHAR(255) NOT NULL, "
            "description TEXT, "
            "category VARCHAR(40) NOT NULL, "
            "trigger_event VARCHAR(80) NOT NULL, "
            "action_type VARCHAR(60) NOT NULL, "
            "action_config JSONB NOT NULL DEFAULT '{}'::jsonb, "
            "status VARCHAR(20) NOT NULL DEFAULT 'enabled', "
            "is_system BOOLEAN NOT NULL DEFAULT false, "
            "max_retry_attempts INTEGER NOT NULL DEFAULT 1, "
            "retry_delay_seconds INTEGER NOT NULL DEFAULT 60, "
            "retry_backoff VARCHAR(20) NOT NULL DEFAULT 'fixed', "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ DEFAULT NOW(), "
            "last_executed_at TIMESTAMPTZ, "
            "last_execution_status VARCHAR(20), "
            "CONSTRAINT uq_tenant_automation_flows_tenant_key UNIQUE (tenant_id, key)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_flows_tenant_status "
            "ON tenant_automation_flows (tenant_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_flows_tenant_trigger "
            "ON tenant_automation_flows (tenant_id, trigger_event)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_flows_tenant_updated "
            "ON tenant_automation_flows (tenant_id, updated_at)",
        ):
            connection.execute(text(sql))

    if "tenant_automation_executions" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_automation_executions ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "automation_flow_id UUID NOT NULL REFERENCES tenant_automation_flows(id) ON DELETE CASCADE, "
            "event_id UUID NOT NULL, "
            "trigger_event VARCHAR(80) NOT NULL, "
            "status VARCHAR(20) NOT NULL DEFAULT 'pending', "
            "execution_kind VARCHAR(20) NOT NULL DEFAULT 'event', "
            "deduplication_key VARCHAR(160) NOT NULL, "
            "root_execution_id UUID REFERENCES tenant_automation_executions(id) ON DELETE SET NULL, "
            "retry_of_execution_id UUID REFERENCES tenant_automation_executions(id) ON DELETE SET NULL, "
            "retry_number INTEGER NOT NULL DEFAULT 0, "
            "started_at TIMESTAMPTZ NOT NULL, "
            "finished_at TIMESTAMPTZ, "
            "duration_ms INTEGER, "
            "input_payload JSONB, "
            "result_payload JSONB, "
            "error_code VARCHAR(60), "
            "error_message TEXT, "
            "error_category VARCHAR(40), "
            "is_retryable BOOLEAN, "
            "attempt_number INTEGER NOT NULL DEFAULT 1, "
            "created_at TIMESTAMPTZ DEFAULT NOW()"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_executions_tenant_created "
            "ON tenant_automation_executions (tenant_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_executions_tenant_status_created "
            "ON tenant_automation_executions (tenant_id, status, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_executions_flow_created "
            "ON tenant_automation_executions (automation_flow_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_executions_event_id "
            "ON tenant_automation_executions (event_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_automation_executions_dedup "
            "ON tenant_automation_executions (tenant_id, automation_flow_id, deduplication_key)",
        ):
            connection.execute(text(sql))

    # Phase 2 reliability columns for installs that already had automation tables.
    if "tenant_automation_flows" in tables:
        for sql in (
            "ALTER TABLE tenant_automation_flows "
            "ADD COLUMN IF NOT EXISTS max_retry_attempts INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE tenant_automation_flows "
            "ADD COLUMN IF NOT EXISTS retry_delay_seconds INTEGER NOT NULL DEFAULT 60",
            "ALTER TABLE tenant_automation_flows "
            "ADD COLUMN IF NOT EXISTS retry_backoff VARCHAR(20) NOT NULL DEFAULT 'fixed'",
        ):
            connection.execute(text(sql))

    if "tenant_automation_executions" in tables:
        for sql in (
            "ALTER TABLE tenant_automation_executions "
            "ADD COLUMN IF NOT EXISTS execution_kind VARCHAR(20) NOT NULL DEFAULT 'event'",
            "ALTER TABLE tenant_automation_executions "
            "ADD COLUMN IF NOT EXISTS deduplication_key VARCHAR(160)",
            "ALTER TABLE tenant_automation_executions "
            "ADD COLUMN IF NOT EXISTS root_execution_id UUID",
            "ALTER TABLE tenant_automation_executions "
            "ADD COLUMN IF NOT EXISTS retry_of_execution_id UUID",
            "ALTER TABLE tenant_automation_executions "
            "ADD COLUMN IF NOT EXISTS retry_number INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE tenant_automation_executions "
            "ADD COLUMN IF NOT EXISTS error_category VARCHAR(40)",
            "ALTER TABLE tenant_automation_executions "
            "ADD COLUMN IF NOT EXISTS is_retryable BOOLEAN",
        ):
            connection.execute(text(sql))

        connection.execute(text(
            """
            UPDATE tenant_automation_executions SET
              execution_kind = CASE
                WHEN COALESCE((input_payload->>'manual_test')::boolean, false) THEN 'manual'
                ELSE 'event'
              END,
              deduplication_key = CASE
                WHEN COALESCE((input_payload->>'manual_test')::boolean, false)
                  THEN 'manual:' || id::text
                ELSE 'event:' || event_id::text
              END,
              root_execution_id = COALESCE(root_execution_id, id)
            WHERE deduplication_key IS NULL
            """
        ))

        # Resolve duplicate dedup keys before unique index (preserve earliest row).
        dup_groups = connection.execute(text(
            """
            SELECT tenant_id, automation_flow_id, deduplication_key
            FROM tenant_automation_executions
            WHERE deduplication_key IS NOT NULL
            GROUP BY tenant_id, automation_flow_id, deduplication_key
            HAVING COUNT(*) > 1
            """
        )).mappings().all()
        for group in dup_groups:
            rows = connection.execute(
                text(
                    """
                    SELECT id
                    FROM tenant_automation_executions
                    WHERE tenant_id = :tenant_id
                      AND automation_flow_id = :flow_id
                      AND deduplication_key = :dedup_key
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {
                    "tenant_id": group["tenant_id"],
                    "flow_id": group["automation_flow_id"],
                    "dedup_key": group["deduplication_key"],
                },
            ).mappings().all()
            for row in rows[1:]:
                connection.execute(
                    text(
                        """
                        UPDATE tenant_automation_executions
                        SET deduplication_key = 'legacy_duplicate:' || id::text,
                            error_code = COALESCE(error_code, 'duplicate_superseded'),
                            error_category = COALESCE(error_category, 'conflict'),
                            is_retryable = COALESCE(is_retryable, false)
                        WHERE id = :id
                        """
                    ),
                    {"id": row["id"]},
                )

        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_automation_executions_dedup "
            "ON tenant_automation_executions (tenant_id, automation_flow_id, deduplication_key)"
        ))

    # Phase 3 durable scheduler jobs.
    tables = set(inspect(connection).get_table_names())
    if "tenant_automation_jobs" not in tables and "tenant_automation_flows" in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_automation_jobs ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "automation_flow_id UUID NOT NULL REFERENCES tenant_automation_flows(id) ON DELETE CASCADE, "
            "execution_id UUID REFERENCES tenant_automation_executions(id) ON DELETE SET NULL, "
            "root_execution_id UUID REFERENCES tenant_automation_executions(id) ON DELETE SET NULL, "
            "job_kind VARCHAR(40) NOT NULL DEFAULT 'automation_retry', "
            "status VARCHAR(20) NOT NULL DEFAULT 'scheduled', "
            "scheduled_for TIMESTAMPTZ NOT NULL, "
            "available_at TIMESTAMPTZ NOT NULL, "
            "attempt_number INTEGER NOT NULL DEFAULT 1, "
            "max_attempts INTEGER NOT NULL DEFAULT 1, "
            "priority INTEGER NOT NULL DEFAULT 100, "
            "deduplication_key VARCHAR(180) NOT NULL, "
            "lease_owner VARCHAR(120), "
            "lease_expires_at TIMESTAMPTZ, "
            "lease_recovery_count INTEGER NOT NULL DEFAULT 0, "
            "started_at TIMESTAMPTZ, "
            "finished_at TIMESTAMPTZ, "
            "last_heartbeat_at TIMESTAMPTZ, "
            "error_code VARCHAR(60), "
            "error_category VARCHAR(40), "
            "error_message TEXT, "
            "payload JSONB NOT NULL DEFAULT '{}'::jsonb, "
            "result_payload JSONB, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_automation_jobs_dedup UNIQUE (tenant_id, deduplication_key), "
            "CONSTRAINT ck_tenant_automation_jobs_status CHECK ("
            "status IN ('scheduled','leased','running','succeeded','failed','dead_letter','cancelled')"
            "), "
            "CONSTRAINT ck_tenant_automation_jobs_kind CHECK (job_kind IN ('automation_retry'))"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_jobs_claim "
            "ON tenant_automation_jobs (status, available_at, priority)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_jobs_tenant_status_created "
            "ON tenant_automation_jobs (tenant_id, status, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_jobs_lease_expires "
            "ON tenant_automation_jobs (lease_expires_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_jobs_flow_created "
            "ON tenant_automation_jobs (automation_flow_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_jobs_root_created "
            "ON tenant_automation_jobs (root_execution_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_automation_jobs_tenant_id "
            "ON tenant_automation_jobs (tenant_id)",
        ):
            connection.execute(text(sql))

    _ensure_workflow_tables(connection)
    _ensure_intelligence_tables(connection)
    _ensure_publishing_intelligence_tables(connection)
    _ensure_content_optimizer_tables(connection)
    _ensure_governed_ai_tables(connection)
    _ensure_campaign_planner_tables(connection)


def _ensure_workflow_tables(connection) -> None:
    """Workflow Builder Phase 1 — versioned definitions and executions."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "tenants" not in tables:
        return

    if "tenant_workflows" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_workflows ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "key VARCHAR(120) NOT NULL, "
            "name VARCHAR(255) NOT NULL, "
            "description TEXT, "
            "status VARCHAR(20) NOT NULL DEFAULT 'draft', "
            "active_version_id UUID, "
            "draft_version_id UUID, "
            "draft_revision INTEGER NOT NULL DEFAULT 1, "
            "trigger_event VARCHAR(80), "
            "failure_policy VARCHAR(40) NOT NULL DEFAULT 'stop_on_failure', "
            "created_by UUID, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ DEFAULT NOW(), "
            "archived_at TIMESTAMPTZ, "
            "CONSTRAINT uq_tenant_workflows_tenant_key UNIQUE (tenant_id, key)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflows_tenant_id ON tenant_workflows (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflows_tenant_status_updated "
            "ON tenant_workflows (tenant_id, status, updated_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflows_tenant_trigger "
            "ON tenant_workflows (tenant_id, trigger_event)",
        ):
            connection.execute(text(sql))

    if "tenant_workflow_versions" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_workflow_versions ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "workflow_id UUID NOT NULL REFERENCES tenant_workflows(id) ON DELETE CASCADE, "
            "version_number INTEGER NOT NULL, "
            "state VARCHAR(20) NOT NULL DEFAULT 'draft', "
            "definition JSONB NOT NULL DEFAULT '{}'::jsonb, "
            "definition_hash VARCHAR(64), "
            "validation_status VARCHAR(20) NOT NULL DEFAULT 'pending', "
            "validation_errors JSONB, "
            "created_by UUID, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "published_at TIMESTAMPTZ, "
            "CONSTRAINT uq_tenant_workflow_versions_workflow_number "
            "UNIQUE (workflow_id, version_number)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflow_versions_tenant_id "
            "ON tenant_workflow_versions (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflow_versions_workflow_id "
            "ON tenant_workflow_versions (workflow_id)",
        ):
            connection.execute(text(sql))

    # Deferred FKs workflows → versions
    if "tenant_workflows" in set(inspect(connection).get_table_names()) and \
            "tenant_workflow_versions" in set(inspect(connection).get_table_names()):
        connection.execute(text(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tenant_workflows_active_version') THEN "
            "ALTER TABLE tenant_workflows ADD CONSTRAINT fk_tenant_workflows_active_version "
            "FOREIGN KEY (active_version_id) REFERENCES tenant_workflow_versions(id) ON DELETE SET NULL; "
            "END IF; END $$"
        ))
        connection.execute(text(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tenant_workflows_draft_version') THEN "
            "ALTER TABLE tenant_workflows ADD CONSTRAINT fk_tenant_workflows_draft_version "
            "FOREIGN KEY (draft_version_id) REFERENCES tenant_workflow_versions(id) ON DELETE SET NULL; "
            "END IF; END $$"
        ))

    if "tenant_workflow_executions" not in set(inspect(connection).get_table_names()):
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_workflow_executions ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "workflow_id UUID NOT NULL REFERENCES tenant_workflows(id) ON DELETE CASCADE, "
            "workflow_version_id UUID NOT NULL REFERENCES tenant_workflow_versions(id) ON DELETE CASCADE, "
            "platform_event_id UUID, "
            "execution_kind VARCHAR(20) NOT NULL DEFAULT 'event', "
            "deduplication_key VARCHAR(200) NOT NULL, "
            "status VARCHAR(20) NOT NULL DEFAULT 'pending', "
            "trigger_event VARCHAR(80) NOT NULL, "
            "started_at TIMESTAMPTZ NOT NULL, "
            "finished_at TIMESTAMPTZ, "
            "duration_ms INTEGER, "
            "matched_conditions JSONB, "
            "current_step_id VARCHAR(80), "
            "input_summary JSONB, "
            "result_summary JSONB, "
            "error_code VARCHAR(60), "
            "error_category VARCHAR(40), "
            "error_message TEXT, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_workflow_executions_dedup "
            "UNIQUE (tenant_id, workflow_id, deduplication_key)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflow_executions_tenant_id "
            "ON tenant_workflow_executions (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflow_executions_workflow_created "
            "ON tenant_workflow_executions (workflow_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflow_executions_tenant_status_created "
            "ON tenant_workflow_executions (tenant_id, status, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflow_executions_platform_event_id "
            "ON tenant_workflow_executions (platform_event_id)",
        ):
            connection.execute(text(sql))

    if "tenant_workflow_step_executions" not in set(inspect(connection).get_table_names()):
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_workflow_step_executions ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "workflow_execution_id UUID NOT NULL "
            "REFERENCES tenant_workflow_executions(id) ON DELETE CASCADE, "
            "step_id VARCHAR(80) NOT NULL, "
            "step_type VARCHAR(40) NOT NULL, "
            "action_type VARCHAR(60), "
            "step_index INTEGER NOT NULL DEFAULT 0, "
            "status VARCHAR(20) NOT NULL DEFAULT 'pending', "
            "started_at TIMESTAMPTZ, "
            "finished_at TIMESTAMPTZ, "
            "duration_ms INTEGER, "
            "input_summary JSONB, "
            "result_summary JSONB, "
            "error_code VARCHAR(60), "
            "error_category VARCHAR(40), "
            "error_message TEXT, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_workflow_step_executions_exec_step "
            "UNIQUE (workflow_execution_id, step_id)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflow_step_executions_tenant_id "
            "ON tenant_workflow_step_executions (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_workflow_step_executions_execution_id "
            "ON tenant_workflow_step_executions (workflow_execution_id)",
        ):
            connection.execute(text(sql))


def _ensure_intelligence_tables(connection) -> None:
    """Marketing Intelligence Platform — signals, scores, recommendations, history."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "tenants" not in tables:
        return

    if "tenant_marketing_signals" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_marketing_signals ("
            "id UUID PRIMARY KEY, "
            "signal_id UUID NOT NULL, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "signal_type VARCHAR(80) NOT NULL, "
            "entity_type VARCHAR(80), "
            "entity_id VARCHAR(120), "
            "occurred_at TIMESTAMPTZ NOT NULL, "
            "metadata JSONB, "
            "source VARCHAR(40) NOT NULL, "
            "severity VARCHAR(20) NOT NULL DEFAULT 'info', "
            "confidence NUMERIC(4,3) NOT NULL DEFAULT 1.000, "
            "platform_event_id UUID, "
            "platform_event_type VARCHAR(120), "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_marketing_signals_tenant_signal UNIQUE (tenant_id, signal_id)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_signals_tenant_id "
            "ON tenant_marketing_signals (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_signals_tenant_occurred "
            "ON tenant_marketing_signals (tenant_id, occurred_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_signals_tenant_type_occurred "
            "ON tenant_marketing_signals (tenant_id, signal_type, occurred_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_signals_tenant_source "
            "ON tenant_marketing_signals (tenant_id, source)",
        ):
            connection.execute(text(sql))

    if "tenant_marketing_scores" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_marketing_scores ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "category VARCHAR(40) NOT NULL, "
            "score INTEGER NOT NULL DEFAULT 50, "
            "weight NUMERIC(5,4) NOT NULL DEFAULT 0.1000, "
            "scoring_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "explanation JSONB, "
            "evidence JSONB, "
            "computed_at TIMESTAMPTZ DEFAULT NOW(), "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_marketing_scores_tenant_category UNIQUE (tenant_id, category)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_scores_tenant_id "
            "ON tenant_marketing_scores (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_scores_tenant_updated "
            "ON tenant_marketing_scores (tenant_id, updated_at)",
        ):
            connection.execute(text(sql))

    if "tenant_marketing_score_history" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_marketing_score_history ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "category VARCHAR(40) NOT NULL, "
            "score INTEGER NOT NULL, "
            "weight NUMERIC(5,4) NOT NULL, "
            "scoring_version VARCHAR(20) NOT NULL, "
            "explanation JSONB, "
            "evidence JSONB, "
            "recorded_at TIMESTAMPTZ DEFAULT NOW()"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_score_history_tenant_id "
            "ON tenant_marketing_score_history (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_score_history_tenant_category_at "
            "ON tenant_marketing_score_history (tenant_id, category, recorded_at)",
        ):
            connection.execute(text(sql))

    if "tenant_marketing_recommendations" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_marketing_recommendations ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "recommendation_key VARCHAR(120) NOT NULL, "
            "category VARCHAR(40) NOT NULL, "
            "title VARCHAR(255) NOT NULL, "
            "reason TEXT NOT NULL, "
            "evidence JSONB, "
            "explanation JSONB, "
            "confidence NUMERIC(4,3) NOT NULL DEFAULT 0.800, "
            "priority VARCHAR(20) NOT NULL DEFAULT 'medium', "
            "status VARCHAR(20) NOT NULL DEFAULT 'open', "
            "rule_id VARCHAR(80) NOT NULL, "
            "rule_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "action_url VARCHAR(255), "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_marketing_recommendations_tenant_key "
            "UNIQUE (tenant_id, recommendation_key)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_recommendations_tenant_id "
            "ON tenant_marketing_recommendations (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_recommendations_tenant_priority "
            "ON tenant_marketing_recommendations (tenant_id, priority, updated_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_recommendations_tenant_status "
            "ON tenant_marketing_recommendations (tenant_id, status)",
        ):
            connection.execute(text(sql))

    if "tenant_marketing_recommendation_history" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_marketing_recommendation_history ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "recommendation_key VARCHAR(120) NOT NULL, "
            "category VARCHAR(40) NOT NULL, "
            "title VARCHAR(255) NOT NULL, "
            "reason TEXT NOT NULL, "
            "evidence JSONB, "
            "explanation JSONB, "
            "confidence NUMERIC(4,3) NOT NULL, "
            "priority VARCHAR(20) NOT NULL, "
            "status VARCHAR(20) NOT NULL, "
            "rule_id VARCHAR(80) NOT NULL, "
            "rule_version VARCHAR(20) NOT NULL, "
            "recorded_at TIMESTAMPTZ DEFAULT NOW()"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_recommendation_history_tenant_id "
            "ON tenant_marketing_recommendation_history (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_rec_history_tenant_recorded "
            "ON tenant_marketing_recommendation_history (tenant_id, recorded_at)",
        ):
            connection.execute(text(sql))

    if "tenant_marketing_insights" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_marketing_insights ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "kind VARCHAR(40) NOT NULL, "
            "title VARCHAR(255) NOT NULL, "
            "summary TEXT NOT NULL, "
            "category VARCHAR(40), "
            "severity VARCHAR(20) NOT NULL DEFAULT 'info', "
            "explanation JSONB, "
            "evidence JSONB, "
            "related_signal_ids JSONB, "
            "created_at TIMESTAMPTZ DEFAULT NOW()"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_insights_tenant_id "
            "ON tenant_marketing_insights (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_insights_tenant_created "
            "ON tenant_marketing_insights (tenant_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_insights_tenant_kind "
            "ON tenant_marketing_insights (tenant_id, kind)",
        ):
            connection.execute(text(sql))

    if "tenant_marketing_trends" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_marketing_trends ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "metric_key VARCHAR(80) NOT NULL, "
            "bucket_start TIMESTAMPTZ NOT NULL, "
            "bucket_end TIMESTAMPTZ NOT NULL, "
            "value NUMERIC(12,4) NOT NULL, "
            "sample_count INTEGER NOT NULL DEFAULT 0, "
            "metadata JSONB, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_marketing_trends_tenant_metric_bucket "
            "UNIQUE (tenant_id, metric_key, bucket_start)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_trends_tenant_id "
            "ON tenant_marketing_trends (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_trends_tenant_metric_bucket "
            "ON tenant_marketing_trends (tenant_id, metric_key, bucket_start)",
        ):
            connection.execute(text(sql))


async def ensure_intelligence_schema() -> None:
    """Apply idempotent DDL for Marketing Intelligence tables."""
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_intelligence_tables)


def _ensure_publishing_intelligence_tables(connection) -> None:
    """Publishing Intelligence — immutable review snapshots and check results."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "tenants" not in tables or "content_items" not in tables:
        return

    if "tenant_publishing_reviews" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_publishing_reviews ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "content_id UUID NOT NULL REFERENCES content_items(id) ON DELETE CASCADE, "
            "review_version INTEGER NOT NULL, "
            "review_engine_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "content_fingerprint VARCHAR(64) NOT NULL, "
            "overall_score INTEGER NOT NULL DEFAULT 0, "
            "status VARCHAR(20) NOT NULL DEFAULT 'completed', "
            "primary_language VARCHAR(10), "
            "target_platforms JSONB, "
            "summary JSONB, "
            "created_by UUID, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "completed_at TIMESTAMPTZ, "
            "superseded_at TIMESTAMPTZ, "
            "CONSTRAINT uq_tenant_publishing_reviews_content_version "
            "UNIQUE (content_id, review_version)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_reviews_tenant_id "
            "ON tenant_publishing_reviews (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_reviews_content_id "
            "ON tenant_publishing_reviews (content_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_reviews_tenant_content_created "
            "ON tenant_publishing_reviews (tenant_id, content_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_reviews_tenant_status_created "
            "ON tenant_publishing_reviews (tenant_id, status, created_at)",
        ):
            connection.execute(text(sql))

    if "tenant_publishing_review_checks" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_publishing_review_checks ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "publishing_review_id UUID NOT NULL "
            "REFERENCES tenant_publishing_reviews(id) ON DELETE CASCADE, "
            "check_key VARCHAR(80) NOT NULL, "
            "category VARCHAR(40) NOT NULL, "
            "severity VARCHAR(20) NOT NULL DEFAULT 'info', "
            "status VARCHAR(20) NOT NULL, "
            "score INTEGER, "
            "weight INTEGER NOT NULL DEFAULT 1, "
            "evidence JSONB, "
            "recommendation_key VARCHAR(80), "
            "recommendation_params JSONB, "
            "created_at TIMESTAMPTZ DEFAULT NOW()"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_review_checks_tenant_id "
            "ON tenant_publishing_review_checks (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_review_checks_publishing_review_id "
            "ON tenant_publishing_review_checks (publishing_review_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_review_checks_review_category "
            "ON tenant_publishing_review_checks (publishing_review_id, category)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_review_checks_tenant_review "
            "ON tenant_publishing_review_checks (tenant_id, publishing_review_id)",
        ):
            connection.execute(text(sql))

    if "tenant_publishing_platform_reviews" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_publishing_platform_reviews ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "publishing_review_id UUID NOT NULL "
            "REFERENCES tenant_publishing_reviews(id) ON DELETE CASCADE, "
            "platform VARCHAR(40) NOT NULL, "
            "platform_score INTEGER NOT NULL DEFAULT 0, "
            "caption_score INTEGER, "
            "media_score INTEGER, "
            "cta_score INTEGER, "
            "hashtag_score INTEGER, "
            "language_score INTEGER, "
            "compliance_score INTEGER, "
            "recommendations JSONB, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_publishing_platform_reviews_review_platform "
            "UNIQUE (publishing_review_id, platform)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_platform_reviews_tenant_id "
            "ON tenant_publishing_platform_reviews (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_platform_reviews_publishing_review_id "
            "ON tenant_publishing_platform_reviews (publishing_review_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_publishing_platform_reviews_tenant_review "
            "ON tenant_publishing_platform_reviews (tenant_id, publishing_review_id)",
        ):
            connection.execute(text(sql))


async def ensure_publishing_intelligence_schema() -> None:
    """Apply idempotent DDL for Publishing Intelligence tables."""
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_publishing_intelligence_tables)


def _ensure_content_optimizer_tables(connection) -> None:
    """Content Optimizer — deterministic, immutable platform content variants."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "tenants" not in tables or "content_items" not in tables:
        return
    # Variants reference publishing reviews; require that table first.
    if "tenant_publishing_reviews" not in tables:
        return

    if "tenant_content_optimization_runs" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_content_optimization_runs ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "content_id UUID NOT NULL REFERENCES content_items(id) ON DELETE CASCADE, "
            "source_fingerprint VARCHAR(64) NOT NULL, "
            "optimizer_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "policy_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "requested_platforms JSONB, "
            "requested_locales JSONB, "
            "configuration JSONB, "
            "status VARCHAR(20) NOT NULL DEFAULT 'generated', "
            "created_by UUID, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "completed_at TIMESTAMPTZ, "
            "superseded_at TIMESTAMPTZ, "
            "failure_code VARCHAR(80), "
            "failure_metadata JSONB"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_optimization_runs_tenant_id "
            "ON tenant_content_optimization_runs (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_optimization_runs_content_id "
            "ON tenant_content_optimization_runs (content_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_opt_runs_tenant_content_created "
            "ON tenant_content_optimization_runs (tenant_id, content_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_opt_runs_tenant_status_created "
            "ON tenant_content_optimization_runs (tenant_id, status, created_at)",
        ):
            connection.execute(text(sql))

    if "tenant_content_templates" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_content_templates ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "template_type VARCHAR(40) NOT NULL, "
            "name VARCHAR(120) NOT NULL, "
            "locale VARCHAR(10) NOT NULL, "
            "content TEXT NOT NULL, "
            "allowed_platforms JSONB, "
            "is_active BOOLEAN NOT NULL DEFAULT true, "
            "created_by UUID, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ DEFAULT NOW()"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_templates_tenant_id "
            "ON tenant_content_templates (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_templates_tenant_type_locale "
            "ON tenant_content_templates (tenant_id, template_type, locale)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_templates_tenant_active "
            "ON tenant_content_templates (tenant_id, is_active)",
        ):
            connection.execute(text(sql))

    if "tenant_content_variants" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_content_variants ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "optimization_run_id UUID NOT NULL "
            "REFERENCES tenant_content_optimization_runs(id) ON DELETE CASCADE, "
            "content_id UUID NOT NULL REFERENCES content_items(id) ON DELETE CASCADE, "
            "platform VARCHAR(40) NOT NULL, "
            "locale VARCHAR(10) NOT NULL, "
            "length_profile VARCHAR(20) NOT NULL, "
            "variant_version INTEGER NOT NULL DEFAULT 1, "
            "caption TEXT NOT NULL DEFAULT '', "
            "hashtags JSONB, "
            "cta TEXT, "
            "link TEXT, "
            "source_fingerprint VARCHAR(64) NOT NULL, "
            "variant_fingerprint VARCHAR(64) NOT NULL, "
            "status VARCHAR(20) NOT NULL DEFAULT 'generated', "
            "publish_readiness VARCHAR(40), "
            "publishing_review_id UUID "
            "REFERENCES tenant_publishing_reviews(id) ON DELETE SET NULL, "
            "source_score INTEGER, "
            "variant_score INTEGER, "
            "score_delta INTEGER, "
            "category_deltas JSONB, "
            "unsupported_reason VARCHAR(120), "
            "accepted_by UUID, "
            "accepted_at TIMESTAMPTZ, "
            "rejected_by UUID, "
            "rejected_at TIMESTAMPTZ, "
            "applied_by UUID, "
            "applied_at TIMESTAMPTZ, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_content_variants_run_platform_locale_profile "
            "UNIQUE (optimization_run_id, platform, locale, length_profile)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variants_tenant_id "
            "ON tenant_content_variants (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variants_content_id "
            "ON tenant_content_variants (content_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variants_optimization_run_id "
            "ON tenant_content_variants (optimization_run_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variants_publishing_review_id "
            "ON tenant_content_variants (publishing_review_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variants_tenant_content_created "
            "ON tenant_content_variants (tenant_id, content_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variants_tenant_platform_locale_created "
            "ON tenant_content_variants (tenant_id, platform, locale, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variants_run_platform_locale_profile "
            "ON tenant_content_variants (optimization_run_id, platform, locale, length_profile)",
        ):
            connection.execute(text(sql))

    if "tenant_content_variant_transformations" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_content_variant_transformations ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "content_variant_id UUID NOT NULL "
            "REFERENCES tenant_content_variants(id) ON DELETE CASCADE, "
            "sequence INTEGER NOT NULL, "
            "operation_key VARCHAR(80) NOT NULL, "
            "category VARCHAR(40) NOT NULL, "
            "source_excerpt_hash VARCHAR(64), "
            "source_position JSONB, "
            "result_excerpt_hash VARCHAR(64), "
            "reason_key VARCHAR(80) NOT NULL, "
            "reason_params JSONB, "
            "policy_key VARCHAR(80), "
            "policy_version VARCHAR(20), "
            "result_summary VARCHAR(240), "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_content_variant_transformations_variant_seq "
            "UNIQUE (content_variant_id, sequence)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variant_transformations_tenant_id "
            "ON tenant_content_variant_transformations (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variant_transformations_content_variant_id "
            "ON tenant_content_variant_transformations (content_variant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variant_xf_tenant_variant "
            "ON tenant_content_variant_transformations (tenant_id, content_variant_id)",
        ):
            connection.execute(text(sql))


async def ensure_content_optimizer_schema() -> None:
    """Apply idempotent DDL for Content Optimizer tables."""
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_publishing_intelligence_tables)
        await conn.run_sync(_ensure_content_optimizer_tables)


def _ensure_governed_ai_tables(connection) -> None:
    """Governed AI Content Adaptation — policies, requests, generations, brand profiles."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "tenants" not in tables:
        return
    if "tenant_content_optimization_runs" not in tables or "tenant_content_variants" not in tables:
        return

    if "tenant_ai_policies" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_ai_policies ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "is_enabled BOOLEAN NOT NULL DEFAULT false, "
            "allowed_task_types JSONB, "
            "allowed_locales JSONB, "
            "allowed_platforms JSONB, "
            "allow_provider_processing BOOLEAN NOT NULL DEFAULT true, "
            "allow_fallback_provider BOOLEAN NOT NULL DEFAULT false, "
            "store_redacted_inputs BOOLEAN NOT NULL DEFAULT true, "
            "store_redacted_outputs BOOLEAN NOT NULL DEFAULT true, "
            "hourly_request_limit INTEGER, "
            "daily_token_limit INTEGER, "
            "monthly_cost_limit_minor INTEGER, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_ai_policies_tenant UNIQUE (tenant_id)"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_ai_policies_tenant_id "
            "ON tenant_ai_policies (tenant_id)"
        ))

    if "tenant_ai_requests" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_ai_requests ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "task_type VARCHAR(80) NOT NULL, "
            "entity_type VARCHAR(40) NOT NULL DEFAULT 'content', "
            "entity_id UUID NOT NULL, "
            "request_status VARCHAR(40) NOT NULL DEFAULT 'queued', "
            "model_alias VARCHAR(40) NOT NULL, "
            "resolved_provider VARCHAR(40), "
            "resolved_model VARCHAR(80), "
            "routing_version VARCHAR(20), "
            "prompt_key VARCHAR(120) NOT NULL, "
            "prompt_version VARCHAR(20) NOT NULL, "
            "input_fingerprint VARCHAR(64) NOT NULL, "
            "idempotency_key VARCHAR(128) NOT NULL, "
            "brand_profile_version_id UUID, "
            "optimization_run_id UUID REFERENCES tenant_content_optimization_runs(id) ON DELETE SET NULL, "
            "configuration JSONB, "
            "requested_by UUID, "
            "requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "started_at TIMESTAMPTZ, "
            "completed_at TIMESTAMPTZ, "
            "failure_code VARCHAR(80), "
            "failure_metadata JSONB, "
            "CONSTRAINT uq_tenant_ai_requests_tenant_idempotency "
            "UNIQUE (tenant_id, idempotency_key)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_ai_requests_tenant_id ON tenant_ai_requests (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_ai_requests_entity_id ON tenant_ai_requests (entity_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_ai_requests_tenant_content_created "
            "ON tenant_ai_requests (tenant_id, entity_id, requested_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_ai_requests_tenant_status_requested "
            "ON tenant_ai_requests (tenant_id, request_status, requested_at)",
        ):
            connection.execute(text(sql))

    if "tenant_ai_generations" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_ai_generations ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "ai_request_id UUID NOT NULL REFERENCES tenant_ai_requests(id) ON DELETE CASCADE, "
            "generation_version INTEGER NOT NULL DEFAULT 1, "
            "platform VARCHAR(40), "
            "locale VARCHAR(10), "
            "length_profile VARCHAR(20), "
            "structured_output JSONB, "
            "redacted_input_snapshot JSONB, "
            "redacted_output_snapshot JSONB, "
            "output_fingerprint VARCHAR(64), "
            "input_tokens INTEGER NOT NULL DEFAULT 0, "
            "output_tokens INTEGER NOT NULL DEFAULT 0, "
            "total_tokens INTEGER NOT NULL DEFAULT 0, "
            "estimated_cost_minor INTEGER NOT NULL DEFAULT 0, "
            "currency VARCHAR(8) NOT NULL DEFAULT 'USD', "
            "latency_ms INTEGER, "
            "finish_reason VARCHAR(40), "
            "validation_status VARCHAR(40) NOT NULL DEFAULT 'pending', "
            "safety_status VARCHAR(40) NOT NULL DEFAULT 'pending', "
            "factual_validation JSONB, "
            "protected_fact_summary JSONB, "
            "content_variant_id UUID REFERENCES tenant_content_variants(id) ON DELETE SET NULL, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_ai_generations_request_version "
            "UNIQUE (ai_request_id, generation_version)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_ai_generations_tenant_id ON tenant_ai_generations (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_ai_generations_ai_request_id "
            "ON tenant_ai_generations (ai_request_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_ai_generations_tenant_request "
            "ON tenant_ai_generations (tenant_id, ai_request_id)",
        ):
            connection.execute(text(sql))

    if "tenant_ai_usage_daily" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_ai_usage_daily ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "usage_date DATE NOT NULL, "
            "provider VARCHAR(40) NOT NULL, "
            "model VARCHAR(80) NOT NULL, "
            "task_type VARCHAR(80) NOT NULL, "
            "request_count INTEGER NOT NULL DEFAULT 0, "
            "successful_request_count INTEGER NOT NULL DEFAULT 0, "
            "failed_request_count INTEGER NOT NULL DEFAULT 0, "
            "input_tokens INTEGER NOT NULL DEFAULT 0, "
            "output_tokens INTEGER NOT NULL DEFAULT 0, "
            "total_tokens INTEGER NOT NULL DEFAULT 0, "
            "estimated_cost_minor INTEGER NOT NULL DEFAULT 0, "
            "currency VARCHAR(8) NOT NULL DEFAULT 'USD', "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_ai_usage_daily_dims "
            "UNIQUE (tenant_id, usage_date, provider, model, task_type)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_ai_usage_daily_tenant_id ON tenant_ai_usage_daily (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_ai_usage_daily_tenant_date "
            "ON tenant_ai_usage_daily (tenant_id, usage_date)",
        ):
            connection.execute(text(sql))

    if "tenant_brand_profiles" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_brand_profiles ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "name VARCHAR(160) NOT NULL, "
            "status VARCHAR(20) NOT NULL DEFAULT 'draft', "
            "current_version_id UUID, "
            "draft_payload JSONB, "
            "draft_version INTEGER NOT NULL DEFAULT 0, "
            "created_by UUID, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_brand_profiles_tenant_id ON tenant_brand_profiles (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_brand_profiles_tenant_status "
            "ON tenant_brand_profiles (tenant_id, status)",
        ):
            connection.execute(text(sql))

    if "tenant_brand_profile_versions" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_brand_profile_versions ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "brand_profile_id UUID NOT NULL REFERENCES tenant_brand_profiles(id) ON DELETE CASCADE, "
            "version INTEGER NOT NULL, "
            "locale VARCHAR(10) NOT NULL DEFAULT 'en', "
            "company_name VARCHAR(200) NOT NULL DEFAULT '', "
            "company_description TEXT NOT NULL DEFAULT '', "
            "audience_description TEXT NOT NULL DEFAULT '', "
            "tone_traits JSONB, "
            "preferred_terms JSONB, "
            "forbidden_terms JSONB, "
            "approved_claims JSONB, "
            "prohibited_claims JSONB, "
            "cta_preferences JSONB, "
            "emoji_policy JSONB, "
            "formatting_preferences JSONB, "
            "platform_guidance JSONB, "
            "source_references JSONB, "
            "created_by UUID, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_brand_profile_versions_profile_version "
            "UNIQUE (brand_profile_id, version)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_brand_profile_versions_tenant_id "
            "ON tenant_brand_profile_versions (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_brand_profile_versions_brand_profile_id "
            "ON tenant_brand_profile_versions (brand_profile_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_brand_profile_versions_tenant_profile "
            "ON tenant_brand_profile_versions (tenant_id, brand_profile_id)",
        ):
            connection.execute(text(sql))

    # AI columns on content variants (idempotent)
    if "tenant_content_variants" in tables:
        for sql in (
            "ALTER TABLE tenant_content_variants "
            "ADD COLUMN IF NOT EXISTS generation_method VARCHAR(40) NOT NULL DEFAULT 'deterministic'",
            "ALTER TABLE tenant_content_variants ADD COLUMN IF NOT EXISTS ai_request_id UUID",
            "ALTER TABLE tenant_content_variants ADD COLUMN IF NOT EXISTS ai_generation_id UUID",
            "ALTER TABLE tenant_content_variants ADD COLUMN IF NOT EXISTS brand_profile_version_id UUID",
            "ALTER TABLE tenant_content_variants ADD COLUMN IF NOT EXISTS prompt_key VARCHAR(120)",
            "ALTER TABLE tenant_content_variants ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(20)",
            "ALTER TABLE tenant_content_variants ADD COLUMN IF NOT EXISTS model_alias VARCHAR(40)",
            "ALTER TABLE tenant_content_variants ADD COLUMN IF NOT EXISTS resolved_provider VARCHAR(40)",
            "ALTER TABLE tenant_content_variants ADD COLUMN IF NOT EXISTS resolved_model VARCHAR(80)",
            "ALTER TABLE tenant_content_variants ADD COLUMN IF NOT EXISTS factual_validation_status VARCHAR(40)",
            "ALTER TABLE tenant_content_variants ADD COLUMN IF NOT EXISTS safety_validation_status VARCHAR(40)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variants_ai_request_id "
            "ON tenant_content_variants (ai_request_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_variants_ai_generation_id "
            "ON tenant_content_variants (ai_generation_id)",
        ):
            connection.execute(text(sql))


async def ensure_governed_ai_schema() -> None:
    """Apply idempotent DDL for Governed AI Content Adaptation tables/columns."""
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_publishing_intelligence_tables)
        await conn.run_sync(_ensure_content_optimizer_tables)
        await conn.run_sync(_ensure_governed_ai_tables)


def _ensure_campaign_planner_tables(connection) -> None:
    """Smart Publishing Phase 3 — Campaign Planner tenant-scoped tables."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "tenants" not in tables:
        return

    if "tenant_marketing_campaigns" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_marketing_campaigns ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "name VARCHAR(200) NOT NULL, "
            "description TEXT, "
            "status VARCHAR(20) NOT NULL DEFAULT 'draft', "
            "objective VARCHAR(120), "
            "timezone VARCHAR(64) NOT NULL DEFAULT 'UTC', "
            "primary_locale VARCHAR(10) NOT NULL DEFAULT 'en', "
            "locales JSONB, "
            "platforms JSONB, "
            "start_date DATE, "
            "end_date DATE, "
            "blackout_dates JSONB, "
            "cadence JSONB, "
            "brand_profile_id UUID, "
            "brand_profile_version_id UUID, "
            "current_plan_version_id UUID, "
            "published_plan_version_id UUID, "
            "planner_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "policy_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "metadata_json JSONB, "
            "created_by UUID, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "archived_at TIMESTAMPTZ"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_campaigns_tenant_id ON tenant_marketing_campaigns (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_campaigns_tenant_status ON tenant_marketing_campaigns (tenant_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_marketing_campaigns_tenant_created ON tenant_marketing_campaigns (tenant_id, created_at)",
        ):
            connection.execute(text(sql))

    if "tenant_campaign_goals" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_goals ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "goal_type VARCHAR(40) NOT NULL DEFAULT 'other', "
            "title VARCHAR(200) NOT NULL, "
            "description TEXT, "
            "priority VARCHAR(20) NOT NULL DEFAULT 'medium', "
            "target_metric VARCHAR(120), "
            "sort_order INTEGER NOT NULL DEFAULT 0, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_goals_tenant_campaign "
            "ON tenant_campaign_goals (tenant_id, campaign_id)"
        ))

    if "tenant_campaign_kpis" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_kpis ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "name VARCHAR(200) NOT NULL, "
            "metric_key VARCHAR(120) NOT NULL, "
            "target_value NUMERIC(18,4), "
            "unit VARCHAR(40), "
            "comparator VARCHAR(10) NOT NULL DEFAULT '>=', "
            "timeframe VARCHAR(40), "
            "sort_order INTEGER NOT NULL DEFAULT 0, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_kpis_tenant_campaign "
            "ON tenant_campaign_kpis (tenant_id, campaign_id)"
        ))

    if "tenant_campaign_audiences" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_audiences ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "name VARCHAR(200) NOT NULL, "
            "description TEXT, "
            "locale VARCHAR(10), "
            "platforms JSONB, "
            "segment JSONB, "
            "sort_order INTEGER NOT NULL DEFAULT 0, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_audiences_tenant_campaign "
            "ON tenant_campaign_audiences (tenant_id, campaign_id)"
        ))

    if "tenant_content_pillars" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_content_pillars ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "name VARCHAR(160) NOT NULL, "
            "slug VARCHAR(160) NOT NULL, "
            "description TEXT, "
            "color VARCHAR(20), "
            "default_weight INTEGER NOT NULL DEFAULT 1, "
            "is_active BOOLEAN NOT NULL DEFAULT true, "
            "created_by UUID, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_content_pillars_tenant_slug UNIQUE (tenant_id, slug)"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_content_pillars_tenant_active "
            "ON tenant_content_pillars (tenant_id, is_active)"
        ))

    if "tenant_campaign_pillars" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_pillars ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "pillar_id UUID NOT NULL REFERENCES tenant_content_pillars(id) ON DELETE CASCADE, "
            "weight INTEGER NOT NULL DEFAULT 1, "
            "sort_order INTEGER NOT NULL DEFAULT 0, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_campaign_pillars_campaign_pillar UNIQUE (campaign_id, pillar_id)"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_pillars_tenant_campaign "
            "ON tenant_campaign_pillars (tenant_id, campaign_id)"
        ))

    if "tenant_campaign_phases" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_phases ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "name VARCHAR(160) NOT NULL, "
            "phase_type VARCHAR(40) NOT NULL DEFAULT 'custom', "
            "description TEXT, "
            "start_date DATE, "
            "end_date DATE, "
            "weight INTEGER NOT NULL DEFAULT 1, "
            "sort_order INTEGER NOT NULL DEFAULT 0, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_phases_tenant_campaign "
            "ON tenant_campaign_phases (tenant_id, campaign_id)"
        ))

    if "tenant_campaign_plan_versions" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_plan_versions ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "version INTEGER NOT NULL, "
            "status VARCHAR(20) NOT NULL DEFAULT 'draft', "
            "generation_method VARCHAR(40) NOT NULL DEFAULT 'deterministic', "
            "plan_fingerprint VARCHAR(64) NOT NULL, "
            "planner_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "policy_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "parameters JSONB, "
            "summary JSONB, "
            "notes TEXT, "
            "source_ai_request_id UUID, "
            "parent_version_id UUID, "
            "slot_count INTEGER NOT NULL DEFAULT 0, "
            "created_by UUID, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "reviewed_at TIMESTAMPTZ, "
            "published_at TIMESTAMPTZ, "
            "superseded_at TIMESTAMPTZ, "
            "CONSTRAINT uq_tenant_campaign_plan_versions_campaign_version UNIQUE (campaign_id, version)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_plan_versions_tenant_campaign "
            "ON tenant_campaign_plan_versions (tenant_id, campaign_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_plan_versions_tenant_status "
            "ON tenant_campaign_plan_versions (tenant_id, status)",
        ):
            connection.execute(text(sql))

    if "tenant_campaign_calendar_slots" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_calendar_slots ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "plan_version_id UUID NOT NULL REFERENCES tenant_campaign_plan_versions(id) ON DELETE CASCADE, "
            "slot_index INTEGER NOT NULL DEFAULT 0, "
            "platform VARCHAR(40) NOT NULL, "
            "locale VARCHAR(10) NOT NULL DEFAULT 'en', "
            "pillar_id UUID, "
            "phase_id UUID, "
            "scheduled_date DATE NOT NULL, "
            "scheduled_time TIME NOT NULL, "
            "suggested_time_label VARCHAR(80), "
            "status VARCHAR(20) NOT NULL DEFAULT 'unassigned', "
            "slot_fingerprint VARCHAR(64) NOT NULL, "
            "notes TEXT, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_calendar_slots_tenant_plan "
            "ON tenant_campaign_calendar_slots (tenant_id, plan_version_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_calendar_slots_plan_date "
            "ON tenant_campaign_calendar_slots (plan_version_id, scheduled_date)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_calendar_slots_plan_platform_dt "
            "ON tenant_campaign_calendar_slots (plan_version_id, platform, scheduled_date, scheduled_time)",
        ):
            connection.execute(text(sql))

    if "tenant_campaign_slot_assignments" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_slot_assignments ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "plan_version_id UUID NOT NULL REFERENCES tenant_campaign_plan_versions(id) ON DELETE CASCADE, "
            "slot_id UUID NOT NULL REFERENCES tenant_campaign_calendar_slots(id) ON DELETE CASCADE, "
            "content_id UUID REFERENCES content_items(id) ON DELETE SET NULL, "
            "content_variant_id UUID, "
            "assignment_type VARCHAR(40) NOT NULL DEFAULT 'content', "
            "assigned_platform VARCHAR(40), "
            "assigned_locale VARCHAR(10), "
            "assignment_status VARCHAR(40) NOT NULL DEFAULT 'assigned', "
            "readiness_status VARCHAR(40) NOT NULL DEFAULT 'unknown', "
            "readiness_score INTEGER, "
            "publishing_review_id UUID, "
            "warnings JSONB, "
            "assigned_by UUID, "
            "assigned_at TIMESTAMPTZ, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_campaign_slot_assignments_slot UNIQUE (slot_id)"
            ")"
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_slot_assignments_tenant_campaign "
            "ON tenant_campaign_slot_assignments (tenant_id, campaign_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_slot_assignments_tenant_content "
            "ON tenant_campaign_slot_assignments (tenant_id, content_id)",
        ):
            connection.execute(text(sql))
    else:
        # Idempotent column add for assignment_type if upgrading older ensure.
        connection.execute(text(
            "ALTER TABLE tenant_campaign_slot_assignments "
            "ADD COLUMN IF NOT EXISTS assignment_type VARCHAR(40) NOT NULL DEFAULT 'content'"
        ))

    if "tenant_campaign_reviews" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_reviews ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "plan_version_id UUID REFERENCES tenant_campaign_plan_versions(id) ON DELETE CASCADE, "
            "review_type VARCHAR(20) NOT NULL DEFAULT 'plan', "
            "coverage_score INTEGER, "
            "readiness_score INTEGER, "
            "total_slots INTEGER NOT NULL DEFAULT 0, "
            "assigned_slots INTEGER NOT NULL DEFAULT 0, "
            "blocked_slots INTEGER NOT NULL DEFAULT 0, "
            "unassigned_slots INTEGER NOT NULL DEFAULT 0, "
            "conflict_count INTEGER NOT NULL DEFAULT 0, "
            "gap_count INTEGER NOT NULL DEFAULT 0, "
            "summary JSONB, "
            "engine_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "created_by UUID, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_reviews_tenant_campaign "
            "ON tenant_campaign_reviews (tenant_id, campaign_id)"
        ))

    if "tenant_campaign_gaps" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_gaps ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "plan_version_id UUID REFERENCES tenant_campaign_plan_versions(id) ON DELETE CASCADE, "
            "review_id UUID REFERENCES tenant_campaign_reviews(id) ON DELETE CASCADE, "
            "gap_type VARCHAR(40) NOT NULL, "
            "severity VARCHAR(20) NOT NULL DEFAULT 'medium', "
            "dimension VARCHAR(40), "
            "dimension_value VARCHAR(120), "
            "detail JSONB, "
            "status VARCHAR(20) NOT NULL DEFAULT 'open', "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_gaps_tenant_campaign "
            "ON tenant_campaign_gaps (tenant_id, campaign_id)"
        ))

    if "tenant_campaign_recommendations" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_campaign_recommendations ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "campaign_id UUID NOT NULL REFERENCES tenant_marketing_campaigns(id) ON DELETE CASCADE, "
            "plan_version_id UUID, "
            "recommendation_key VARCHAR(120) NOT NULL, "
            "category VARCHAR(40) NOT NULL DEFAULT 'campaign', "
            "title VARCHAR(200) NOT NULL, "
            "reason TEXT NOT NULL, "
            "evidence JSONB, "
            "priority VARCHAR(20) NOT NULL DEFAULT 'medium', "
            "rule_id VARCHAR(120) NOT NULL, "
            "rule_version VARCHAR(20) NOT NULL DEFAULT '1.0.0', "
            "status VARCHAR(20) NOT NULL DEFAULT 'open', "
            "action_url VARCHAR(200), "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "CONSTRAINT uq_tenant_campaign_recommendations_key "
            "UNIQUE (tenant_id, campaign_id, recommendation_key)"
            ")"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_campaign_recommendations_tenant_campaign "
            "ON tenant_campaign_recommendations (tenant_id, campaign_id)"
        ))


async def ensure_campaign_planner_schema() -> None:
    """Apply idempotent DDL for Campaign Planner tables."""
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_campaign_planner_tables)


def _ensure_customer_success_journey_columns(connection) -> None:
    """Customer Success Journey — post-platform-ready adoption engine."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())

    if "tenant_onboarding_progress" in tables:
        for sql in (
            "ALTER TABLE tenant_onboarding_progress "
            "ADD COLUMN IF NOT EXISTS north_star_goal VARCHAR(40)",
            "ALTER TABLE tenant_onboarding_progress "
            "ADD COLUMN IF NOT EXISTS platform_ready_at TIMESTAMPTZ",
        ):
            connection.execute(text(sql))

    if "tenant_customer_success_journey" not in tables:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tenant_customer_success_journey ("
            "id UUID PRIMARY KEY, "
            "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
            "status VARCHAR(20) NOT NULL DEFAULT 'not_started', "
            "started_at TIMESTAMPTZ, "
            "completed_at TIMESTAMPTZ, "
            "current_checkpoint VARCHAR(20), "
            "milestones_achieved JSONB, "
            "timeline_entries JSONB, "
            "weekly_wins JSONB, "
            "dismissed_recommendations JSONB, "
            "last_refreshed_at TIMESTAMPTZ, "
            "created_at TIMESTAMPTZ DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ DEFAULT NOW()"
            ")"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_tenant_customer_success_journey_tenant_id "
            "ON tenant_customer_success_journey (tenant_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tenant_customer_success_journey_status "
            "ON tenant_customer_success_journey (status)"
        ))


def _ensure_tenant_onboarding_v2_columns(connection) -> None:
    """Customer onboarding v2 — dual readiness metrics and walkthrough state."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "tenant_onboarding_progress" not in inspector.get_table_names():
        return
    for sql in (
        "ALTER TABLE tenant_onboarding_progress "
        "ADD COLUMN IF NOT EXISTS platform_readiness_percent INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tenant_onboarding_progress "
        "ADD COLUMN IF NOT EXISTS business_readiness_percent INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tenant_onboarding_progress "
        "ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ",
        "ALTER TABLE tenant_onboarding_progress "
        "ADD COLUMN IF NOT EXISTS executive_walkthrough_progress JSONB",
        "ALTER TABLE tenant_onboarding_progress "
        "ADD COLUMN IF NOT EXISTS first_success_state JSONB",
        "ALTER TABLE tenant_onboarding_progress "
        "ADD COLUMN IF NOT EXISTS auto_config_applied BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE tenant_onboarding_progress "
        "ADD COLUMN IF NOT EXISTS auto_config_applied_at TIMESTAMPTZ",
        "ALTER TABLE tenant_onboarding_progress "
        "ADD COLUMN IF NOT EXISTS onboarding_version INTEGER NOT NULL DEFAULT 2",
    ):
        connection.execute(text(sql))


def _ensure_executive_crm_pipeline_columns(connection) -> None:
    """Executive CRM pipeline — 12-stage lifecycle, timeline events, commercial links."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())

    if "sales_customers" in tables:
        for sql in (
            "ALTER TABLE sales_customers ADD COLUMN IF NOT EXISTS client_id UUID "
            "REFERENCES clients(id) ON DELETE SET NULL",
            "ALTER TABLE sales_customers ADD COLUMN IF NOT EXISTS owner_id UUID "
            "REFERENCES tenant_users(id) ON DELETE SET NULL",
            "ALTER TABLE sales_customers ADD COLUMN IF NOT EXISTS primary_publishing_account_id UUID "
            "REFERENCES publishing_accounts(id) ON DELETE SET NULL",
            "CREATE INDEX IF NOT EXISTS ix_sales_customers_client_id ON sales_customers (client_id)",
            "CREATE INDEX IF NOT EXISTS ix_sales_customers_owner_id ON sales_customers (owner_id)",
            "CREATE INDEX IF NOT EXISTS ix_sales_customers_primary_publishing_account_id "
            "ON sales_customers (primary_publishing_account_id)",
        ):
            connection.execute(text(sql))

    if "sales_deals" in tables:
        for sql in (
            "ALTER TABLE sales_deals ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ",
            "ALTER TABLE sales_deals ADD COLUMN IF NOT EXISTS owner_id UUID "
            "REFERENCES tenant_users(id) ON DELETE SET NULL",
            "ALTER TABLE sales_deals ADD COLUMN IF NOT EXISTS stage_source VARCHAR(20) "
            "NOT NULL DEFAULT 'manual'",
            "ALTER TABLE sales_deals ADD COLUMN IF NOT EXISTS stage_override BOOLEAN "
            "NOT NULL DEFAULT false",
            "CREATE INDEX IF NOT EXISTS ix_sales_deals_owner_id ON sales_deals (owner_id)",
        ):
            connection.execute(text(sql))
        connection.execute(text(
            "UPDATE sales_deals SET stage = 'lead' WHERE stage = 'new_lead'"
        ))
        connection.execute(text(
            "UPDATE sales_deals SET stage = 'closed_won' WHERE stage = 'won'"
        ))
        connection.execute(text(
            "UPDATE sales_deals SET stage = 'closed_lost' WHERE stage = 'lost'"
        ))

    if "sales_proposals" in tables:
        for sql in (
            "ALTER TABLE sales_proposals ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE sales_proposals ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ",
            "ALTER TABLE sales_proposals ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ",
            "ALTER TABLE sales_proposals ADD COLUMN IF NOT EXISTS attachment_url VARCHAR(1024)",
        ):
            connection.execute(text(sql))

    if "crm_pipeline_events" not in tables:
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS crm_pipeline_events (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                event_type VARCHAR(40) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                payload JSONB,
                customer_id UUID REFERENCES sales_customers(id) ON DELETE SET NULL,
                lead_id UUID REFERENCES sales_leads(id) ON DELETE SET NULL,
                deal_id UUID REFERENCES sales_deals(id) ON DELETE SET NULL,
                actor VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        ))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_crm_pipeline_events_tenant_id "
            "ON crm_pipeline_events (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_crm_pipeline_events_event_type "
            "ON crm_pipeline_events (event_type)",
            "CREATE INDEX IF NOT EXISTS ix_crm_pipeline_events_customer_id "
            "ON crm_pipeline_events (customer_id)",
            "CREATE INDEX IF NOT EXISTS ix_crm_pipeline_events_lead_id "
            "ON crm_pipeline_events (lead_id)",
            "CREATE INDEX IF NOT EXISTS ix_crm_pipeline_events_deal_id "
            "ON crm_pipeline_events (deal_id)",
            "CREATE INDEX IF NOT EXISTS ix_crm_pipeline_events_created_at "
            "ON crm_pipeline_events (created_at)",
        ):
            connection.execute(text(sql))


def _ensure_meta_publishing_columns(connection) -> None:
    """Meta Graph API publishing foundation columns on publishing_accounts."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "publishing_accounts" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("publishing_accounts")}
    for column, sql in [
        ("refresh_token_encrypted", "ALTER TABLE publishing_accounts ADD COLUMN IF NOT EXISTS refresh_token_encrypted TEXT"),
        ("expires_at", "ALTER TABLE publishing_accounts ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"),
        ("facebook_page_id", "ALTER TABLE publishing_accounts ADD COLUMN IF NOT EXISTS facebook_page_id VARCHAR(64)"),
        ("instagram_business_account_id", "ALTER TABLE publishing_accounts ADD COLUMN IF NOT EXISTS instagram_business_account_id VARCHAR(64)"),
        ("permissions_json", "ALTER TABLE publishing_accounts ADD COLUMN IF NOT EXISTS permissions_json TEXT"),
        ("account_metadata_json", "ALTER TABLE publishing_accounts ADD COLUMN IF NOT EXISTS account_metadata_json TEXT"),
    ]:
        if column not in existing:
            connection.execute(text(sql))
    connection.execute(text(
        "ALTER TABLE publishing_accounts ALTER COLUMN status TYPE VARCHAR(30)"
    ))


def _ensure_publishing_accounts_tenant_id(connection) -> None:
    """Tenant ownership column on publishing_accounts."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "publishing_accounts" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("publishing_accounts")}
    if "tenant_id" not in existing:
        connection.execute(text(
            "ALTER TABLE publishing_accounts ADD COLUMN IF NOT EXISTS tenant_id UUID"
        ))
        connection.execute(text(
            """
            UPDATE publishing_accounts
            SET tenant_id = (
                SELECT tu.tenant_id
                FROM tenant_users tu
                WHERE lower(tu.email) = 'demo@factory.local'
                LIMIT 1
            )
            WHERE tenant_id IS NULL
            """
        ))
        connection.execute(text(
            """
            UPDATE publishing_accounts
            SET tenant_id = (
                SELECT t.id FROM tenants t ORDER BY t.created_at ASC LIMIT 1
            )
            WHERE tenant_id IS NULL
            """
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_publishing_accounts_tenant_id "
            "ON publishing_accounts (tenant_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_publishing_accounts_tenant_platform "
            "ON publishing_accounts (tenant_id, platform)"
        ))


def _ensure_telegram_ingestion_columns(connection) -> None:
    """Telegram ingestion enrichment columns on content_items."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "content_items" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("content_items")}
    for column, sql in [
        ("telegram_original_caption", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS telegram_original_caption TEXT"),
        ("content_classification", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS content_classification VARCHAR(50)"),
        ("suggestions_json", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS suggestions_json TEXT"),
        ("quality_warnings_json", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS quality_warnings_json TEXT"),
        ("telegram_media_group_id", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS telegram_media_group_id VARCHAR(50)"),
        ("telegram_forward_from", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS telegram_forward_from VARCHAR(255)"),
    ]:
        if column not in existing:
            connection.execute(text(sql))


def _ensure_content_factory_ai_columns(connection) -> None:
    """Content Factory AI pipeline columns (factories + items)."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "content_factories" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("content_factories")}
        for column, sql in [
            ("input_type", "ALTER TABLE content_factories ADD COLUMN IF NOT EXISTS input_type VARCHAR(20) DEFAULT 'image'"),
            ("input_text", "ALTER TABLE content_factories ADD COLUMN IF NOT EXISTS input_text TEXT"),
            ("content_category", "ALTER TABLE content_factories ADD COLUMN IF NOT EXISTS content_category VARCHAR(50)"),
            ("target_languages_json", "ALTER TABLE content_factories ADD COLUMN IF NOT EXISTS target_languages_json TEXT"),
            ("metadata_json", "ALTER TABLE content_factories ADD COLUMN IF NOT EXISTS metadata_json TEXT"),
        ]:
            if column not in existing:
                connection.execute(text(sql))
    if "content_factory_items" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("content_factory_items")}
        for column, sql in [
            ("review_status", "ALTER TABLE content_factory_items ADD COLUMN IF NOT EXISTS review_status VARCHAR(30) DEFAULT 'generated'"),
            ("headline", "ALTER TABLE content_factory_items ADD COLUMN IF NOT EXISTS headline VARCHAR(500)"),
            ("cta_suggestion", "ALTER TABLE content_factory_items ADD COLUMN IF NOT EXISTS cta_suggestion TEXT"),
            ("quality_scores_json", "ALTER TABLE content_factory_items ADD COLUMN IF NOT EXISTS quality_scores_json TEXT"),
            ("platform_variants_json", "ALTER TABLE content_factory_items ADD COLUMN IF NOT EXISTS platform_variants_json TEXT"),
            ("scheduled_for", "ALTER TABLE content_factory_items ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ"),
        ]:
            if column not in existing:
                connection.execute(text(sql))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_content_factory_items_review_status "
            "ON content_factory_items (review_status)"
        ))
        connection.execute(text(
            "ALTER TABLE content_factories ALTER COLUMN source_media_id DROP NOT NULL"
        ))


def _ensure_whatsapp_business_foundation_columns(connection) -> None:
    """WhatsApp Business Integration — tenant accounts, contact city."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "whatsapp_sync_accounts" in inspector.get_table_names():
        for sql in (
            "ALTER TABLE whatsapp_sync_accounts ADD COLUMN IF NOT EXISTS tenant_id UUID "
            "REFERENCES tenants(id) ON DELETE CASCADE",
            "ALTER TABLE whatsapp_sync_accounts ADD COLUMN IF NOT EXISTS connected_at TIMESTAMPTZ",
            "ALTER TABLE whatsapp_sync_accounts ADD COLUMN IF NOT EXISTS business_display_name VARCHAR(255)",
            "CREATE INDEX IF NOT EXISTS ix_whatsapp_sync_accounts_tenant_id "
            "ON whatsapp_sync_accounts (tenant_id)",
        ):
            connection.execute(text(sql))
    if "communication_contacts" in inspector.get_table_names():
        connection.execute(text(
            "ALTER TABLE communication_contacts ADD COLUMN IF NOT EXISTS city VARCHAR(100)"
        ))


def _ensure_wechat_business_foundation_columns(connection) -> None:
    """WeChat Business Integration — tenant accounts, contact CRM fields."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "wechat_sync_accounts" in inspector.get_table_names():
        for sql in (
            "ALTER TABLE wechat_sync_accounts ADD COLUMN IF NOT EXISTS tenant_id UUID "
            "REFERENCES tenants(id) ON DELETE CASCADE",
            "ALTER TABLE wechat_sync_accounts ADD COLUMN IF NOT EXISTS connected_at TIMESTAMPTZ",
            "CREATE INDEX IF NOT EXISTS ix_wechat_sync_accounts_tenant_id "
            "ON wechat_sync_accounts (tenant_id)",
        ):
            connection.execute(text(sql))
    if "communication_contacts" in inspector.get_table_names():
        for sql in (
            "ALTER TABLE communication_contacts ADD COLUMN IF NOT EXISTS buyer_id UUID "
            "REFERENCES buyers(id) ON DELETE SET NULL",
            "ALTER TABLE communication_contacts ADD COLUMN IF NOT EXISTS customer_id UUID "
            "REFERENCES sales_customers(id) ON DELETE SET NULL",
            "ALTER TABLE communication_contacts ADD COLUMN IF NOT EXISTS industry VARCHAR(100)",
            "ALTER TABLE communication_contacts ADD COLUMN IF NOT EXISTS tags_json JSONB",
            "CREATE INDEX IF NOT EXISTS ix_communication_contacts_buyer_id "
            "ON communication_contacts (buyer_id)",
            "CREATE INDEX IF NOT EXISTS ix_communication_contacts_customer_id "
            "ON communication_contacts (customer_id)",
        ):
            connection.execute(text(sql))


def _ensure_client_briefs_columns(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "client_briefs" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("client_briefs")}
    for column, sql in [
        ("product_description", "ALTER TABLE client_briefs ADD COLUMN IF NOT EXISTS product_description TEXT"),
        ("languages", "ALTER TABLE client_briefs ADD COLUMN IF NOT EXISTS languages JSON"),
        ("notes", "ALTER TABLE client_briefs ADD COLUMN IF NOT EXISTS notes TEXT"),
        ("admin_feedback", "ALTER TABLE client_briefs ADD COLUMN IF NOT EXISTS admin_feedback TEXT"),
    ]:
        if column not in existing:
            connection.execute(text(sql))


def _ensure_factory_platform_v2_management_columns(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "factory_platform_profiles" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("factory_platform_profiles")}
        for column, sql in [
            ("brand_name", "ALTER TABLE factory_platform_profiles ADD COLUMN IF NOT EXISTS brand_name VARCHAR(255)"),
            ("address", "ALTER TABLE factory_platform_profiles ADD COLUMN IF NOT EXISTS address VARCHAR(500)"),
            ("founded_year", "ALTER TABLE factory_platform_profiles ADD COLUMN IF NOT EXISTS founded_year INTEGER"),
            ("employee_count", "ALTER TABLE factory_platform_profiles ADD COLUMN IF NOT EXISTS employee_count INTEGER"),
            ("verification_status", "ALTER TABLE factory_platform_profiles ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) NOT NULL DEFAULT 'unverified'"),
            ("logo_url", "ALTER TABLE factory_platform_profiles ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500)"),
            ("factory_video_url", "ALTER TABLE factory_platform_profiles ADD COLUMN IF NOT EXISTS factory_video_url VARCHAR(500)"),
        ]:
            if column not in existing:
                connection.execute(text(sql))

    if "factory_catalog_products" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("factory_catalog_products")}
        for column, sql in [
            ("image_url", "ALTER TABLE factory_catalog_products ADD COLUMN IF NOT EXISTS image_url VARCHAR(500)"),
            ("moq", "ALTER TABLE factory_catalog_products ADD COLUMN IF NOT EXISTS moq INTEGER"),
            ("price_min", "ALTER TABLE factory_catalog_products ADD COLUMN IF NOT EXISTS price_min NUMERIC(12,2)"),
            ("price_max", "ALTER TABLE factory_catalog_products ADD COLUMN IF NOT EXISTS price_max NUMERIC(12,2)"),
            ("currency", "ALTER TABLE factory_catalog_products ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'USD'"),
            ("export_available", "ALTER TABLE factory_catalog_products ADD COLUMN IF NOT EXISTS export_available BOOLEAN NOT NULL DEFAULT TRUE"),
        ]:
            if column not in existing:
                connection.execute(text(sql))

    if "factory_certificates" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("factory_certificates")}
        for column, sql in [
            ("certificate_number", "ALTER TABLE factory_certificates ADD COLUMN IF NOT EXISTS certificate_number VARCHAR(100)"),
            ("issue_date", "ALTER TABLE factory_certificates ADD COLUMN IF NOT EXISTS issue_date DATE"),
            ("document_url", "ALTER TABLE factory_certificates ADD COLUMN IF NOT EXISTS document_url VARCHAR(500)"),
        ]:
            if column not in existing:
                connection.execute(text(sql))

    if "factory_catalog_products" not in inspector.get_table_names():
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS factory_catalog_products (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                product_name VARCHAR(255) NOT NULL,
                category VARCHAR(100),
                description TEXT,
                target_markets JSONB,
                image_url VARCHAR(500),
                moq INTEGER,
                price_min NUMERIC(12,2),
                price_max NUMERIC(12,2),
                currency VARCHAR(10) DEFAULT 'USD',
                export_available BOOLEAN NOT NULL DEFAULT TRUE,
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_factory_catalog_products_tenant_id ON factory_catalog_products (tenant_id)",
        ))

    if "factory_certificates" not in inspector.get_table_names():
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS factory_certificates (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                certificate_name VARCHAR(255) NOT NULL,
                certificate_type VARCHAR(50) NOT NULL,
                issuing_authority VARCHAR(255),
                certificate_number VARCHAR(100),
                issue_date DATE,
                expiry_date DATE,
                document_url VARCHAR(500),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_factory_certificates_tenant_id ON factory_certificates (tenant_id)",
        ))

    if "factory_export_markets" not in inspector.get_table_names():
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS factory_export_markets (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                country VARCHAR(100) NOT NULL,
                market_score INTEGER NOT NULL DEFAULT 0,
                active_buyers INTEGER NOT NULL DEFAULT 0,
                opportunities INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_factory_export_markets_tenant_id ON factory_export_markets (tenant_id)",
        ))

    if "factory_media_assets" not in inspector.get_table_names():
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS factory_media_assets (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                media_type VARCHAR(20) NOT NULL,
                title VARCHAR(255),
                description TEXT,
                media_file_id UUID REFERENCES media_files(id) ON DELETE SET NULL,
                storage_path VARCHAR(500),
                original_filename VARCHAR(255),
                reusable_modules JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_factory_media_assets_tenant_id ON factory_media_assets (tenant_id)",
        ))


def _ensure_admin_security_columns(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "admin_users" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("admin_users")}
        for column, sql in [
            (
                "failed_login_attempts",
                "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0",
            ),
            ("locked_until", "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ"),
        ]:
            if column not in existing:
                connection.execute(text(sql))
    if "admin_sessions" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("admin_sessions")}
        if "access_token_nonce" not in existing:
            connection.execute(text(
                "ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS access_token_nonce VARCHAR(64)",
            ))


def _ensure_tenant_auth_columns(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "tenant_users" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("tenant_users")}
    for column, sql in [
        ("password_hash", "ALTER TABLE tenant_users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"),
        ("refresh_token_hash", "ALTER TABLE tenant_users ADD COLUMN IF NOT EXISTS refresh_token_hash VARCHAR(128)"),
        ("last_login_at", "ALTER TABLE tenant_users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ"),
        ("updated_at", "ALTER TABLE tenant_users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()"),
    ]:
        if column not in existing:
            connection.execute(text(sql))


def _ensure_tenant_columns(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "tenants" not in inspector.get_table_names():
        return
    for table in ("clients", "customer_portal_accounts", "factory_partner_applications"):
        if table not in inspector.get_table_names():
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        if "tenant_id" not in existing:
            connection.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id UUID "
                "REFERENCES tenants(id) ON DELETE SET NULL",
            ))


def _ensure_content_repurpose_columns(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "content_items" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("content_items")}
    for column, sql in [
        (
            "parent_content_id",
            "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS parent_content_id UUID "
            "REFERENCES content_items(id) ON DELETE SET NULL",
        ),
        (
            "parent_media_asset_id",
            "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS parent_media_asset_id UUID "
            "REFERENCES media_assets(id) ON DELETE SET NULL",
        ),
    ]:
        if column not in existing:
            connection.execute(text(sql))


def _ensure_content_campaign_column(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "content_items" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("content_items")}
    if "campaign_id" not in existing:
        connection.execute(text(
            "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS campaign_id UUID "
            "REFERENCES campaigns(id) ON DELETE SET NULL"
        ))


def _ensure_partners_network_columns(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "partners" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("partners")}
    for column, sql in [
        ("company_name", "ALTER TABLE partners ADD COLUMN IF NOT EXISTS company_name VARCHAR(255)"),
        ("country", "ALTER TABLE partners ADD COLUMN IF NOT EXISTS country VARCHAR(100)"),
        ("city", "ALTER TABLE partners ADD COLUMN IF NOT EXISTS city VARCHAR(100)"),
        ("partner_type", "ALTER TABLE partners ADD COLUMN IF NOT EXISTS partner_type VARCHAR(40)"),
        ("industries_json", "ALTER TABLE partners ADD COLUMN IF NOT EXISTS industries_json JSONB"),
        ("website", "ALTER TABLE partners ADD COLUMN IF NOT EXISTS website VARCHAR(500)"),
    ]:
        if column not in existing:
            connection.execute(text(sql))
    connection.execute(text(
        "UPDATE partners SET company_name = company WHERE company_name IS NULL AND company IS NOT NULL"
    ))


def _ensure_client_brand_columns(connection) -> None:
    """Add brand profile columns to existing dev databases (PostgreSQL)."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "clients" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("clients")}
    statements = [
        ("brand_name", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS brand_name VARCHAR(255)"),
        ("business_description", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS business_description TEXT"),
        ("products_services", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS products_services TEXT"),
        ("target_audience", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS target_audience TEXT"),
        ("tone_of_voice", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS tone_of_voice VARCHAR(30) DEFAULT 'friendly'"),
        ("preferred_languages", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS preferred_languages JSONB"),
        ("cta_phone", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS cta_phone VARCHAR(100)"),
        ("cta_telegram", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS cta_telegram VARCHAR(100)"),
        ("cta_website", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS cta_website VARCHAR(500)"),
        ("cta_address", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS cta_address VARCHAR(500)"),
        ("words_to_avoid", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS words_to_avoid TEXT"),
        ("hashtag_preferences", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS hashtag_preferences TEXT"),
        ("logo_url", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500)"),
        ("telegram_group_id", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS telegram_group_id VARCHAR(50)"),
        ("telegram_group_title", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS telegram_group_title VARCHAR(255)"),
        ("telegram_workflow_mode", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS telegram_workflow_mode VARCHAR(40) DEFAULT 'auto_create_from_media'"),
        ("telegram_active_content_id", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS telegram_active_content_id UUID"),
        ("telegram_publish_chat_id", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS telegram_publish_chat_id VARCHAR(255)"),
        ("telegram_publish_title", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS telegram_publish_title VARCHAR(255)"),
        ("telegram_publish_type", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS telegram_publish_type VARCHAR(20)"),
        ("operator_auto_draft_enabled", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS operator_auto_draft_enabled BOOLEAN DEFAULT FALSE"),
        ("plan_name", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS plan_name VARCHAR(100)"),
        ("monthly_fee", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS monthly_fee NUMERIC(10,2)"),
        ("monthly_post_limit", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS monthly_post_limit INTEGER"),
        ("billing_status", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS billing_status VARCHAR(20) DEFAULT 'active'"),
        ("billing_cycle_start", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS billing_cycle_start TIMESTAMPTZ"),
        ("billing_cycle_end", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS billing_cycle_end TIMESTAMPTZ"),
    ]
    for column, sql in statements:
        if column not in existing:
            connection.execute(text(sql))

def _ensure_telegram_buffer_columns(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "telegram_group_buffer_messages" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("telegram_group_buffer_messages")}
    for column, sql in [
        ("inbox_status", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS inbox_status VARCHAR(20) DEFAULT 'new'"),
        ("linked_content_id", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS linked_content_id UUID"),
        ("ai_suggestion_json", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS ai_suggestion_json TEXT"),
        ("ai_suggested_at", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS ai_suggested_at TIMESTAMPTZ"),
        ("auto_drafted", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS auto_drafted BOOLEAN DEFAULT FALSE"),
        ("ai_summary", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS ai_summary TEXT"),
        ("priority", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS priority VARCHAR(10)"),
        ("suggested_publish_date", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS suggested_publish_date TIMESTAMPTZ"),
        ("suggested_platforms_json", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS suggested_platforms_json TEXT"),
        ("detected_deadline", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS detected_deadline VARCHAR(255)"),
        ("detected_offer", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS detected_offer TEXT"),
        ("detected_language", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS detected_language VARCHAR(10)"),
        ("grouped_task_id", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS grouped_task_id UUID"),
        ("smart_analyzed_at", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS smart_analyzed_at TIMESTAMPTZ"),
        ("account_manager_intent", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS account_manager_intent VARCHAR(40)"),
        ("account_manager_summary", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS account_manager_summary TEXT"),
        ("account_manager_recommended_action", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS account_manager_recommended_action TEXT"),
        ("account_manager_priority", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS account_manager_priority VARCHAR(10)"),
        ("account_manager_reply_sent", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS account_manager_reply_sent BOOLEAN DEFAULT FALSE"),
        ("account_manager_reply_text", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS account_manager_reply_text TEXT"),
        ("account_manager_related_content_id", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS account_manager_related_content_id UUID"),
        ("account_manager_processed_at", "ALTER TABLE telegram_group_buffer_messages ADD COLUMN IF NOT EXISTS account_manager_processed_at TIMESTAMPTZ"),
    ]:
        if column not in existing:
            connection.execute(text(sql))

    if "content_items" in inspector.get_table_names():
        content_cols = {c["name"] for c in inspector.get_columns("content_items")}
        if "telegram_group_title" not in content_cols:
            connection.execute(text(
                "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS telegram_group_title VARCHAR(255)"
            ))
        for column, sql in [
            ("telegram_message_id", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT"),
            ("telegram_excluded", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS telegram_excluded BOOLEAN DEFAULT FALSE"),
            ("telegram_instructions", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS telegram_instructions TEXT"),
            ("context_ai_override", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS context_ai_override VARCHAR(50)"),
            ("telegram_buffer_refs", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS telegram_buffer_refs TEXT"),
            ("review_token", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS review_token VARCHAR(64)"),
            ("client_approved_at", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS client_approved_at TIMESTAMPTZ"),
            ("client_review_feedback", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS client_review_feedback TEXT"),
            ("client_review_status", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS client_review_status VARCHAR(30)"),
            ("client_review_preview_sent_at", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS client_review_preview_sent_at TIMESTAMPTZ"),
            ("client_review_preview_error", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS client_review_preview_error TEXT"),
            ("media_request_sent_at", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS media_request_sent_at TIMESTAMPTZ"),
            ("media_request_message", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS media_request_message TEXT"),
            ("media_request_status", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS media_request_status VARCHAR(20)"),
            ("media_request_format", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS media_request_format VARCHAR(20)"),
            ("linked_sales_lead_id", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS linked_sales_lead_id UUID REFERENCES sales_leads(id) ON DELETE SET NULL"),
            ("linked_buyer_id", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS linked_buyer_id UUID REFERENCES buyers(id) ON DELETE SET NULL"),
            ("linked_sales_deal_id", "ALTER TABLE content_items ADD COLUMN IF NOT EXISTS linked_sales_deal_id UUID REFERENCES sales_deals(id) ON DELETE SET NULL"),
        ]:
            if column not in content_cols:
                connection.execute(text(sql))
        if "review_token" not in content_cols:
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_content_items_review_token "
                "ON content_items (review_token) WHERE review_token IS NOT NULL"
            ))


def _ensure_content_plan_columns(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "content_plan_items" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("content_plan_items")}
    if "content_item_id" in existing and "linked_content_id" not in existing:
        connection.execute(text(
            "ALTER TABLE content_plan_items RENAME COLUMN content_item_id TO linked_content_id"
        ))
        existing.discard("content_item_id")
        existing.add("linked_content_id")
    if "linked_content_id" not in existing:
        connection.execute(text(
            "ALTER TABLE content_plan_items ADD COLUMN IF NOT EXISTS linked_content_id UUID "
            "REFERENCES content_items(id) ON DELETE SET NULL"
        ))


def _ensure_crm_deals_columns(connection) -> None:
    """Add revenue/commission columns when crm_deals predates revenue migrations."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "crm_deals" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("crm_deals")}
    statements = [
        ("deal_amount", "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS deal_amount NUMERIC(18, 2)"),
        ("currency", "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'UZS'"),
        ("commission_percent", "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS commission_percent NUMERIC(5, 2)"),
        ("commission_amount", "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS commission_amount NUMERIC(12, 2)"),
        ("commission_status", "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS commission_status VARCHAR(20)"),
        ("partner_commission_percent", "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS partner_commission_percent NUMERIC(5, 2)"),
        ("partner_commission_amount", "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS partner_commission_amount NUMERIC(12, 2)"),
    ]
    for column, sql in statements:
        if column not in existing:
            connection.execute(text(sql))
    connection.execute(text("UPDATE crm_deals SET currency = 'UZS' WHERE currency IS NULL"))
    connection.execute(text(
        "UPDATE crm_deals SET deal_amount = expected_value "
        "WHERE deal_amount IS NULL AND status = 'won' AND expected_value IS NOT NULL"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_crm_deals_commission_status ON crm_deals (commission_status)"
    ))


def _ensure_crm_leads_columns(connection) -> None:
    """Add attribution columns when crm_leads predates revenue/attribution migrations."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "crm_leads" not in inspector.get_table_names():
        return
    for sql in (
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS attribution_source VARCHAR(50)",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS attribution_campaign VARCHAR(255)",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS attribution_notes TEXT",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS attributed_by VARCHAR(100)",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS partner_id UUID",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS referral_code VARCHAR(50)",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS attribution_link_id UUID",
        "UPDATE crm_leads SET attribution_source = source "
        "WHERE attribution_source IS NULL AND source IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_crm_leads_partner_id ON crm_leads (partner_id)",
        "CREATE INDEX IF NOT EXISTS ix_crm_leads_attribution_link_id ON crm_leads (attribution_link_id)",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS lead_score INTEGER",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS qualification_level VARCHAR(50)",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS ai_summary TEXT",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS recommended_action TEXT",
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS last_scored_at TIMESTAMPTZ",
        "CREATE INDEX IF NOT EXISTS ix_crm_leads_lead_score ON crm_leads (lead_score)",
        "CREATE INDEX IF NOT EXISTS ix_crm_leads_qualification_level ON crm_leads (qualification_level)",
    ):
        connection.execute(text(sql))


def _ensure_outreach_proposal_columns(connection) -> None:
    """Outreach workflow + sales playbook link columns (schema drift safe)."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "buyer_outreach_messages" in inspector.get_table_names():
        for sql in (
            "ALTER TABLE buyer_outreach_messages ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ",
            "ALTER TABLE buyer_outreach_messages ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
            "ALTER TABLE buyer_outreach_messages ADD COLUMN IF NOT EXISTS communication_thread_id UUID",
            "ALTER TABLE buyer_outreach_messages ADD COLUMN IF NOT EXISTS follow_up_task_id UUID",
            "ALTER TABLE buyer_outreach_messages ADD COLUMN IF NOT EXISTS copied_at TIMESTAMPTZ",
            "ALTER TABLE buyer_outreach_messages ADD COLUMN IF NOT EXISTS last_action_at TIMESTAMPTZ",
            "ALTER TABLE buyer_outreach_messages ADD COLUMN IF NOT EXISTS sales_playbook_id UUID",
            "ALTER TABLE buyer_outreach_messages ADD COLUMN IF NOT EXISTS sales_playbook_step_id UUID",
            "CREATE INDEX IF NOT EXISTS ix_buyer_outreach_messages_communication_thread_id "
            "ON buyer_outreach_messages (communication_thread_id)",
            "CREATE INDEX IF NOT EXISTS ix_buyer_outreach_messages_follow_up_task_id "
            "ON buyer_outreach_messages (follow_up_task_id)",
            "CREATE INDEX IF NOT EXISTS ix_buyer_outreach_messages_sales_playbook_id "
            "ON buyer_outreach_messages (sales_playbook_id)",
        ):
            connection.execute(text(sql))
    if "proposal_documents" in inspector.get_table_names():
        for sql in (
            "ALTER TABLE proposal_documents ADD COLUMN IF NOT EXISTS exported_pdf_path VARCHAR(500)",
            "ALTER TABLE proposal_documents ADD COLUMN IF NOT EXISTS exported_docx_path VARCHAR(500)",
            "ALTER TABLE proposal_documents ADD COLUMN IF NOT EXISTS last_exported_at TIMESTAMPTZ",
            "ALTER TABLE proposal_documents ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ",
            "ALTER TABLE proposal_documents ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ",
            "ALTER TABLE proposal_documents ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ",
            "ALTER TABLE proposal_documents ADD COLUMN IF NOT EXISTS follow_up_at TIMESTAMPTZ",
            "ALTER TABLE proposal_documents ADD COLUMN IF NOT EXISTS buyer_feedback TEXT",
            "ALTER TABLE proposal_documents ADD COLUMN IF NOT EXISTS sales_playbook_id UUID",
            "ALTER TABLE proposal_documents ADD COLUMN IF NOT EXISTS sales_playbook_step_id UUID",
            "CREATE INDEX IF NOT EXISTS ix_proposal_documents_sales_playbook_id "
            "ON proposal_documents (sales_playbook_id)",
        ):
            connection.execute(text(sql))


def _ensure_operator_tasks_columns(connection) -> None:
    """Add task execution columns when operator_tasks predates execution migration."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "operator_tasks" not in inspector.get_table_names():
        return
    for sql in (
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS execution_status VARCHAR(20)",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS execution_result TEXT",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS executed_at TIMESTAMPTZ",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS recommendation_id UUID",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(80)",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS lead_id UUID",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS deal_id UUID",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS proposal_id UUID",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS channel VARCHAR(30)",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS action_type VARCHAR(40)",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMPTZ",
    ):
        connection.execute(text(sql))


def _ensure_communication_wechat_columns(connection) -> None:
    """WeChat Contact Center columns on communication hub tables."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "communication_contacts" in inspector.get_table_names():
        for sql in (
            "ALTER TABLE communication_contacts ADD COLUMN IF NOT EXISTS wechat_id VARCHAR(100)",
            "ALTER TABLE communication_contacts ADD COLUMN IF NOT EXISTS wecom_id VARCHAR(100)",
            "ALTER TABLE communication_contacts ADD COLUMN IF NOT EXISTS qr_code_url VARCHAR(500)",
            "ALTER TABLE communication_contacts ADD COLUMN IF NOT EXISTS preferred_language VARCHAR(20)",
            "CREATE INDEX IF NOT EXISTS ix_communication_contacts_wechat_id "
            "ON communication_contacts (wechat_id)",
            "CREATE INDEX IF NOT EXISTS ix_communication_contacts_wecom_id "
            "ON communication_contacts (wecom_id)",
        ):
            connection.execute(text(sql))
    if "communication_threads" in inspector.get_table_names():
        for sql in (
            "ALTER TABLE communication_threads ADD COLUMN IF NOT EXISTS deal_id UUID",
            "ALTER TABLE communication_threads ADD COLUMN IF NOT EXISTS external_contact_id VARCHAR(100)",
            "ALTER TABLE communication_threads ADD COLUMN IF NOT EXISTS last_manual_sync_at TIMESTAMPTZ",
            "CREATE INDEX IF NOT EXISTS ix_communication_threads_deal_id "
            "ON communication_threads (deal_id)",
            "CREATE INDEX IF NOT EXISTS ix_communication_threads_external_contact_id "
            "ON communication_threads (external_contact_id)",
        ):
            connection.execute(text(sql))
    if "communication_messages" in inspector.get_table_names():
        for sql in (
            "ALTER TABLE communication_messages ADD COLUMN IF NOT EXISTS original_language VARCHAR(20)",
            "ALTER TABLE communication_messages ADD COLUMN IF NOT EXISTS translated_text TEXT",
            "ALTER TABLE communication_messages ADD COLUMN IF NOT EXISTS copied_at TIMESTAMPTZ",
            "ALTER TABLE communication_messages ADD COLUMN IF NOT EXISTS manual_sent_at TIMESTAMPTZ",
        ):
            connection.execute(text(sql))


def _ensure_communication_platform_integration_columns(connection) -> None:
    """Sales CRM links on communication hub tables (platform integrations migration)."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    for table in ("communication_threads", "communication_contacts"):
        if table not in tables:
            continue
        for column, fk_table in (
            ("sales_lead_id", "sales_leads"),
            ("sales_deal_id", "sales_deals"),
        ):
            connection.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} UUID "
                f"REFERENCES {fk_table}(id) ON DELETE SET NULL"
            ))
            connection.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table} ({column})"
            ))


def _ensure_communication_hub_mvp_columns(connection) -> None:
    """Communication Hub MVP — tenant links, follow-ups, templates."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())

    for table in ("communication_contacts", "communication_threads"):
        if table in tables:
            connection.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id UUID "
                f"REFERENCES tenants(id) ON DELETE CASCADE"
            ))
            connection.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)"
            ))

    if "communication_threads" in tables:
        for sql in (
            "ALTER TABLE communication_threads ADD COLUMN IF NOT EXISTS buyer_id UUID "
            "REFERENCES buyers(id) ON DELETE SET NULL",
            "ALTER TABLE communication_threads ADD COLUMN IF NOT EXISTS customer_id UUID "
            "REFERENCES sales_customers(id) ON DELETE SET NULL",
            "CREATE INDEX IF NOT EXISTS ix_communication_threads_buyer_id "
            "ON communication_threads (buyer_id)",
            "CREATE INDEX IF NOT EXISTS ix_communication_threads_customer_id "
            "ON communication_threads (customer_id)",
        ):
            connection.execute(text(sql))

    if "communication_messages" in tables:
        for sql in (
            "ALTER TABLE communication_messages ADD COLUMN IF NOT EXISTS status VARCHAR(20) "
            "NOT NULL DEFAULT 'sent'",
            "ALTER TABLE communication_messages ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ "
            "DEFAULT NOW()",
            "CREATE INDEX IF NOT EXISTS ix_communication_messages_status "
            "ON communication_messages (status)",
        ):
            connection.execute(text(sql))

    if "communication_follow_ups" not in tables:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS communication_follow_ups (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                communication_id UUID REFERENCES communication_messages(id) ON DELETE SET NULL,
                thread_id UUID REFERENCES communication_threads(id) ON DELETE SET NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                due_date TIMESTAMPTZ NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                assigned_user VARCHAR(255),
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_communication_follow_ups_tenant_id "
            "ON communication_follow_ups (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_communication_follow_ups_due_date "
            "ON communication_follow_ups (due_date)",
            "CREATE INDEX IF NOT EXISTS ix_communication_follow_ups_status "
            "ON communication_follow_ups (status)",
        ):
            connection.execute(text(sql))

    if "communication_message_templates" not in tables:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS communication_message_templates (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                category VARCHAR(30) NOT NULL,
                content TEXT NOT NULL,
                language VARCHAR(10) NOT NULL DEFAULT 'en',
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        for sql in (
            "CREATE INDEX IF NOT EXISTS ix_communication_message_templates_tenant_id "
            "ON communication_message_templates (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_communication_message_templates_category "
            "ON communication_message_templates (category)",
        ):
            connection.execute(text(sql))


def _ensure_whatsapp_tables(connection) -> None:
    """WhatsApp Contact Center tables (idempotent dev patch)."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())

    if "whatsapp_contacts" not in tables:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS whatsapp_contacts (
                id UUID PRIMARY KEY,
                phone VARCHAR(50) NOT NULL,
                display_name VARCHAR(255) NOT NULL,
                company VARCHAR(255),
                country VARCHAR(100),
                crm_client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_whatsapp_contacts_phone ON whatsapp_contacts (phone)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_whatsapp_contacts_crm_client_id "
            "ON whatsapp_contacts (crm_client_id)"
        ))

    if "whatsapp_threads" not in tables:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS whatsapp_threads (
                id UUID PRIMARY KEY,
                contact_id UUID NOT NULL REFERENCES whatsapp_contacts(id) ON DELETE CASCADE,
                last_message_at TIMESTAMPTZ,
                unread_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_whatsapp_threads_contact_id "
            "ON whatsapp_threads (contact_id)"
        ))

    if "whatsapp_messages" not in tables:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                id UUID PRIMARY KEY,
                thread_id UUID NOT NULL REFERENCES whatsapp_threads(id) ON DELETE CASCADE,
                direction VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'sent',
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_whatsapp_messages_thread_id "
            "ON whatsapp_messages (thread_id)"
        ))
