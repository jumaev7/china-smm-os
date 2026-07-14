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
    AutomationExecutionDetail,
    AutomationExecutionListResponse,
    AutomationExecutionSummary,
    AutomationFlowDetail,
    AutomationFlowListResponse,
    AutomationFlowSummary,
    AutomationFlowUpdate,
    AutomationKpiResponse,
    AutomationManualRunResponse,
    AutomationRetryResponse,
    AutomationStatusChangeResponse,
)
from app.services.automation_errors import safe_error_message, sanitize_payload_summary
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
        "key": "system_publish_partial_failed_notify",
        "name": "Partial publishing failure alert",
        "description": (
            "When a publish attempt partially fails (some platforms succeed, others fail), "
            "create an in-app notification."
        ),
        "category": "publishing",
        "trigger_event": "tenant.content.publish_partial_failed",
        "action_type": "create_notification",
        "action_config": {
            "title": "Partial publish failure: {resource_name}",
            "body": (
                "Some platforms published successfully, but {failure_count} failed. "
                "Review publishing settings — this is not a total failure."
            ),
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
        max_retry_attempts=int(getattr(row, "max_retry_attempts", 1) or 1),
        retry_delay_seconds=int(getattr(row, "retry_delay_seconds", 60) or 60),
        retry_backoff=getattr(row, "retry_backoff", None) or "fixed",  # type: ignore[arg-type]
        last_executed_at=row.last_executed_at,
        last_execution_status=row.last_execution_status,  # type: ignore[arg-type]
        execution_count=count,
        success_rate=round(rate, 1),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _execution_to_summary_async(
    db: AsyncSession,
    row: TenantAutomationExecution,
    *,
    automation_name: str | None = None,
    flow: TenantAutomationFlow | None = None,
    max_retry_attempts: int | None = None,
    evaluate_eligibility: bool = True,
) -> AutomationExecutionSummary:
    payload = row.input_payload or {}
    retry_eligible = False
    retry_blocked_reason: str | None = None
    resolved_max = max_retry_attempts
    if resolved_max is None and flow is not None:
        resolved_max = int(getattr(flow, "max_retry_attempts", 1) or 1)

    if evaluate_eligibility and row.status == "failed" and flow is not None:
        eligibility = await AutomationExecutionService.evaluate_retry_eligibility(
            db,
            tenant_id=row.tenant_id,
            execution=row,
            flow=flow,
        )
        retry_eligible = bool(eligibility["eligible"])
        retry_blocked_reason = eligibility["reason"]
        resolved_max = int(eligibility["max_retry_attempts"])
    elif evaluate_eligibility and row.status == "failed" and flow is None:
        retry_blocked_reason = "Automation flow not found"

    return AutomationExecutionSummary(
        id=row.id,
        automation_flow_id=row.automation_flow_id,
        automation_name=automation_name,
        event_id=row.event_id,
        trigger_event=row.trigger_event,
        status=row.status,  # type: ignore[arg-type]
        execution_kind=getattr(row, "execution_kind", None) or "event",  # type: ignore[arg-type]
        root_execution_id=getattr(row, "root_execution_id", None),
        retry_of_execution_id=getattr(row, "retry_of_execution_id", None),
        retry_number=int(getattr(row, "retry_number", 0) or 0),
        max_retry_attempts=resolved_max,
        retry_eligible=retry_eligible,
        retry_blocked_reason=retry_blocked_reason,
        is_retryable=getattr(row, "is_retryable", None),
        error_category=getattr(row, "error_category", None),  # type: ignore[arg-type]
        started_at=row.started_at,
        finished_at=row.finished_at,
        duration_ms=row.duration_ms,
        error_code=row.error_code,
        error_message=safe_error_message(row.error_message),
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
                max_retry_attempts=1,
                retry_delay_seconds=60,
                retry_backoff="fixed",
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
        recent = [
            await _execution_to_summary_async(
                db,
                r,
                automation_name=row.name,
                flow=row,
            )
            for r in recent_rows
        ]
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
                select(
                    TenantAutomationExecution,
                    TenantAutomationFlow,
                )
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

        items: list[AutomationExecutionSummary] = []
        for exec_row, flow_row in rows:
            items.append(
                await _execution_to_summary_async(
                    db,
                    exec_row,
                    automation_name=flow_row.name,
                    flow=flow_row,
                    max_retry_attempts=int(getattr(flow_row, "max_retry_attempts", 1) or 1),
                    evaluate_eligibility=exec_row.status == "failed",
                ),
            )
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
    async def get_execution(
        db: AsyncSession,
        tenant_id: UUID,
        execution_id: UUID,
    ) -> AutomationExecutionDetail:
        execution = await AutomationService._load_execution(db, tenant_id, execution_id)
        flow = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.id == execution.automation_flow_id,
                    TenantAutomationFlow.tenant_id == tenant_id,
                ),
            )
        ).scalar_one_or_none()
        summary = await _execution_to_summary_async(
            db,
            execution,
            automation_name=flow.name if flow else None,
            flow=flow,
        )
        return AutomationExecutionDetail(
            **summary.model_dump(),
            input_summary=sanitize_payload_summary(execution.input_payload),
            result_summary=sanitize_payload_summary(execution.result_payload),
            action_type=flow.action_type if flow else None,  # type: ignore[arg-type]
        )

    @staticmethod
    async def retry_execution(
        db: AsyncSession,
        tenant_id: UUID,
        execution_id: UUID,
    ) -> AutomationRetryResponse:
        execution = await AutomationService._load_execution(db, tenant_id, execution_id)
        flow = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.id == execution.automation_flow_id,
                    TenantAutomationFlow.tenant_id == tenant_id,
                ),
            )
        ).scalar_one_or_none()
        if flow is None:
            raise HTTPException(status_code=404, detail="Automation flow not found")

        eligibility = await AutomationExecutionService.evaluate_retry_eligibility(
            db,
            tenant_id=tenant_id,
            execution=execution,
            flow=flow,
        )
        if not eligibility["eligible"]:
            raise HTTPException(
                status_code=409,
                detail=eligibility["reason"] or "Retry not allowed",
            )

        try:
            retry_row = await AutomationExecutionService.retry_execution(
                db,
                tenant_id,
                execution,
                flow,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        await db.flush()
        return AutomationRetryResponse(
            execution_id=retry_row.id,
            flow_id=flow.id,
            status=retry_row.status,  # type: ignore[arg-type]
            execution_kind=getattr(retry_row, "execution_kind", None) or "retry",  # type: ignore[arg-type]
            root_execution_id=retry_row.root_execution_id or retry_row.id,
            retry_of_execution_id=retry_row.retry_of_execution_id or execution.id,
            retry_number=int(getattr(retry_row, "retry_number", 0) or 0),
            duration_ms=retry_row.duration_ms,
            error_message=safe_error_message(retry_row.error_message),
            error_category=getattr(retry_row, "error_category", None),  # type: ignore[arg-type]
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

        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

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

        success_rate_overall = (
            round(int(recent_success) / int(recent_total) * 100, 1)
            if int(recent_total) > 0
            else 100.0
        )
        health = min(
            100,
            max(
                0,
                int(
                    (active / max(len(flows), 1)) * 40
                    + success_rate_overall * 0.5
                    + (10 if failed_flows == 0 else max(0, 10 - failed_flows * 5))
                ),
            ),
        )

        executions_today = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.created_at >= today_start,
                ),
            )
        ).scalar_one()
        success_count_today = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.created_at >= today_start,
                    TenantAutomationExecution.status == "success",
                ),
            )
        ).scalar_one()
        failure_count_today = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.created_at >= today_start,
                    TenantAutomationExecution.status == "failed",
                ),
            )
        ).scalar_one()
        settled = int(success_count_today) + int(failure_count_today)
        success_rate = (
            round(int(success_count_today) / settled * 100, 1) if settled > 0 else 100.0
        )
        retry_count_today = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.created_at >= today_start,
                    TenantAutomationExecution.execution_kind == "retry",
                ),
            )
        ).scalar_one()
        retry_success_count_today = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.created_at >= today_start,
                    TenantAutomationExecution.execution_kind == "retry",
                    TenantAutomationExecution.status == "success",
                ),
            )
        ).scalar_one()
        partial_publish_failures_today = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.created_at >= today_start,
                    TenantAutomationExecution.trigger_event
                    == "tenant.content.publish_partial_failed",
                ),
            )
        ).scalar_one()
        average_duration_ms = (
            await db.execute(
                select(func.avg(TenantAutomationExecution.duration_ms))
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.created_at >= today_start,
                    TenantAutomationExecution.status.in_(("success", "failed")),
                    TenantAutomationExecution.duration_ms.is_not(None),
                ),
            )
        ).scalar_one()

        return AutomationKpiResponse(
            health_score=health,
            active_count=active,
            paused_count=paused,
            disabled_count=disabled,
            failed_flow_count=failed_flows,
            total_executions_24h=int(recent_total),
            success_rate_overall=success_rate_overall,
            total_flows=len(flows),
            enabled_flows=active,
            executions_today=int(executions_today),
            success_count_today=int(success_count_today),
            failure_count_today=int(failure_count_today),
            success_rate=success_rate,
            retry_count_today=int(retry_count_today),
            retry_success_count_today=int(retry_success_count_today),
            partial_publish_failures_today=int(partial_publish_failures_today),
            average_duration_ms=(
                round(float(average_duration_ms), 1) if average_duration_ms is not None else None
            ),
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

    @staticmethod
    async def _load_execution(
        db: AsyncSession,
        tenant_id: UUID,
        execution_id: UUID,
    ) -> TenantAutomationExecution:
        row = (
            await db.execute(
                select(TenantAutomationExecution).where(
                    TenantAutomationExecution.id == execution_id,
                    TenantAutomationExecution.tenant_id == tenant_id,
                ),
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Automation execution not found")
        return row
