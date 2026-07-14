"""Tenant-scoped Automation Center service."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import (
    AUTOMATION_FLOW_STATUSES,
    TenantAutomationExecution,
    TenantAutomationFlow,
)
from app.schemas.automation import (
    AutomationExecutionListResponse,
    AutomationExecutionSummary,
    AutomationFlowDetail,
    AutomationFlowListResponse,
    AutomationFlowSummary,
    AutomationFlowUpdate,
    AutomationKpiResponse,
    AutomationManualRunResponse,
    AutomationStatusChangeResponse,
)
from app.services.automation_execution_service import AutomationExecutionService

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

SYSTEM_FLOW_DEFINITIONS: tuple[dict, ...] = (
    {
        "key": "system_publish_failed_notify",
        "name": "Publishing failure recovery",
        "description": "When a publish attempt fails, create an in-app notification for the team.",
        "category": "publishing",
        "trigger_event": "tenant.content.publish_failed",
        "action_type": "create_notification",
        "action_config": {
            "title": "Publishing failed: {resource_name}",
            "body": "A publish attempt failed. Review publishing settings and retry.",
            "category": "publishing",
            "severity": "warning",
            "action_url": "/publishing",
            "resource_type": "publishing",
        },
    },
    {
        "key": "system_integration_disconnected_notify",
        "name": "Integration disconnected response",
        "description": "When an integration disconnects, notify admins to reconnect.",
        "category": "integrations",
        "trigger_event": "tenant.integration.disconnected",
        "action_type": "create_notification",
        "action_config": {
            "title": "{integration_name} disconnected",
            "body": "An integration was disconnected. Reconnect from Integrations.",
            "category": "integrations",
            "severity": "warning",
            "action_url": "/integrations",
            "resource_type": "integration",
        },
    },
    {
        "key": "system_buyer_created_crm_lead",
        "name": "Buyer import to CRM",
        "description": "When a buyer is created, automatically create a CRM lead for follow-up.",
        "category": "crm",
        "trigger_event": "tenant.buyer.created",
        "action_type": "create_crm_lead",
        "action_config": {
            "name_template": "Buyer: {buyer_name}",
            "notes_template": "Auto-created from buyer {buyer_id} ({company_name})",
            "source": "other",
            "priority": "medium",
        },
    },
)


def _escape_ilike(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _flow_enabled(status: str) -> bool:
    return status == "enabled"


def _map_ui_status(flow: TenantAutomationFlow) -> str:
    if flow.last_execution_status == "failed" and flow.status == "enabled":
        return "failed"
    if flow.status == "enabled":
        return "active"
    if flow.status == "paused":
        return "paused"
    return "draft"


async def _execution_count(db: AsyncSession, tenant_id: UUID, flow_id: UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.automation_flow_id == flow_id,
                ),
            )
        ).scalar_one(),
    )


async def _row_to_summary(
    db: AsyncSession,
    row: TenantAutomationFlow,
) -> AutomationFlowSummary:
    count, rate = await AutomationExecutionService.count_success_rate(db, row.tenant_id, row.id)
    return AutomationFlowSummary(
        id=row.id,
        key=row.key,
        name=row.name,
        description=row.description,
        category=row.category,
        trigger_event=row.trigger_event,
        action_type=row.action_type,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        is_system=row.is_system,
        enabled=_flow_enabled(row.status),
        last_executed_at=row.last_executed_at,
        last_execution_status=row.last_execution_status,  # type: ignore[arg-type]
        execution_count=count,
        success_rate=round(rate, 1),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _execution_to_summary(
    row: TenantAutomationExecution,
    *,
    automation_name: str | None = None,
) -> AutomationExecutionSummary:
    payload = row.input_payload or {}
    return AutomationExecutionSummary(
        id=row.id,
        automation_flow_id=row.automation_flow_id,
        automation_name=automation_name,
        event_id=row.event_id,
        trigger_event=row.trigger_event,
        status=row.status,  # type: ignore[arg-type]
        started_at=row.started_at,
        finished_at=row.finished_at,
        duration_ms=row.duration_ms,
        error_code=row.error_code,
        error_message=row.error_message,
        attempt_number=row.attempt_number,
        is_manual_test=bool(payload.get("manual_test")),
        created_at=row.created_at,
    )


class AutomationService:
    @staticmethod
    async def ensure_system_flows(db: AsyncSession, tenant_id: UUID) -> int:
        created = 0
        for spec in SYSTEM_FLOW_DEFINITIONS:
            existing = (
                await db.execute(
                    select(TenantAutomationFlow).where(
                        TenantAutomationFlow.tenant_id == tenant_id,
                        TenantAutomationFlow.key == spec["key"],
                    ),
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            row = TenantAutomationFlow(
                tenant_id=tenant_id,
                key=spec["key"],
                name=spec["name"],
                description=spec["description"],
                category=spec["category"],
                trigger_event=spec["trigger_event"],
                action_type=spec["action_type"],
                action_config=spec["action_config"],
                status="enabled",
                is_system=True,
            )
            db.add(row)
            created += 1
        if created:
            await db.flush()
        return created

    @staticmethod
    async def list_flows(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        status: str | None = None,
        category: str | None = None,
        search: str | None = None,
    ) -> AutomationFlowListResponse:
        await AutomationService.ensure_system_flows(db, tenant_id)
        filters = [TenantAutomationFlow.tenant_id == tenant_id]
        if status and status in AUTOMATION_FLOW_STATUSES:
            filters.append(TenantAutomationFlow.status == status)
        if category:
            filters.append(TenantAutomationFlow.category == category)
        if search and search.strip():
            term = f"%{_escape_ilike(search.strip())}%"
            filters.append(
                or_(
                    TenantAutomationFlow.name.ilike(term, escape="\\"),
                    TenantAutomationFlow.description.ilike(term, escape="\\"),
                    TenantAutomationFlow.key.ilike(term, escape="\\"),
                ),
            )
        rows = (
            await db.execute(
                select(TenantAutomationFlow)
                .where(*filters)
                .order_by(
                    TenantAutomationFlow.is_system.desc(),
                    TenantAutomationFlow.updated_at.desc(),
                ),
            )
        ).scalars().all()
        items = [await _row_to_summary(db, row) for row in rows]
        return AutomationFlowListResponse(items=items, total=len(items))

    @staticmethod
    async def get_flow(db: AsyncSession, tenant_id: UUID, flow_id: UUID) -> AutomationFlowDetail:
        await AutomationService.ensure_system_flows(db, tenant_id)
        row = await AutomationService._load_flow(db, tenant_id, flow_id)
        summary = await _row_to_summary(db, row)
        recent_rows = (
            await db.execute(
                select(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.automation_flow_id == flow_id,
                )
                .order_by(TenantAutomationExecution.created_at.desc())
                .limit(10),
            )
        ).scalars().all()
        recent = [_execution_to_summary(r, automation_name=row.name) for r in recent_rows]
        return AutomationFlowDetail(
            **summary.model_dump(),
            action_config=row.action_config or {},
            recent_executions=recent,
        )

    @staticmethod
    async def update_flow(
        db: AsyncSession,
        tenant_id: UUID,
        flow_id: UUID,
        data: AutomationFlowUpdate,
    ) -> AutomationFlowDetail:
        row = await AutomationService._load_flow(db, tenant_id, flow_id)
        payload = data.model_dump(exclude_unset=True)
        if not payload:
            return await AutomationService.get_flow(db, tenant_id, flow_id)
        if row.is_system and "name" in payload:
            raise HTTPException(status_code=409, detail="System flow name cannot be changed")
        for key, value in payload.items():
            setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return await AutomationService.get_flow(db, tenant_id, flow_id)

    @staticmethod
    async def enable_flow(
        db: AsyncSession,
        tenant_id: UUID,
        flow_id: UUID,
    ) -> AutomationStatusChangeResponse:
        row = await AutomationService._load_flow(db, tenant_id, flow_id)
        row.status = "enabled"
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return AutomationStatusChangeResponse(
            id=row.id,
            status="enabled",
            enabled=True,
            updated_at=row.updated_at,
        )

    @staticmethod
    async def pause_flow(
        db: AsyncSession,
        tenant_id: UUID,
        flow_id: UUID,
    ) -> AutomationStatusChangeResponse:
        row = await AutomationService._load_flow(db, tenant_id, flow_id)
        row.status = "paused"
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return AutomationStatusChangeResponse(
            id=row.id,
            status="paused",
            enabled=False,
            updated_at=row.updated_at,
        )

    @staticmethod
    async def disable_flow(
        db: AsyncSession,
        tenant_id: UUID,
        flow_id: UUID,
    ) -> AutomationStatusChangeResponse:
        row = await AutomationService._load_flow(db, tenant_id, flow_id)
        if row.is_system:
            raise HTTPException(status_code=409, detail="System flows cannot be disabled")
        row.status = "disabled"
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return AutomationStatusChangeResponse(
            id=row.id,
            status="disabled",
            enabled=False,
            updated_at=row.updated_at,
        )

    @staticmethod
    async def manual_run(
        db: AsyncSession,
        tenant_id: UUID,
        flow_id: UUID,
    ) -> AutomationManualRunResponse:
        row = await AutomationService._load_flow(db, tenant_id, flow_id)
        execution = await AutomationExecutionService.run_manual_test(db, tenant_id, row)
        await db.flush()
        return AutomationManualRunResponse(
            execution_id=execution.id,
            flow_id=row.id,
            status=execution.status,  # type: ignore[arg-type]
            is_manual_test=True,
            duration_ms=execution.duration_ms,
            error_message=execution.error_message,
        )

    @staticmethod
    async def list_executions(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        flow_id: UUID | None = None,
        status: str | None = None,
    ) -> AutomationExecutionListResponse:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        offset = (page - 1) * page_size
        filters = [TenantAutomationExecution.tenant_id == tenant_id]
        if flow_id is not None:
            filters.append(TenantAutomationExecution.automation_flow_id == flow_id)
        if status:
            filters.append(TenantAutomationExecution.status == status)

        total = (
            await db.execute(
                select(func.count()).select_from(TenantAutomationExecution).where(*filters),
            )
        ).scalar_one()

        rows = (
            await db.execute(
                select(TenantAutomationExecution, TenantAutomationFlow.name)
                .join(
                    TenantAutomationFlow,
                    TenantAutomationFlow.id == TenantAutomationExecution.automation_flow_id,
                )
                .where(*filters)
                .order_by(TenantAutomationExecution.created_at.desc())
                .offset(offset)
                .limit(page_size),
            )
        ).all()

        items = [
            _execution_to_summary(exec_row, automation_name=flow_name)
            for exec_row, flow_name in rows
        ]
        pages = max(1, math.ceil(int(total) / page_size)) if total else 0
        if total == 0:
            pages = 0
        return AutomationExecutionListResponse(
            items=items,
            total=int(total),
            page=page,
            page_size=page_size,
            pages=pages,
        )

    @staticmethod
    async def get_kpis(db: AsyncSession, tenant_id: UUID) -> AutomationKpiResponse:
        await AutomationService.ensure_system_flows(db, tenant_id)
        flows = (
            await db.execute(
                select(TenantAutomationFlow).where(TenantAutomationFlow.tenant_id == tenant_id),
            )
        ).scalars().all()

        active = sum(1 for f in flows if f.status == "enabled")
        paused = sum(1 for f in flows if f.status == "paused")
        disabled = sum(1 for f in flows if f.status == "disabled")
        failed_flows = sum(
            1 for f in flows if f.status == "enabled" and f.last_execution_status == "failed"
        )

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_total = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.created_at >= since,
                ),
            )
        ).scalar_one()
        recent_success = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.created_at >= since,
                    TenantAutomationExecution.status == "success",
                ),
            )
        ).scalar_one()

        success_rate = (
            round(int(recent_success) / int(recent_total) * 100, 1)
            if int(recent_total) > 0
            else 100.0
        )
        health = min(
            100,
            max(
                0,
                int((active / max(len(flows), 1)) * 40 + success_rate * 0.5 + (10 if failed_flows == 0 else max(0, 10 - failed_flows * 5))),
            ),
        )

        return AutomationKpiResponse(
            health_score=health,
            active_count=active,
            paused_count=paused,
            disabled_count=disabled,
            failed_flow_count=failed_flows,
            total_executions_24h=int(recent_total),
            success_rate_overall=success_rate,
            total_flows=len(flows),
        )

    @staticmethod
    async def _load_flow(
        db: AsyncSession,
        tenant_id: UUID,
        flow_id: UUID,
    ) -> TenantAutomationFlow:
        row = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.id == flow_id,
                    TenantAutomationFlow.tenant_id == tenant_id,
                ),
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Automation flow not found")
        return row
