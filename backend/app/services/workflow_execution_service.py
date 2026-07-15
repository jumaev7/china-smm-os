"""Workflow execution — event-driven multi-step runs with idempotency."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.types import PlatformEvent
from app.models.workflow import (
    TenantWorkflow,
    TenantWorkflowExecution,
    TenantWorkflowStepExecution,
    TenantWorkflowVersion,
)
from app.services.automation_actions import execute_action
from app.services.automation_errors import classify_automation_error, safe_error_message, sanitize_payload_summary
from app.services.automation_execution_service import (
    AUTOMATION_DEPTH_KEY,
    AUTOMATION_ORIGIN_KEY,
    MAX_AUTOMATION_DEPTH,
)
from app.services.workflow_field_catalog import extract_allowlisted_fields
from app.services.workflow_rule_engine import WorkflowRuleEngine
from app.services.workflow_validation_service import WorkflowValidationService

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def workflow_event_deduplication_key(workflow_version_id: UUID, platform_event_id: UUID) -> str:
    return f"workflow-event:{workflow_version_id}:{platform_event_id}"


def _should_skip_event(event: PlatformEvent) -> str | None:
    if event.metadata.get(AUTOMATION_ORIGIN_KEY):
        return "automation_origin"
    depth = int(event.metadata.get(AUTOMATION_DEPTH_KEY, 0) or 0)
    if depth >= MAX_AUTOMATION_DEPTH:
        return "max_depth"
    return None


class WorkflowExecutionService:
    """
    Executes published tenant workflows for matching events.

    Transaction behavior (aligned with simple automations):
    - Runs synchronously inside the Event Bus caller's session.
    - Uses flush() only — commit is owned by PlatformEventService.emit or API layer.
    - Workflow/step failures are recorded without raising to the bus.
    - Domain rollback rolls back workflow execution rows from the same session.
    - Workflow failure never raises into domain operations.

    Idempotency: unique (tenant_id, workflow_id, deduplication_key) where
    key = workflow-event:{workflow_version_id}:{platform_event_id}.
    """

    @staticmethod
    async def process_event(db: AsyncSession, event: PlatformEvent) -> list[TenantWorkflowExecution]:
        skip_reason = _should_skip_event(event)
        if skip_reason:
            return []

        tenant_id = event.tenant_id
        if tenant_id is None:
            return []

        workflows = (
            await db.execute(
                select(TenantWorkflow).where(
                    TenantWorkflow.tenant_id == tenant_id,
                    TenantWorkflow.status == "published",
                    TenantWorkflow.trigger_event == event.event_type,
                    TenantWorkflow.active_version_id.is_not(None),
                ),
            )
        ).scalars().all()

        results: list[TenantWorkflowExecution] = []
        for workflow in workflows:
            execution = await WorkflowExecutionService._execute_workflow_for_event(
                db,
                workflow=workflow,
                event=event,
            )
            if execution is not None:
                results.append(execution)
        return results

    @staticmethod
    async def _execute_workflow_for_event(
        db: AsyncSession,
        *,
        workflow: TenantWorkflow,
        event: PlatformEvent,
    ) -> TenantWorkflowExecution | None:
        version = (
            await db.execute(
                select(TenantWorkflowVersion).where(
                    TenantWorkflowVersion.tenant_id == workflow.tenant_id,
                    TenantWorkflowVersion.id == workflow.active_version_id,
                    TenantWorkflowVersion.state == "published",
                ),
            )
        ).scalar_one_or_none()
        if version is None:
            return None

        validation = WorkflowValidationService.validate(version.definition)
        if not validation.valid or not validation.normalized_definition:
            logger.warning(
                "Skipping workflow %s — active version failed validation",
                workflow.id,
            )
            return None

        defn = validation.normalized_definition
        allowlisted = extract_allowlisted_fields(event.event_type, event.payload or {})
        evaluation = WorkflowRuleEngine.evaluate(
            event_type=event.event_type,
            payload=allowlisted,
            conditions=defn.get("conditions"),
        )

        dedup = workflow_event_deduplication_key(version.id, event.event_id)
        if not evaluation.matched:
            # Lightweight skip record — bounded, no step rows
            return await WorkflowExecutionService._create_or_get_execution(
                db,
                workflow=workflow,
                version=version,
                platform_event_id=event.event_id,
                execution_kind="event",
                deduplication_key=dedup,
                trigger_event=event.event_type,
                payload=allowlisted,
                status="skipped",
                matched_conditions={
                    "status": evaluation.status,
                    "failed_condition_ids": list(evaluation.failed_condition_ids)[:20],
                },
                result_summary={"skipped": True, "reason": "conditions_not_matched"},
                run_steps=False,
                steps=[],
            )

        return await WorkflowExecutionService._create_or_get_execution(
            db,
            workflow=workflow,
            version=version,
            platform_event_id=event.event_id,
            execution_kind="event",
            deduplication_key=dedup,
            trigger_event=event.event_type,
            payload=allowlisted,
            status="running",
            matched_conditions={
                "status": evaluation.status,
                "condition_count": evaluation.diagnostics.get("condition_count"),
            },
            result_summary=None,
            run_steps=True,
            steps=list(defn.get("steps") or []),
            full_payload=event.payload or {},
        )

    @staticmethod
    async def _create_or_get_execution(
        db: AsyncSession,
        *,
        workflow: TenantWorkflow,
        version: TenantWorkflowVersion,
        platform_event_id: UUID | None,
        execution_kind: str,
        deduplication_key: str,
        trigger_event: str,
        payload: dict[str, Any],
        status: str,
        matched_conditions: dict[str, Any] | None,
        result_summary: dict[str, Any] | None,
        run_steps: bool,
        steps: list[dict[str, Any]],
        full_payload: dict[str, Any] | None = None,
    ) -> TenantWorkflowExecution | None:
        now = _utcnow()
        row = TenantWorkflowExecution(
            id=uuid4(),
            tenant_id=workflow.tenant_id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            platform_event_id=platform_event_id,
            execution_kind=execution_kind,
            deduplication_key=deduplication_key,
            status=status,
            trigger_event=trigger_event,
            started_at=now,
            matched_conditions=matched_conditions,
            input_summary=sanitize_payload_summary(payload),
            result_summary=result_summary,
        )

        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            existing = (
                await db.execute(
                    select(TenantWorkflowExecution).where(
                        TenantWorkflowExecution.tenant_id == workflow.tenant_id,
                        TenantWorkflowExecution.workflow_id == workflow.id,
                        TenantWorkflowExecution.deduplication_key == deduplication_key,
                    ),
                )
            ).scalar_one_or_none()
            return existing

        if status == "skipped" or not run_steps:
            row.finished_at = _utcnow()
            row.duration_ms = int((row.finished_at - row.started_at).total_seconds() * 1000)
            await db.flush()
            return row

        return await WorkflowExecutionService._run_steps(
            db,
            execution=row,
            steps=steps,
            event_id=platform_event_id or uuid4(),
            event_type=trigger_event,
            payload=full_payload or payload,
        )

    @staticmethod
    async def _run_steps(
        db: AsyncSession,
        *,
        execution: TenantWorkflowExecution,
        steps: list[dict[str, Any]],
        event_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> TenantWorkflowExecution:
        started = time.perf_counter()
        action_payload = dict(payload)
        # Prevent nested automation loops from workflow-originated side effects
        action_payload.setdefault("test_context", {})

        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("id") or f"step_{index + 1}")
            action_type = str(step.get("action_type") or "")
            config = step.get("config") if isinstance(step.get("config"), dict) else {}

            execution.current_step_id = step_id
            step_started = _utcnow()
            step_row = TenantWorkflowStepExecution(
                id=uuid4(),
                tenant_id=execution.tenant_id,
                workflow_execution_id=execution.id,
                step_id=step_id,
                step_type="action",
                action_type=action_type,
                step_index=index,
                status="running",
                started_at=step_started,
                input_summary=sanitize_payload_summary({"action_type": action_type, "config_keys": sorted(config.keys())}),
            )
            db.add(step_row)
            await db.flush()

            try:
                result = await execute_action(
                    db,
                    action_type=action_type,
                    tenant_id=execution.tenant_id,
                    event_id=event_id,
                    event_type=event_type,
                    config=config,
                    payload=action_payload,
                )
            except Exception as exc:
                logger.exception("Workflow step %s failed", step_id)
                category, _retryable = classify_automation_error("internal_error", str(exc))
                step_row.status = "failed"
                step_row.error_code = "internal_error"
                step_row.error_category = category
                step_row.error_message = safe_error_message(str(exc))
                step_row.finished_at = _utcnow()
                step_row.duration_ms = int((step_row.finished_at - step_started).total_seconds() * 1000)

                execution.status = "failed"
                execution.error_code = step_row.error_code
                execution.error_category = step_row.error_category
                execution.error_message = step_row.error_message
                execution.finished_at = step_row.finished_at
                execution.duration_ms = int((time.perf_counter() - started) * 1000)
                execution.result_summary = {"failed_step_id": step_id, "steps_completed": index}
                await db.flush()
                return execution

            step_row.finished_at = _utcnow()
            step_row.duration_ms = int((step_row.finished_at - step_started).total_seconds() * 1000)
            if result.success:
                step_row.status = "success"
                step_row.result_summary = sanitize_payload_summary(result.payload)
            else:
                category, _ = classify_automation_error(result.error_code, result.error_message)
                step_row.status = "failed"
                step_row.error_code = result.error_code
                step_row.error_category = category
                step_row.error_message = safe_error_message(result.error_message)
                step_row.result_summary = sanitize_payload_summary(result.payload)

                # Phase 1 policy: stop_on_failure
                execution.status = "failed"
                execution.error_code = step_row.error_code
                execution.error_category = step_row.error_category
                execution.error_message = step_row.error_message
                execution.finished_at = step_row.finished_at
                execution.duration_ms = int((time.perf_counter() - started) * 1000)
                execution.result_summary = {"failed_step_id": step_id, "steps_completed": index}
                await db.flush()
                return execution

            await db.flush()

        execution.status = "success"
        execution.finished_at = _utcnow()
        execution.duration_ms = int((time.perf_counter() - started) * 1000)
        execution.current_step_id = None
        execution.result_summary = {"steps_completed": len(steps)}
        await db.flush()
        return execution
