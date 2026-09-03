"""Mobile Operator Control Plane — thin read aggregation over canonical services.

Phase 1: home + system-status only. Mutations stay on Operator Workspace actions.
No provider live calls. No new workflow state. No backup subprocess bridge.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.mobile_control import (
    MobileBackupStatus,
    MobileControlCapabilities,
    MobileControlHomeResponse,
    MobileControlSystemResponse,
    MobileSystemStatusSummary,
)
from app.schemas.operator_workspace import OperatorAttentionItem
from app.services.notification_service import NotificationService
from app.services.operator_workspace_actions import (
    ACTION_ACKNOWLEDGE_ALERT,
    ACTION_APPROVE_CONTENT,
    ACTION_OPEN,
    ACTION_RESOLVE_ALERT,
    ACTION_RETRY_PUBLISH,
    OperatorWorkspaceActionService,
)
from app.services.operator_workspace_service import (
    PRIORITY_ORDER,
    OperatorWorkspaceService,
    _sort_key,
)
from app.services.system_health_service import SystemHealthService

logger = logging.getLogger(__name__)

URGENT_PRIORITIES = frozenset({"critical", "high"})
DEFAULT_URGENT_LIMIT = 10

_PROBLEM_TYPES = frozenset({
    "publishing_issue",
    "scheduling_issue",
    "integration_issue",
    "telegram_ingestion_issue",
    "automation_failure",
})

_CAPABILITIES = MobileControlCapabilities(
    actions_supported=[
        ACTION_OPEN,
        ACTION_ACKNOWLEDGE_ALERT,
        ACTION_RESOLVE_ALERT,
        ACTION_RETRY_PUBLISH,
        ACTION_APPROVE_CONTENT,
    ],
    # Durable push device registration requires an approved migration.
    push_registration=False,
    biometric_unlock=False,
    # Internal reject is PATCH status only — not a dedicated operator action yet.
    internal_content_reject=False,
    backup_status_live=False,
    realtime_channel=False,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _map_component(raw: str | None) -> str:
    if not raw:
        return "unknown"
    value = str(raw).lower()
    if value in ("ok", "running", "configured"):
        return "ok"
    if value in ("error", "stopped", "degraded"):
        return "degraded"
    if value == "disabled":
        return "disabled"
    if value == "unconfigured":
        return "unconfigured"
    if value == "demo":
        return "demo"
    return "unknown"


class MobileControlService:
    """Thin aggregation — never owns domain mutations."""

    @classmethod
    def capabilities(cls) -> MobileControlCapabilities:
        return _CAPABILITIES.model_copy(deep=True)

    @classmethod
    async def build_system_status(
        cls,
        db: AsyncSession,
        *,
        integration_attention_count: int = 0,
    ) -> MobileSystemStatusSummary:
        """Sanitized health. Never exposes secrets, IPs, pool internals, or env."""
        notes: list[str] = []
        try:
            raw = await SystemHealthService.health(db)
        except Exception:
            logger.exception("mobile-control system health failed")
            return MobileSystemStatusSummary(
                overall="degraded",
                api="ok",
                database="unknown",
                integration_attention_count=integration_attention_count,
                backup=MobileBackupStatus(),
                notes=["System health check failed — treat as degraded"],
            )

        database = _map_component(raw.get("database"))
        if database == "degraded" or raw.get("database") == "error":
            database = "degraded"

        scheduler = _map_component(raw.get("scheduler"))
        ai = _map_component(raw.get("ai_services"))
        telegram = _map_component(raw.get("telegram_bot"))

        overall_raw = raw.get("status")
        overall = _map_component(overall_raw)
        if overall == "unknown" and database == "ok":
            overall = "ok"
        if database == "degraded":
            overall = "degraded"

        if integration_attention_count > 0:
            notes.append(
                f"{integration_attention_count} integration(s) need attention "
                "(see Problems / Integrations)",
            )

        notes.append(
            "Backup freshness is unavailable on mobile until a read-only "
            "status bridge is approved.",
        )

        return MobileSystemStatusSummary(
            overall=overall if overall in ("ok", "degraded", "unknown") else "unknown",
            api="ok",
            database=database if database in ("ok", "degraded", "unknown") else "unknown",
            scheduler=scheduler,
            ai_services=ai,
            telegram_bot=telegram,
            integration_attention_count=integration_attention_count,
            backup=MobileBackupStatus(),
            uptime_seconds=int(raw["uptime"]) if raw.get("uptime") is not None else None,
            notes=notes,
        )

    @classmethod
    def _select_urgent(
        cls,
        items: list[OperatorAttentionItem],
        *,
        limit: int = DEFAULT_URGENT_LIMIT,
    ) -> list[OperatorAttentionItem]:
        urgent = [i for i in items if i.priority in URGENT_PRIORITIES]
        urgent.sort(key=_sort_key)
        page = urgent[: max(0, limit)]
        OperatorWorkspaceActionService.attach_actions(page)
        return page

    @classmethod
    async def get_home(
        cls,
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        urgent_limit: int = DEFAULT_URGENT_LIMIT,
        tenant_id: UUID | None = None,
    ) -> MobileControlHomeResponse:
        """Aggregate canonical projections. No provider calls. No mutations."""
        now = _utc_now()
        limit = max(1, min(int(urgent_limit), 25))

        items = await OperatorWorkspaceService._collect_items(db, client_id=client_id)
        summary = OperatorWorkspaceService._build_summary(items)

        approvals_count = sum(
            1 for i in items if i.attention_type == "content_internal_review"
        )
        problems_count = sum(1 for i in items if i.attention_type in _PROBLEM_TYPES)

        unread = 0
        if tenant_id is not None:
            try:
                unread_resp = await NotificationService.get_unread_count(db, tenant_id)
                unread = int(unread_resp.unread_count)
            except Exception:
                logger.exception("mobile-control unread notifications failed")
                unread = 0

        system_status = await cls.build_system_status(
            db,
            integration_attention_count=summary.integration_issues,
        )
        urgent_items = cls._select_urgent(items, limit=limit)

        return MobileControlHomeResponse(
            generated_at=now,
            attention_summary=summary,
            approvals_count=approvals_count,
            problems_count=problems_count,
            waiting_for_client=summary.waiting_for_client,
            unread_notifications=unread,
            system_status=system_status,
            urgent_items=urgent_items,
            urgent_limit=limit,
            capabilities=cls.capabilities(),
            deep_link_base="/operator-workspace",
            last_updated_at=now,
        )

    @classmethod
    async def get_system(
        cls,
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> MobileControlSystemResponse:
        items = await OperatorWorkspaceService._collect_items(db, client_id=client_id)
        summary = OperatorWorkspaceService._build_summary(items)
        system_status = await cls.build_system_status(
            db,
            integration_attention_count=summary.integration_issues,
        )
        return MobileControlSystemResponse(
            generated_at=_utc_now(),
            system_status=system_status,
            capabilities=cls.capabilities(),
        )
