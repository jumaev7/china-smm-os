"""Automation flow execution — event-driven and manual test runs."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.types import PlatformEvent
from app.models.automation import (
    AUTOMATION_EXECUTION_STATUSES,
    TenantAutomationExecution,
    TenantAutomationFlow,
)
from app.services.automation_actions import execute_action, validate_action_config

logger = logging.getLogger(__name__)

MAX_AUTOMATION_DEPTH = 3
AUTOMATION_ORIGIN_KEY = "automation_origin"
AUTOMATION_DEPTH_KEY = "automation_depth"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _should_skip_event(event: PlatformEvent) -> str | None:
    if event.metadata.get(AUTOMATION_ORIGIN_KEY):
        return "automation_origin"
    depth = int(event.metadata.get(AUTOMATION_DEPTH_KEY, 0) or 0)
    if depth >= MAX_AUTOMATION_DEPTH:
        return "max_depth"
    return None


def _test_payload_for_flow(flow: TenantAutomationFlow) -> dict[str, Any]:
    """Fixed safe synthetic payloads for manual test runs — no arbitrary client input."""
    base = {
        "manual_test": True,
        "test_context": {
            "resource_name": "Test resource",
            "buyer_name": "Test Buyer",
            "platform": "instagram",
            "integration_name": "Instagram",
        },
    }
    if flow.trigger_event == "tenant.content.publish_failed":
        base.update({"resource_name": "Test post", "channel": "instagram"})
    elif flow.trigger_event == "tenant.integration.disconnected":
        base.update({"platform": "instagram", "integration_name": "Instagram"})
    elif flow.trigger_event == "tenant.buyer.created":
        base.update({"buyer_name": "Test Buyer", "company": "Test Co"})
    elif flow.trigger_event == "tenant.crm.lead_created":
        base.update({"lead_name": "Test Lead"})
    return base


class AutomationExecutionService:
    """
    Executes enabled tenant flows for matching events.

    Transaction behavior: runs synchronously inside the Event Bus caller's session.
    Uses flush() only — commit is owned by PlatformEventService.emit or API layer.
    Individual flow failures are recorded without raising to the bus.
    """

    @staticmethod
    async def process_event(db: AsyncSession, event: PlatformEvent) -> list[TenantAutomationExecution]:
        skip_reason = _should_skip_event(event)
        if skip_reason:
            return []

        tenant_id = event.tenant_id
        if tenant_id is None:
            return []

        flows = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.tenant_id == tenant_id,
                    TenantAutomationFlow.trigger_event == event.event_type,
                    TenantAutomationFlow.status == "enabled",
                ),
            )
        ).scalars().all()

        results: list[TenantAutomationExecution] = []
        for flow in flows:
            execution = await AutomationExecutionService._execute_flow(
                db,
                flow=flow,
                event_id=event.event_id,
                trigger_event=event.event_type,
                payload=event.payload or {},
                is_manual_test=bool(event.metadata.get("manual_test")),
            )
            if execution is not None:
                results.append(execution)
        return results

    @staticmethod
    async def run_manual_test(
        db: AsyncSession,
        tenant_id: UUID,
        flow: TenantAutomationFlow,
    ) -> TenantAutomationExecution:
        if flow.tenant_id != tenant_id:
            raise ValueError("Flow tenant mismatch")
        payload = _test_payload_for_flow(flow)
        event_id = payload.get("event_id")  # type: ignore[assignment]
        from uuid import uuid4

        execution = await AutomationExecutionService._execute_flow(
            db,
            flow=flow,
            event_id=uuid4(),
            trigger_event=flow.trigger_event,
            payload=payload,
            is_manual_test=True,
        )
        if execution is None:
            raise RuntimeError("Manual test execution was skipped")
        return execution

    @staticmethod
    async def _existing_execution(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        event_id: UUID,
    ) -> TenantAutomationExecution | None:
        return (
            await db.execute(
                select(TenantAutomationExecution).where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.automation_flow_id == flow_id,
                    TenantAutomationExecution.event_id == event_id,
                ),
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _execute_flow(
        db: AsyncSession,
        *,
        flow: TenantAutomationFlow,
        event_id: UUID,
        trigger_event: str,
        payload: dict[str, Any],
        is_manual_test: bool = False,
    ) -> TenantAutomationExecution | None:
        existing = await AutomationExecutionService._existing_execution(
            db,
            tenant_id=flow.tenant_id,
            flow_id=flow.id,
            event_id=event_id,
        )
        if existing is not None:
            return existing

        try:
            validate_action_config(flow.action_type, flow.action_config)
        except ValueError as exc:
            return await AutomationExecutionService._finalize_execution(
                db,
                flow=flow,
                event_id=event_id,
                trigger_event=trigger_event,
                payload=payload,
                status="failed",
                error_code="invalid_config",
                error_message=str(exc),
                started_at=_utcnow(),
                duration_ms=0,
                result_payload=None,
                is_manual_test=is_manual_test,
            )

        started_at = _utcnow()
        start = time.perf_counter()
        row = TenantAutomationExecution(
            tenant_id=flow.tenant_id,
            automation_flow_id=flow.id,
            event_id=event_id,
            trigger_event=trigger_event,
            status="running",
            started_at=started_at,
            input_payload={**payload, "manual_test": is_manual_test},
            attempt_number=1,
        )
        db.add(row)
        await db.flush()

        try:
            action_result = await execute_action(
                db,
                action_type=flow.action_type,
                tenant_id=flow.tenant_id,
                event_id=event_id,
                event_type=trigger_event,
                config=flow.action_config,
                payload=payload,
            )
        except Exception as exc:
            logger.exception("[Automation] flow %s action failed", flow.key)
            duration_ms = int((time.perf_counter() - start) * 1000)
            return await AutomationExecutionService._finalize_existing(
                db,
                row=row,
                flow=flow,
                status="failed",
                error_code="execution_error",
                error_message=str(exc),
                duration_ms=duration_ms,
                result_payload=None,
            )

        duration_ms = int((time.perf_counter() - start) * 1000)
        if action_result.success:
            return await AutomationExecutionService._finalize_existing(
                db,
                row=row,
                flow=flow,
                status="success",
                duration_ms=duration_ms,
                result_payload=action_result.payload,
            )
        return await AutomationExecutionService._finalize_existing(
            db,
            row=row,
            flow=flow,
            status="failed",
            error_code=action_result.error_code,
            error_message=action_result.error_message,
            duration_ms=duration_ms,
            result_payload=action_result.payload,
        )

    @staticmethod
    async def _finalize_existing(
        db: AsyncSession,
        *,
        row: TenantAutomationExecution,
        flow: TenantAutomationFlow,
        status: str,
        duration_ms: int,
        result_payload: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> TenantAutomationExecution:
        finished = _utcnow()
        row.status = status if status in AUTOMATION_EXECUTION_STATUSES else "failed"
        row.finished_at = finished
        row.duration_ms = duration_ms
        row.result_payload = result_payload
        row.error_code = error_code
        row.error_message = error_message
        flow.last_executed_at = finished
        flow.last_execution_status = row.status
        flow.updated_at = finished
        await db.flush()
        return row

    @staticmethod
    async def _finalize_execution(
        db: AsyncSession,
        *,
        flow: TenantAutomationFlow,
        event_id: UUID,
        trigger_event: str,
        payload: dict[str, Any],
        status: str,
        started_at: datetime,
        duration_ms: int,
        result_payload: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        is_manual_test: bool = False,
    ) -> TenantAutomationExecution:
        finished = _utcnow()
        row = TenantAutomationExecution(
            tenant_id=flow.tenant_id,
            automation_flow_id=flow.id,
            event_id=event_id,
            trigger_event=trigger_event,
            status=status,
            started_at=started_at,
            finished_at=finished,
            duration_ms=duration_ms,
            input_payload={**payload, "manual_test": is_manual_test},
            result_payload=result_payload,
            error_code=error_code,
            error_message=error_message,
            attempt_number=1,
        )
        db.add(row)
        flow.last_executed_at = finished
        flow.last_execution_status = status
        flow.updated_at = finished
        await db.flush()
        return row

    @staticmethod
    async def count_success_rate(
        db: AsyncSession,
        tenant_id: UUID,
        flow_id: UUID,
    ) -> tuple[int, float]:
        total = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.automation_flow_id == flow_id,
                    TenantAutomationExecution.status.in_(("success", "failed")),
                ),
            )
        ).scalar_one()
        success = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.automation_flow_id == flow_id,
                    TenantAutomationExecution.status == "success",
                ),
            )
        ).scalar_one()
        rate = (int(success) / int(total) * 100.0) if int(total) > 0 else 0.0
        return int(total), rate
