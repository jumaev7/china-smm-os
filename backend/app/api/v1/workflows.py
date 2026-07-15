"""Tenant Workflow Builder API."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.workflow import (
    WorkflowCatalogResponse,
    WorkflowCloneResponse,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowExecutionDetail,
    WorkflowExecutionListResponse,
    WorkflowListResponse,
    WorkflowPublishResponse,
    WorkflowStatusChangeResponse,
    WorkflowTestRequest,
    WorkflowTestResponse,
    WorkflowUpdate,
    WorkflowValidateRequest,
    WorkflowValidateResponse,
    WorkflowVersionDetail,
    WorkflowVersionListResponse,
)
from app.services.tenant_auth_service import CurrentTenantUser
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/catalog", response_model=WorkflowCatalogResponse)
async def workflow_catalog(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    return await run_guarded(
        WorkflowService.get_catalog(),
        label="workflows.catalog",
    )


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WorkflowService.list_workflows(
            db, user.tenant_id, page=page, page_size=page_size, status=status,
        ),
        label="workflows.list",
    )


@router.post("", response_model=WorkflowDetail)
async def create_workflow(
    body: WorkflowCreate,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        WorkflowService.create_workflow(
            db,
            user.tenant_id,
            name=body.name,
            description=body.description,
            key=body.key,
            definition=body.definition,
            created_by=user.id,
        ),
        label="workflows.create",
    )
    await db.commit()
    return result


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(
    workflow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WorkflowService.get_workflow(db, user.tenant_id, workflow_id),
        label="workflows.get",
    )


@router.patch("/{workflow_id}", response_model=WorkflowDetail)
async def update_workflow(
    workflow_id: UUID,
    body: WorkflowUpdate,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        WorkflowService.update_workflow(
            db,
            user.tenant_id,
            workflow_id,
            draft_revision=body.draft_revision,
            name=body.name,
            description=body.description,
            definition=body.definition,
            updated_by=user.id,
        ),
        label="workflows.update",
    )
    await db.commit()
    return result


@router.post("/{workflow_id}/validate", response_model=WorkflowValidateResponse)
async def validate_workflow(
    workflow_id: UUID,
    body: WorkflowValidateRequest | None = None,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WorkflowService.validate_workflow(
            db,
            user.tenant_id,
            workflow_id,
            definition=(body.definition if body else None),
        ),
        label="workflows.validate",
    )


@router.post("/{workflow_id}/publish", response_model=WorkflowPublishResponse)
async def publish_workflow(
    workflow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        WorkflowService.publish_workflow(
            db, user.tenant_id, workflow_id, published_by=user.id,
        ),
        label="workflows.publish",
    )
    await db.commit()
    return result


@router.post("/{workflow_id}/pause", response_model=WorkflowStatusChangeResponse)
async def pause_workflow(
    workflow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        WorkflowService.pause_workflow(db, user.tenant_id, workflow_id),
        label="workflows.pause",
    )
    await db.commit()
    return result


@router.post("/{workflow_id}/resume", response_model=WorkflowStatusChangeResponse)
async def resume_workflow(
    workflow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        WorkflowService.resume_workflow(db, user.tenant_id, workflow_id),
        label="workflows.resume",
    )
    await db.commit()
    return result


@router.post("/{workflow_id}/archive", response_model=WorkflowStatusChangeResponse)
async def archive_workflow(
    workflow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        WorkflowService.archive_workflow(db, user.tenant_id, workflow_id),
        label="workflows.archive",
    )
    await db.commit()
    return result


@router.post("/{workflow_id}/clone", response_model=WorkflowCloneResponse)
async def clone_workflow(
    workflow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        WorkflowService.clone_workflow(
            db, user.tenant_id, workflow_id, created_by=user.id,
        ),
        label="workflows.clone",
    )
    await db.commit()
    return result


@router.get("/{workflow_id}/versions", response_model=WorkflowVersionListResponse)
async def list_workflow_versions(
    workflow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WorkflowService.list_versions(db, user.tenant_id, workflow_id),
        label="workflows.versions",
    )


@router.get("/{workflow_id}/versions/{version_id}", response_model=WorkflowVersionDetail)
async def get_workflow_version(
    workflow_id: UUID,
    version_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WorkflowService.get_version(db, user.tenant_id, workflow_id, version_id),
        label="workflows.version.get",
    )


@router.get("/{workflow_id}/executions", response_model=WorkflowExecutionListResponse)
async def list_workflow_executions(
    workflow_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WorkflowService.list_executions(
            db, user.tenant_id, workflow_id, page=page, page_size=page_size,
        ),
        label="workflows.executions",
    )


@router.post("/{workflow_id}/test", response_model=WorkflowTestResponse)
async def test_workflow(
    workflow_id: UUID,
    body: WorkflowTestRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WorkflowService.test_workflow(
            db,
            user.tenant_id,
            workflow_id,
            mode=body.mode,
            version_id=body.version_id,
            synthetic_payload=body.synthetic_payload,
        ),
        label="workflows.test",
    )


# Separate router for execution detail by id (path without workflow_id prefix)
execution_router = APIRouter(prefix="/workflow-executions", tags=["workflows"])


@execution_router.get("/{execution_id}", response_model=WorkflowExecutionDetail)
async def get_workflow_execution(
    execution_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WorkflowService.get_execution(db, user.tenant_id, execution_id),
        label="workflows.execution.get",
    )
