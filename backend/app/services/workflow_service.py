"""Tenant workflow lifecycle — draft, validate, publish, pause, archive, clone."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import AUTOMATION_ACTION_TYPES
from app.models.workflow import (
    MAX_CONDITION_DEPTH,
    MAX_TOTAL_CONDITIONS,
    MAX_WORKFLOW_STEPS,
    TenantWorkflow,
    TenantWorkflowExecution,
    TenantWorkflowVersion,
)
from app.schemas.workflow import (
    WorkflowCatalogResponse,
    WorkflowDetail,
    WorkflowExecutionDetail,
    WorkflowExecutionListResponse,
    WorkflowExecutionSummary,
    WorkflowListResponse,
    WorkflowPublishResponse,
    WorkflowStatusChangeResponse,
    WorkflowStepExecutionSummary,
    WorkflowSummary,
    WorkflowTestResponse,
    WorkflowValidateResponse,
    WorkflowValidationErrorItem,
    WorkflowVersionDetail,
    WorkflowVersionListResponse,
    WorkflowVersionSummary,
)
from app.services.automation_errors import sanitize_payload_summary
from app.services.workflow_field_catalog import (
    catalog_as_api,
    extract_allowlisted_fields,
    list_workflow_trigger_events,
)
from app.services.workflow_rule_engine import WorkflowRuleEngine
from app.services.workflow_validation_service import WorkflowValidationService

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,118}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "workflow"
    return base[:100]


def _empty_definition(event: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "trigger": {"event": event or list_workflow_trigger_events()[0]},
        "conditions": {"operator": "all", "items": []},
        "steps": [],
        "failure_policy": "stop_on_failure",
    }


def _validation_errors_as_items(raw: list[dict[str, Any]] | None) -> list[WorkflowValidationErrorItem]:
    if not raw:
        return []
    return [
        WorkflowValidationErrorItem(
            code=str(item.get("code", "invalid")),
            message=str(item.get("message", "")),
            path=item.get("path"),
        )
        for item in raw
        if isinstance(item, dict)
    ]


class WorkflowService:
    @staticmethod
    async def get_catalog() -> WorkflowCatalogResponse:
        events = catalog_as_api()
        return WorkflowCatalogResponse(
            events=events,
            action_types=sorted(AUTOMATION_ACTION_TYPES),
            limits={
                "max_steps": MAX_WORKFLOW_STEPS,
                "max_condition_depth": MAX_CONDITION_DEPTH,
                "max_total_conditions": MAX_TOTAL_CONDITIONS,
            },
        )

    @staticmethod
    async def list_workflows(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> WorkflowListResponse:
        filters = [TenantWorkflow.tenant_id == tenant_id]
        if status:
            filters.append(TenantWorkflow.status == status)
        total = (
            await db.execute(select(func.count()).select_from(TenantWorkflow).where(*filters))
        ).scalar_one()
        rows = (
            await db.execute(
                select(TenantWorkflow)
                .where(*filters)
                .order_by(TenantWorkflow.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size),
            )
        ).scalars().all()
        items = []
        for row in rows:
            items.append(await WorkflowService._to_summary(db, row))
        return WorkflowListResponse(items=items, total=int(total))

    @staticmethod
    async def create_workflow(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        name: str,
        description: str | None = None,
        key: str | None = None,
        definition: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> WorkflowDetail:
        workflow_key = key or _slugify(name)
        if not _KEY_RE.match(workflow_key):
            raise HTTPException(status_code=400, detail="Invalid workflow key")

        existing = (
            await db.execute(
                select(TenantWorkflow.id).where(
                    TenantWorkflow.tenant_id == tenant_id,
                    TenantWorkflow.key == workflow_key,
                ),
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Workflow key already exists")

        defn = definition or _empty_definition()
        validation = WorkflowValidationService.validate(defn)
        # Allow incomplete drafts to be created; still store validation state.
        stored = validation.normalized_definition if validation.valid else defn

        workflow = TenantWorkflow(
            id=uuid4(),
            tenant_id=tenant_id,
            key=workflow_key,
            name=name.strip(),
            description=description,
            status="draft",
            draft_revision=1,
            trigger_event=(stored.get("trigger") or {}).get("event"),
            failure_policy="stop_on_failure",
            created_by=created_by,
        )
        db.add(workflow)
        await db.flush()

        version = TenantWorkflowVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            version_number=1,
            state="draft",
            definition=stored,
            definition_hash=validation.definition_hash,
            validation_status="valid" if validation.valid else ("invalid" if validation.errors else "pending"),
            validation_errors=validation.to_error_dicts() or None,
            created_by=created_by,
        )
        db.add(version)
        await db.flush()
        workflow.draft_version_id = version.id
        await db.flush()
        return await WorkflowService.get_workflow(db, tenant_id, workflow.id)

    @staticmethod
    async def get_workflow(db: AsyncSession, tenant_id: UUID, workflow_id: UUID) -> WorkflowDetail:
        workflow = await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        return await WorkflowService._to_detail(db, workflow)

    @staticmethod
    async def update_workflow(
        db: AsyncSession,
        tenant_id: UUID,
        workflow_id: UUID,
        *,
        draft_revision: int,
        name: str | None = None,
        description: str | None = None,
        definition: dict[str, Any] | None = None,
        updated_by: UUID | None = None,
    ) -> WorkflowDetail:
        workflow = await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        if workflow.status == "archived":
            raise HTTPException(status_code=409, detail="Archived workflows cannot be edited")
        if workflow.draft_revision != draft_revision:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "stale_draft_revision",
                    "message": "Draft was updated elsewhere; reload and retry",
                    "current_revision": workflow.draft_revision,
                },
            )

        if name is not None:
            workflow.name = name.strip()
        if description is not None:
            workflow.description = description

        draft = await WorkflowService._ensure_mutable_draft(db, workflow, updated_by=updated_by)
        if definition is not None:
            validation = WorkflowValidationService.validate(definition)
            stored = validation.normalized_definition if validation.valid else definition
            draft.definition = stored
            draft.definition_hash = validation.definition_hash
            draft.validation_status = "valid" if validation.valid else "invalid"
            draft.validation_errors = validation.to_error_dicts() or None
            workflow.trigger_event = (stored.get("trigger") or {}).get("event")

        workflow.draft_revision = int(workflow.draft_revision) + 1
        workflow.updated_at = _utcnow()
        await db.flush()
        return await WorkflowService.get_workflow(db, tenant_id, workflow_id)

    @staticmethod
    async def validate_workflow(
        db: AsyncSession,
        tenant_id: UUID,
        workflow_id: UUID,
        *,
        definition: dict[str, Any] | None = None,
    ) -> WorkflowValidateResponse:
        workflow = await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        if definition is None:
            draft = await WorkflowService._get_version(db, tenant_id, workflow.draft_version_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="Draft version not found")
            definition = draft.definition
        result = WorkflowValidationService.validate(definition)
        return WorkflowValidateResponse(
            valid=result.valid,
            errors=_validation_errors_as_items(result.to_error_dicts()),
            definition_hash=result.definition_hash,
            normalized_definition=result.normalized_definition,
        )

    @staticmethod
    async def publish_workflow(
        db: AsyncSession,
        tenant_id: UUID,
        workflow_id: UUID,
        *,
        published_by: UUID | None = None,
    ) -> WorkflowPublishResponse:
        workflow = await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        if workflow.status == "archived":
            raise HTTPException(status_code=409, detail="Archived workflows cannot be published")

        draft = await WorkflowService._get_version(db, tenant_id, workflow.draft_version_id)
        if draft is None or draft.state != "draft":
            raise HTTPException(status_code=409, detail="No draft version to publish")

        validation = WorkflowValidationService.validate(draft.definition)
        if not validation.valid or not validation.normalized_definition:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "validation_failed",
                    "errors": validation.to_error_dicts(),
                },
            )

        # Freeze draft into published immutable version (new row if draft already published once)
        now = _utcnow()
        next_number = await WorkflowService._next_version_number(db, workflow.id)

        if draft.state == "draft" and draft.version_number == next_number - 1 and draft.published_at is None:
            # Promote current draft in place to published
            published = draft
            published.state = "published"
            published.definition = validation.normalized_definition
            published.definition_hash = validation.definition_hash
            published.validation_status = "valid"
            published.validation_errors = None
            published.published_at = now
        else:
            published = TenantWorkflowVersion(
                id=uuid4(),
                tenant_id=tenant_id,
                workflow_id=workflow.id,
                version_number=next_number,
                state="published",
                definition=validation.normalized_definition,
                definition_hash=validation.definition_hash,
                validation_status="valid",
                validation_errors=None,
                created_by=published_by,
                published_at=now,
            )
            db.add(published)
            await db.flush()

        # Supersede previous active
        if workflow.active_version_id and workflow.active_version_id != published.id:
            previous = await WorkflowService._get_version(db, tenant_id, workflow.active_version_id)
            if previous is not None and previous.state == "published":
                previous.state = "superseded"

        workflow.active_version_id = published.id
        workflow.trigger_event = validation.normalized_definition["trigger"]["event"]
        workflow.status = "published"
        workflow.updated_at = now

        # Create a new draft copy for further edits (published stays immutable)
        new_draft = TenantWorkflowVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            version_number=published.version_number + 1,
            state="draft",
            definition=dict(validation.normalized_definition),
            definition_hash=validation.definition_hash,
            validation_status="valid",
            validation_errors=None,
            created_by=published_by,
        )
        db.add(new_draft)
        await db.flush()
        workflow.draft_version_id = new_draft.id
        workflow.draft_revision = int(workflow.draft_revision) + 1
        # Re-touch updated_at so this second UPDATE carries an explicit value —
        # otherwise the column's onupdate=func.now() default fires again without
        # RETURNING, leaving the ORM attribute expired for the response below.
        workflow.updated_at = _utcnow()
        await db.flush()

        return WorkflowPublishResponse(
            id=workflow.id,
            status=workflow.status,  # type: ignore[arg-type]
            draft_revision=workflow.draft_revision,
            updated_at=workflow.updated_at,
            active_version_id=workflow.active_version_id,
            draft_version_id=workflow.draft_version_id,
            published_version_id=published.id,
            published_version_number=published.version_number,
            definition_hash=published.definition_hash,
        )

    @staticmethod
    async def pause_workflow(db: AsyncSession, tenant_id: UUID, workflow_id: UUID) -> WorkflowStatusChangeResponse:
        workflow = await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        if workflow.status == "archived":
            raise HTTPException(status_code=409, detail="Archived workflows cannot be paused")
        if workflow.status not in {"published", "paused"}:
            raise HTTPException(status_code=409, detail="Only published workflows can be paused")
        workflow.status = "paused"
        workflow.updated_at = _utcnow()
        await db.flush()
        return WorkflowService._status_response(workflow)

    @staticmethod
    async def resume_workflow(db: AsyncSession, tenant_id: UUID, workflow_id: UUID) -> WorkflowStatusChangeResponse:
        workflow = await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        if workflow.status != "paused":
            raise HTTPException(status_code=409, detail="Only paused workflows can be resumed")
        if not workflow.active_version_id:
            raise HTTPException(status_code=409, detail="No published version to resume")
        workflow.status = "published"
        workflow.updated_at = _utcnow()
        await db.flush()
        return WorkflowService._status_response(workflow)

    @staticmethod
    async def archive_workflow(db: AsyncSession, tenant_id: UUID, workflow_id: UUID) -> WorkflowStatusChangeResponse:
        workflow = await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        if workflow.status == "archived":
            return WorkflowService._status_response(workflow)
        workflow.status = "archived"
        workflow.archived_at = _utcnow()
        workflow.updated_at = workflow.archived_at
        await db.flush()
        return WorkflowService._status_response(workflow)

    @staticmethod
    async def clone_workflow(
        db: AsyncSession,
        tenant_id: UUID,
        workflow_id: UUID,
        *,
        created_by: UUID | None = None,
    ) -> WorkflowDetail:
        source = await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        source_version = await WorkflowService._get_version(
            db,
            tenant_id,
            source.draft_version_id or source.active_version_id,
        )
        if source_version is None:
            raise HTTPException(status_code=404, detail="Source workflow version not found")

        stamp = int(_utcnow().timestamp())
        return await WorkflowService.create_workflow(
            db,
            tenant_id,
            name=f"{source.name} (copy)",
            description=source.description,
            key=f"{source.key}_copy_{stamp}"[:120],
            definition=dict(source_version.definition or {}),
            created_by=created_by,
        )

    @staticmethod
    async def list_versions(
        db: AsyncSession,
        tenant_id: UUID,
        workflow_id: UUID,
    ) -> WorkflowVersionListResponse:
        await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        rows = (
            await db.execute(
                select(TenantWorkflowVersion)
                .where(
                    TenantWorkflowVersion.tenant_id == tenant_id,
                    TenantWorkflowVersion.workflow_id == workflow_id,
                )
                .order_by(TenantWorkflowVersion.version_number.desc()),
            )
        ).scalars().all()
        return WorkflowVersionListResponse(
            items=[WorkflowService._to_version_summary(r) for r in rows],
            total=len(rows),
        )

    @staticmethod
    async def get_version(
        db: AsyncSession,
        tenant_id: UUID,
        workflow_id: UUID,
        version_id: UUID,
    ) -> WorkflowVersionDetail:
        await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        row = await WorkflowService._get_version(db, tenant_id, version_id)
        if row is None or row.workflow_id != workflow_id:
            raise HTTPException(status_code=404, detail="Workflow version not found")
        summary = WorkflowService._to_version_summary(row)
        return WorkflowVersionDetail(
            **summary.model_dump(),
            definition=dict(row.definition or {}),
            validation_errors=row.validation_errors,
        )

    @staticmethod
    async def list_executions(
        db: AsyncSession,
        tenant_id: UUID,
        workflow_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> WorkflowExecutionListResponse:
        workflow = await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        total = (
            await db.execute(
                select(func.count())
                .select_from(TenantWorkflowExecution)
                .where(
                    TenantWorkflowExecution.tenant_id == tenant_id,
                    TenantWorkflowExecution.workflow_id == workflow_id,
                ),
            )
        ).scalar_one()
        rows = (
            await db.execute(
                select(TenantWorkflowExecution)
                .where(
                    TenantWorkflowExecution.tenant_id == tenant_id,
                    TenantWorkflowExecution.workflow_id == workflow_id,
                )
                .order_by(TenantWorkflowExecution.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size),
            )
        ).scalars().all()
        return WorkflowExecutionListResponse(
            items=[
                WorkflowExecutionSummary(
                    id=r.id,
                    workflow_id=r.workflow_id,
                    workflow_version_id=r.workflow_version_id,
                    workflow_name=workflow.name,
                    platform_event_id=r.platform_event_id,
                    execution_kind=r.execution_kind,  # type: ignore[arg-type]
                    status=r.status,  # type: ignore[arg-type]
                    trigger_event=r.trigger_event,
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                    duration_ms=r.duration_ms,
                    current_step_id=r.current_step_id,
                    error_code=r.error_code,
                    error_message=r.error_message,
                    created_at=r.created_at,
                )
                for r in rows
            ],
            total=int(total),
        )

    @staticmethod
    async def get_execution(
        db: AsyncSession,
        tenant_id: UUID,
        execution_id: UUID,
    ) -> WorkflowExecutionDetail:
        from app.models.workflow import TenantWorkflowStepExecution

        row = (
            await db.execute(
                select(TenantWorkflowExecution).where(
                    TenantWorkflowExecution.tenant_id == tenant_id,
                    TenantWorkflowExecution.id == execution_id,
                ),
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow execution not found")

        workflow = await WorkflowService._require_workflow(db, tenant_id, row.workflow_id)
        steps = (
            await db.execute(
                select(TenantWorkflowStepExecution)
                .where(
                    TenantWorkflowStepExecution.tenant_id == tenant_id,
                    TenantWorkflowStepExecution.workflow_execution_id == row.id,
                )
                .order_by(TenantWorkflowStepExecution.step_index.asc()),
            )
        ).scalars().all()

        return WorkflowExecutionDetail(
            id=row.id,
            workflow_id=row.workflow_id,
            workflow_version_id=row.workflow_version_id,
            workflow_name=workflow.name,
            platform_event_id=row.platform_event_id,
            execution_kind=row.execution_kind,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            trigger_event=row.trigger_event,
            started_at=row.started_at,
            finished_at=row.finished_at,
            duration_ms=row.duration_ms,
            current_step_id=row.current_step_id,
            error_code=row.error_code,
            error_message=row.error_message,
            created_at=row.created_at,
            matched_conditions=row.matched_conditions,
            input_summary=sanitize_payload_summary(row.input_summary),
            result_summary=sanitize_payload_summary(row.result_summary),
            steps=[
                WorkflowStepExecutionSummary(
                    id=s.id,
                    step_id=s.step_id,
                    step_type=s.step_type,
                    action_type=s.action_type,
                    step_index=s.step_index,
                    status=s.status,  # type: ignore[arg-type]
                    started_at=s.started_at,
                    finished_at=s.finished_at,
                    duration_ms=s.duration_ms,
                    error_code=s.error_code,
                    error_message=s.error_message,
                    input_summary=sanitize_payload_summary(s.input_summary),
                    result_summary=sanitize_payload_summary(s.result_summary),
                )
                for s in steps
            ],
        )

    @staticmethod
    async def test_workflow(
        db: AsyncSession,
        tenant_id: UUID,
        workflow_id: UUID,
        *,
        mode: str = "evaluate_only",
        version_id: UUID | None = None,
        synthetic_payload: dict[str, Any] | None = None,
    ) -> WorkflowTestResponse:
        if mode != "evaluate_only":
            raise HTTPException(status_code=400, detail="Only evaluate_only test mode is supported")

        workflow = await WorkflowService._require_workflow(db, tenant_id, workflow_id)
        version = await WorkflowService._get_version(
            db,
            tenant_id,
            version_id or workflow.draft_version_id or workflow.active_version_id,
        )
        if version is None or version.workflow_id != workflow.id:
            raise HTTPException(status_code=404, detail="Workflow version not found")

        validation = WorkflowValidationService.validate(version.definition)
        if not validation.valid or not validation.normalized_definition:
            return WorkflowTestResponse(
                mode="evaluate_only",
                valid=False,
                validation_errors=_validation_errors_as_items(validation.to_error_dicts()),
            )

        defn = validation.normalized_definition
        event_type = defn["trigger"]["event"]
        # Only catalog-approved synthetic fields accepted
        allowlisted = extract_allowlisted_fields(event_type, synthetic_payload or {})
        evaluation = WorkflowRuleEngine.evaluate(
            event_type=event_type,
            payload=allowlisted,
            conditions=defn.get("conditions"),
        )
        planned = [
            {
                "id": step.get("id"),
                "type": step.get("type"),
                "action_type": step.get("action_type"),
            }
            for step in defn.get("steps") or []
            if isinstance(step, dict)
        ]
        return WorkflowTestResponse(
            mode="evaluate_only",
            valid=True,
            matched=evaluation.matched,
            evaluation_status=evaluation.status,
            planned_steps=planned if evaluation.matched else [],
            evaluated_conditions=[
                {"condition_id": r.condition_id, "matched": r.matched, "reason": r.reason}
                for r in evaluation.evaluated_conditions
            ],
            failed_condition_ids=list(evaluation.failed_condition_ids),
            diagnostics=dict(evaluation.diagnostics),
        )

    # ── internals ──────────────────────────────────────────────────────────

    @staticmethod
    async def _require_workflow(db: AsyncSession, tenant_id: UUID, workflow_id: UUID) -> TenantWorkflow:
        row = (
            await db.execute(
                select(TenantWorkflow).where(
                    TenantWorkflow.tenant_id == tenant_id,
                    TenantWorkflow.id == workflow_id,
                ),
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return row

    @staticmethod
    async def _get_version(
        db: AsyncSession,
        tenant_id: UUID,
        version_id: UUID | None,
    ) -> TenantWorkflowVersion | None:
        if version_id is None:
            return None
        return (
            await db.execute(
                select(TenantWorkflowVersion).where(
                    TenantWorkflowVersion.tenant_id == tenant_id,
                    TenantWorkflowVersion.id == version_id,
                ),
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _next_version_number(db: AsyncSession, workflow_id: UUID) -> int:
        current = (
            await db.execute(
                select(func.max(TenantWorkflowVersion.version_number)).where(
                    TenantWorkflowVersion.workflow_id == workflow_id,
                ),
            )
        ).scalar_one()
        return int(current or 0) + 1

    @staticmethod
    async def _ensure_mutable_draft(
        db: AsyncSession,
        workflow: TenantWorkflow,
        *,
        updated_by: UUID | None = None,
    ) -> TenantWorkflowVersion:
        draft = await WorkflowService._get_version(db, workflow.tenant_id, workflow.draft_version_id)
        if draft is not None and draft.state == "draft":
            return draft

        # Editing a published workflow without a draft: create new draft from active
        source = draft or await WorkflowService._get_version(
            db, workflow.tenant_id, workflow.active_version_id,
        )
        next_number = await WorkflowService._next_version_number(db, workflow.id)
        new_draft = TenantWorkflowVersion(
            id=uuid4(),
            tenant_id=workflow.tenant_id,
            workflow_id=workflow.id,
            version_number=next_number,
            state="draft",
            definition=dict((source.definition if source else None) or _empty_definition(workflow.trigger_event)),
            definition_hash=source.definition_hash if source else None,
            validation_status=source.validation_status if source else "pending",
            validation_errors=source.validation_errors if source else None,
            created_by=updated_by,
        )
        db.add(new_draft)
        await db.flush()
        workflow.draft_version_id = new_draft.id
        return new_draft

    @staticmethod
    def _status_response(workflow: TenantWorkflow) -> WorkflowStatusChangeResponse:
        return WorkflowStatusChangeResponse(
            id=workflow.id,
            status=workflow.status,  # type: ignore[arg-type]
            draft_revision=workflow.draft_revision,
            updated_at=workflow.updated_at,
            active_version_id=workflow.active_version_id,
            draft_version_id=workflow.draft_version_id,
        )

    @staticmethod
    def _to_version_summary(row: TenantWorkflowVersion) -> WorkflowVersionSummary:
        return WorkflowVersionSummary(
            id=row.id,
            workflow_id=row.workflow_id,
            version_number=row.version_number,
            state=row.state,  # type: ignore[arg-type]
            validation_status=row.validation_status,  # type: ignore[arg-type]
            definition_hash=row.definition_hash,
            created_at=row.created_at,
            published_at=row.published_at,
        )

    @staticmethod
    async def _to_summary(db: AsyncSession, workflow: TenantWorkflow) -> WorkflowSummary:
        active_num = None
        draft_num = None
        if workflow.active_version_id:
            active = await WorkflowService._get_version(db, workflow.tenant_id, workflow.active_version_id)
            active_num = active.version_number if active else None
        if workflow.draft_version_id:
            draft = await WorkflowService._get_version(db, workflow.tenant_id, workflow.draft_version_id)
            draft_num = draft.version_number if draft else None
        return WorkflowSummary(
            id=workflow.id,
            key=workflow.key,
            name=workflow.name,
            description=workflow.description,
            status=workflow.status,  # type: ignore[arg-type]
            trigger_event=workflow.trigger_event,
            active_version_id=workflow.active_version_id,
            draft_version_id=workflow.draft_version_id,
            draft_revision=workflow.draft_revision,
            failure_policy=workflow.failure_policy,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
            archived_at=workflow.archived_at,
            active_version_number=active_num,
            draft_version_number=draft_num,
        )

    @staticmethod
    async def _to_detail(db: AsyncSession, workflow: TenantWorkflow) -> WorkflowDetail:
        summary = await WorkflowService._to_summary(db, workflow)
        draft = await WorkflowService._get_version(db, workflow.tenant_id, workflow.draft_version_id)
        active = await WorkflowService._get_version(db, workflow.tenant_id, workflow.active_version_id)
        versions = (
            await db.execute(
                select(TenantWorkflowVersion)
                .where(
                    TenantWorkflowVersion.tenant_id == workflow.tenant_id,
                    TenantWorkflowVersion.workflow_id == workflow.id,
                )
                .order_by(TenantWorkflowVersion.version_number.desc())
                .limit(10),
            )
        ).scalars().all()
        return WorkflowDetail(
            **summary.model_dump(),
            draft_definition=dict(draft.definition) if draft else None,
            active_definition=dict(active.definition) if active else None,
            draft_validation_status=draft.validation_status if draft else None,  # type: ignore[arg-type]
            draft_validation_errors=draft.validation_errors if draft else None,
            recent_versions=[WorkflowService._to_version_summary(v) for v in versions],
        )
