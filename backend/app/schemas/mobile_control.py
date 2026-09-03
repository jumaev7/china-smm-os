"""Mobile Operator Control Plane — thin aggregation schemas (Phase 1).

No new workflow state. Aggregates Operator Workspace + notification + safe system status.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.operator_workspace import (
    OperatorAttentionItem,
    OperatorWorkspaceSummary,
)


ComponentStatus = Literal["ok", "degraded", "unknown", "disabled", "unconfigured", "demo"]
BackupExposure = Literal["unavailable", "healthy", "action_required", "unknown"]


class MobileBackupStatus(BaseModel):
    """Read-only backup posture for mobile SYSTEM tab.

    Live host/R2 status is NOT tenant-exposed. Phase 1 returns ``unavailable``
    until a safe read-only status bridge is approved (no restore/download).
    """

    status: BackupExposure = "unavailable"
    last_successful_at: datetime | None = None
    message: str = (
        "Backup status is not exposed via the tenant API. "
        "Host ops status only — no restore/download from mobile."
    )


class MobileSystemStatusSummary(BaseModel):
    """Sanitized operator-safe system posture. No secrets, IPs, or raw env."""

    overall: ComponentStatus = "unknown"
    api: ComponentStatus = "ok"
    database: ComponentStatus = "unknown"
    scheduler: ComponentStatus = "unknown"
    ai_services: ComponentStatus = "unknown"
    telegram_bot: ComponentStatus = "unknown"
    integration_attention_count: int = 0
    backup: MobileBackupStatus = Field(default_factory=MobileBackupStatus)
    uptime_seconds: int | None = None
    notes: list[str] = Field(default_factory=list)


class MobileControlCapabilities(BaseModel):
    """Capability flags so slower-updating mobile clients stay action-driven."""

    actions_supported: list[str] = Field(default_factory=list)
    push_registration: bool = False
    biometric_unlock: bool = False  # client-only; never replaces API auth
    internal_content_reject: bool = False
    backup_status_live: bool = False
    realtime_channel: bool = False


class MobileControlHomeResponse(BaseModel):
    """Compact home payload for Today / Approvals / Problems / System tabs.

    Does not call providers live, mutate state, or bypass tenant scope.
    """

    generated_at: datetime
    attention_summary: OperatorWorkspaceSummary
    approvals_count: int = 0
    problems_count: int = 0
    waiting_for_client: int = 0
    unread_notifications: int = 0
    system_status: MobileSystemStatusSummary
    urgent_items: list[OperatorAttentionItem] = Field(default_factory=list)
    urgent_limit: int = 10
    capabilities: MobileControlCapabilities
    deep_link_base: str = "/operator-workspace"
    last_updated_at: datetime


class MobileControlSystemResponse(BaseModel):
    """SYSTEM tab — same sanitized projection as home.system_status."""

    generated_at: datetime
    system_status: MobileSystemStatusSummary
    capabilities: MobileControlCapabilities
