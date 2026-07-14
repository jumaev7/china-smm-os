"""Automation flow execution — event-driven, manual test, and controlled retries."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.types import PlatformEvent
from app.models.automation import (
    AUTOMATION_EXECUTION_KINDS,
    AUTOMATION_EXECUTION_STATUSES,
    DEFAULT_MAX_RETRY_ATTEMPTS,
    TenantAutomationExecution,
    TenantAutomationFlow,
)
from app.services.automation_actions import execute_action, validate_action_config
from app.services.automation_errors import (
    action_type_allowed,
    classify_automation_error,
    clamp_max_retry_attempts,
    safe_error_message,
)

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


def event_deduplication_key(event_id: UUID) -> str:
    return f"event:{event_id}"


def manual_deduplication_key(execution_id: UUID) -> str:
    return f"manual:{execution_id}"


def retry_deduplication_key(root_execution_id: UUID, retry_number: int) -> str:
    return f"retry:{root_execution_id}:{retry_number}"


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
    elif flow.trigger_event == "tenant.content.publish_partial_failed":
        base.update({
            "resource_name": "Test post",
            "success_count": 1,
            "failure_count": 1,
            "successful_platforms": ["instagram"],
            "failed_platforms": [{"platform": "facebook", "error": "adapter failure"}],
        })
    elif flow.trigger_event == "tenant.integration.disconnected":
        base.update({"platform": "instagram", "integration_name": "Instagram"})
    elif flow.trigger_event == "tenant.buyer.created":
        base.update({"buyer_name": "Test Buyer", "company": "Test Co"})
    elif flow.trigger_event == "tenant.crm.lead_created":
        base.update({"lead_name": "Test Lead"})
    return base


def _apply_error_classification(
    row: TenantAutomationExecution,
    *,
    error_code: str | None,
    error_message: str | None,
) -> None:
    category, retryable = classify_automation_error(error_code, error_message)
    row.error_code = error_code
    row.error_message = safe_error_message(error_message)
    row.error_category = category
    row.is_retryable = retryable if row.status == "failed" else False


class AutomationExecutionService:
    """
    Executes enabled tenant flows for matching events.

    Transaction behavior: runs synchronously inside the Event Bus caller's session.
    Uses flush() only — commit is owned by PlatformEventService.emit or API layer.
    Individual flow failures are recorded without raising to the bus.

    Idempotency: unique (tenant_id, automation_flow_id, deduplication_key).
    Concurrent duplicate inserts resolve via savepoint + IntegrityError; losers
    return the winning execution without re-running the action.
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
                execution_kind="event",
                deduplication_key=event_deduplication_key(event.event_id),
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
        execution_id = uuid4()
        execution = await AutomationExecutionService._execute_flow(
            db,
            flow=flow,
            event_id=uuid4(),
            trigger_event=flow.trigger_event,
            payload=payload,
            execution_kind="manual",
            deduplication_key=manual_deduplication_key(execution_id),
            predetermined_id=execution_id,
        )
        if execution is None:
            raise RuntimeError("Manual test execution was skipped")
        return execution

    @staticmethod
    async def retry_execution(
        db: AsyncSession,
        tenant_id: UUID,
        failed_execution: TenantAutomationExecution,
        flow: TenantAutomationFlow,
    ) -> TenantAutomationExecution:
        """Create and run a new linked retry execution from a failed row."""
        eligibility = await AutomationExecutionService.evaluate_retry_eligibility(
            db,
            tenant_id=tenant_id,
            execution=failed_execution,
            flow=flow,
        )
        if not eligibility["eligible"]:
            raise ValueError(eligibility["reason"] or "Retry not allowed")

        root_id = failed_execution.root_execution_id or failed_execution.id
        next_retry = int(eligibility["next_retry_number"])
        payload = dict(failed_execution.input_payload or {})
        payload.pop("manual_test", None)
        payload["retry_of_execution_id"] = str(failed_execution.id)
        payload["root_execution_id"] = str(root_id)

        execution = await AutomationExecutionService._execute_flow(
            db,
            flow=flow,
            event_id=failed_execution.event_id,
            trigger_event=failed_execution.trigger_event,
            payload=payload,
            execution_kind="retry",
            deduplication_key=retry_deduplication_key(root_id, next_retry),
            root_execution_id=root_id,
            retry_of_execution_id=failed_execution.id,
            retry_number=next_retry,
        )
        if execution is None:
            raise RuntimeError("Retry execution was skipped")
        return execution

    @staticmethod
    async def evaluate_retry_eligibility(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        execution: TenantAutomationExecution,
        flow: TenantAutomationFlow | None = None,
    ) -> dict[str, Any]:
        max_retries = clamp_max_retry_attempts(
            getattr(flow, "max_retry_attempts", None) if flow is not None else DEFAULT_MAX_RETRY_ATTEMPTS,
        )
        root_id = execution.root_execution_id or execution.id
        retry_count = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.root_execution_id == root_id,
                    TenantAutomationExecution.execution_kind == "retry",
                ),
            )
        ).scalar_one()
        next_retry_number = int(retry_count) + 1

        reason: str | None = None
        if execution.tenant_id != tenant_id:
            reason = "Execution not found"
        elif execution.status != "failed":
            reason = "Only failed executions can be retried"
        elif flow is None:
            reason = "Automation flow not found"
        elif flow.tenant_id != tenant_id or flow.id != execution.automation_flow_id:
            reason = "Automation flow not found"
        elif not action_type_allowed(flow.action_type):
            reason = "Action type is not allowlisted"
        elif next_retry_number > max_retries:
            reason = f"Retry limit reached ({max_retries})"
        elif execution.is_retryable is False:
            reason = "Failure is not retryable"
        elif execution.is_retryable is None and execution.error_code:
            _, retryable = classify_automation_error(execution.error_code, execution.error_message)
            if not retryable:
                reason = "Failure is not retryable"
        elif execution.is_retryable is None and not execution.error_code:
            reason = "Failure is not classified as retryable"

        return {
            "eligible": reason is None,
            "reason": reason,
            "is_retryable": bool(execution.is_retryable) if execution.is_retryable is not None else False,
            "retry_number": execution.retry_number,
            "retry_count": int(retry_count),
            "max_retry_attempts": max_retries,
            "next_retry_number": next_retry_number,
            "root_execution_id": root_id,
        }

    @staticmethod
    async def _existing_by_dedup(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        deduplication_key: str,
    ) -> TenantAutomationExecution | None:
        return (
            await db.execute(
                select(TenantAutomationExecution).where(
                    TenantAutomationExecution.tenant_id == tenant_id,
                    TenantAutomationExecution.automation_flow_id == flow_id,
                    TenantAutomationExecution.deduplication_key == deduplication_key,
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
        execution_kind: str,
        deduplication_key: str,
        predetermined_id: UUID | None = None,
        root_execution_id: UUID | None = None,
        retry_of_execution_id: UUID | None = None,
        retry_number: int = 0,
    ) -> TenantAutomationExecution | None:
        if execution_kind not in AUTOMATION_EXECUTION_KINDS:
            execution_kind = "event"

        existing = await AutomationExecutionService._existing_by_dedup(
            db,
            tenant_id=flow.tenant_id,
            flow_id=flow.id,
            deduplication_key=deduplication_key,
        )
        if existing is not None:
            return existing

        is_manual = execution_kind == "manual"
        try:
            validate_action_config(flow.action_type, flow.action_config)
        except ValueError as exc:
            return await AutomationExecutionService._insert_terminal_execution(
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
                execution_kind=execution_kind,
                deduplication_key=deduplication_key,
                predetermined_id=predetermined_id,
                root_execution_id=root_execution_id,
                retry_of_execution_id=retry_of_execution_id,
                retry_number=retry_number,
                is_manual_test=is_manual,
            )

        started_at = _utcnow()
        start = time.perf_counter()
        execution_id = predetermined_id or uuid4()
        row = TenantAutomationExecution(
            id=execution_id,
            tenant_id=flow.tenant_id,
            automation_flow_id=flow.id,
            event_id=event_id,
            trigger_event=trigger_event,
            status="running",
            started_at=started_at,
            input_payload={**payload, "manual_test": is_manual},
            attempt_number=retry_number + 1,
            execution_kind=execution_kind,
            deduplication_key=deduplication_key,
            root_execution_id=root_execution_id or execution_id,
            retry_of_execution_id=retry_of_execution_id,
            retry_number=retry_number,
        )

        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            existing = await AutomationExecutionService._existing_by_dedup(
                db,
                tenant_id=flow.tenant_id,
                flow_id=flow.id,
                deduplication_key=deduplication_key,
            )
            if existing is not None:
                return existing
            raise

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
        if row.status == "failed":
            _apply_error_classification(row, error_code=error_code, error_message=error_message)
        else:
            row.error_code = None
            row.error_message = None
            row.error_category = None
            row.is_retryable = False
        if row.root_execution_id is None:
            row.root_execution_id = row.id
        flow.last_executed_at = finished
        flow.last_execution_status = row.status
        flow.updated_at = finished
        await db.flush()
        if row.status == "failed" and row.is_retryable:
            from app.services.automation_job_service import AutomationJobService

            await AutomationJobService.enqueue_automatic_retry(db, execution=row, flow=flow)
        return row

    @staticmethod
    async def _insert_terminal_execution(
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
        execution_kind: str = "event",
        deduplication_key: str,
        predetermined_id: UUID | None = None,
        root_execution_id: UUID | None = None,
        retry_of_execution_id: UUID | None = None,
        retry_number: int = 0,
        is_manual_test: bool = False,
    ) -> TenantAutomationExecution:
        finished = _utcnow()
        execution_id = predetermined_id or uuid4()
        row = TenantAutomationExecution(
            id=execution_id,
            tenant_id=flow.tenant_id,
            automation_flow_id=flow.id,
            event_id=event_id,
            trigger_event=trigger_event,
            status=status if status in AUTOMATION_EXECUTION_STATUSES else "failed",
            started_at=started_at,
            finished_at=finished,
            duration_ms=duration_ms,
            input_payload={**payload, "manual_test": is_manual_test},
            result_payload=result_payload,
            attempt_number=retry_number + 1,
            execution_kind=execution_kind,
            deduplication_key=deduplication_key,
            root_execution_id=root_execution_id or execution_id,
            retry_of_execution_id=retry_of_execution_id,
            retry_number=retry_number,
        )
        if row.status == "failed":
            _apply_error_classification(row, error_code=error_code, error_message=error_message)

        try:
            async with db.begin_nested():
                db.add(row)
                flow.last_executed_at = finished
                flow.last_execution_status = row.status
                flow.updated_at = finished
                await db.flush()
        except IntegrityError:
            existing = await AutomationExecutionService._existing_by_dedup(
                db,
                tenant_id=flow.tenant_id,
                flow_id=flow.id,
                deduplication_key=deduplication_key,
            )
            if existing is not None:
                return existing
            raise
        if row.status == "failed" and row.is_retryable:
            from app.services.automation_job_service import AutomationJobService

            await AutomationJobService.enqueue_automatic_retry(db, execution=row, flow=flow)
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
