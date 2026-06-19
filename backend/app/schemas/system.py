from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel


HealthStatus = Literal["ok", "degraded"]
DatabaseStatus = Literal["ok", "error"]
SchedulerStatus = Literal["running", "stopped", "disabled"]
AiServicesStatus = Literal["ok", "demo", "unconfigured"]
TelegramStatus = Literal["configured", "unconfigured"]


class DbPoolStatus(BaseModel):
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    checked_in: int
    checked_out: int
    overflow: int


class SystemHealthResponse(BaseModel):
    status: HealthStatus
    uptime: int
    database: DatabaseStatus
    scheduler: SchedulerStatus
    ai_services: AiServicesStatus
    telegram_bot: TelegramStatus
    demo_mode: bool = False
    total_clients: int
    total_leads: int
    total_deals: int
    total_content: int
    total_posts: int
    total_revenue: Decimal
    total_commissions: Decimal
    db_pool: DbPoolStatus | None = None


class DemoSeedResponse(BaseModel):
    created: bool
    message: str
    client_id: str | None = None
    partner_id: str | None = None
    leads: int | None = None
    deals: int | None = None
    won_deals: int | None = None
    content_items: int | None = None


class DemoResetResponse(BaseModel):
    deleted: bool
    message: str
    counts: dict[str, int] | None = None


class SchemaHealthMissingColumn(BaseModel):
    table: str
    column: str


class SchemaHealthResponse(BaseModel):
    ok: bool
    database_connected: bool = True
    alembic_current_revision: str | None = None
    alembic_head_revision: str | None = None
    migration_drift: bool = False
    missing_tables: list[str]
    missing_columns: list[SchemaHealthMissingColumn]
    checked_models: list[str] = []
    warnings: list[str] = []


class ApiHealthEndpointStatus(BaseModel):
    name: str
    path: str
    status: Literal["ok", "error", "slow"]
    duration_ms: int
    error: str | None = None


class ApiHealthResponse(BaseModel):
    endpoints: list[ApiHealthEndpointStatus]
    ok_count: int
    total: int
    admin_security: dict[str, Any] | None = None


class RecentErrorEntry(BaseModel):
    timestamp: str
    method: str
    path: str
    status: int
    duration_ms: int
    error_summary: str | None = None
    category: str = "unknown"


class RecentErrorsResponse(BaseModel):
    errors: list[RecentErrorEntry]
    slow: list[RecentErrorEntry]
    categories: dict[str, int] = {}


class QueryHealthEntry(BaseModel):
    endpoint: str
    avg_duration_ms: float
    max_duration_ms: float
    call_count: int
    avg_query_count: float = 0.0


class QueryHealthResponse(BaseModel):
    endpoints: list[QueryHealthEntry]
    slowest_requests: list[dict[str, Any]] = []


class DependencyChainItem(BaseModel):
    kind: str
    name: str


class PageDependency(BaseModel):
    page: str
    route: str
    endpoints: list[str]
    services: list[str]
    tables: list[str]
    chain: list[DependencyChainItem]


class DependenciesResponse(BaseModel):
    pages: list[PageDependency]
    total: int
    admin_security: dict[str, Any] | None = None


class HealthSnapshotEntry(BaseModel):
    timestamp: str
    schema_ok: bool
    migration_drift: bool
    missing_tables_count: int
    missing_columns_count: int
    api_ok_count: int
    api_total: int
    error_count_5xx: int
    slow_count: int
    error_categories: dict[str, int] = {}
    broken_endpoints: list[str] = []


class HealthSnapshotsResponse(BaseModel):
    snapshots: list[HealthSnapshotEntry]
    retention_hours: int = 48


class I18nHealthResponse(BaseModel):
    missing_keys: dict[str, list[str]]
    unused_keys: list[str]
    translated_keys_count: dict[str, int]
    canonical_locale: str
    used_keys_count: int
