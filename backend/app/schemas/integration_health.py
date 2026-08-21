"""Pydantic schemas for integration health API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HealthStatus = Literal[
    "healthy",
    "degraded",
    "action_required",
    "unavailable",
    "unknown",
]


class CapabilityHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    reason_code: str
    reason: str
    requires_operator_action: bool = False


class IntegrationHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integration_id: str
    platform: str
    provider: str
    tenant_id: str | None = None
    client_id: str | None = None
    account_name: str | None = None
    status: HealthStatus
    severity: str
    reason_code: str
    reason: str
    checked_at: str | None = None
    last_success_at: str | None = None
    stale_after_seconds: int
    stale: bool
    requires_operator_action: bool
    responsible_party: str
    recommended_next_step: str
    deep_link: str
    capabilities: list[CapabilityHealthOut] = Field(default_factory=list)
    source: str = "local"
    never_checked: bool = False
    transient_failure_count: int = 0
    safe_auto_recheck: bool = True


class IntegrationHealthSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    healthy: int = 0
    degraded: int = 0
    action_required: int = 0
    unavailable: int = 0
    unknown: int = 0
    stale: int = 0
    requires_action: int = 0


class IntegrationHealthListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[IntegrationHealthOut]
    total: int
    summary: IntegrationHealthSummaryOut
    checked_at: str
    cache_semantics: str
    live_check: bool = False


class IntegrationHealthDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: IntegrationHealthOut
    cache_semantics: str
    live_check: bool = False
