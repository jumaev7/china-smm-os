from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin, get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user, get_current_tenant_user_optional
from app.schemas.client_brief import (
    ClientBriefAddMedia,
    ClientBriefConvertResponse,
    ClientBriefCreate,
    ClientBriefListResponse,
    ClientBriefRequestChanges,
    ClientBriefResponse,
    ClientBriefUpdatePlan,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.client_brief_service import ClientBriefService
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/client-briefs", tags=["client-briefs"])


@router.post("", response_model=ClientBriefResponse, status_code=201)
async def submit_client_brief(
    body: ClientBriefCreate,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await ClientBriefService.submit(
        db,
        body,
        tenant_id=user.tenant_id,
        submitted_by=user.email,
    )


@router.get("", response_model=ClientBriefListResponse)
async def list_client_briefs(
    tenant_scope: bool = Query(False, description="Restrict to authenticated tenant"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    if admin:
        return await run_guarded(
            ClientBriefService.list_briefs(db, tenant_id=None, skip=skip, limit=limit),
            label="client-briefs.list",
        )
    if user:
        return await run_guarded(
            ClientBriefService.list_briefs(
                db, tenant_id=user.tenant_id, skip=skip, limit=limit,
            ),
            label="client-briefs.list",
        )
    raise HTTPException(status_code=401, detail="Authentication required")


@router.get("/{brief_id}", response_model=ClientBriefResponse)
async def get_client_brief(
    brief_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    if not admin and not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user and not admin:
        brief = await ClientBriefService._load(db, brief_id)
        ClientBriefService.assert_tenant_can_access(brief, user.tenant_id)
    return await ClientBriefService.get_brief(db, brief_id)


@router.post("/{brief_id}/mark-reviewed", response_model=ClientBriefResponse)
async def mark_client_brief_reviewed(
    brief_id: UUID,
    admin: CurrentAdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await ClientBriefService.mark_reviewed(db, brief_id)


@router.post("/{brief_id}/approve-brief", response_model=ClientBriefResponse)
async def approve_client_brief(
    brief_id: UUID,
    admin: CurrentAdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await ClientBriefService.approve_brief(db, brief_id)


@router.post("/{brief_id}/request-changes", response_model=ClientBriefResponse)
async def request_client_brief_changes(
    brief_id: UUID,
    body: ClientBriefRequestChanges,
    admin: CurrentAdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await ClientBriefService.request_changes(db, brief_id, feedback=body.feedback)


@router.post("/{brief_id}/generate-plan", response_model=ClientBriefResponse)
async def generate_client_brief_plan(
    brief_id: UUID,
    admin: CurrentAdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await ClientBriefService.generate_plan(db, brief_id)


@router.put("/{brief_id}/plan", response_model=ClientBriefResponse)
async def update_client_brief_plan(
    brief_id: UUID,
    body: ClientBriefUpdatePlan,
    admin: CurrentAdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await ClientBriefService.update_plan(db, brief_id, body.plan)


@router.post("/{brief_id}/approve-plan", response_model=ClientBriefResponse)
async def approve_client_brief_plan(
    brief_id: UUID,
    admin: CurrentAdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await ClientBriefService.approve_plan(db, brief_id)


@router.post("/{brief_id}/add-media", response_model=ClientBriefResponse)
async def add_client_brief_media(
    brief_id: UUID,
    body: ClientBriefAddMedia,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await ClientBriefService.add_media(
        db,
        brief_id,
        tenant_id=user.tenant_id,
        media_urls=body.media_urls,
    )


@router.post("/{brief_id}/convert-to-tasks", response_model=ClientBriefConvertResponse)
async def convert_client_brief_to_tasks(
    brief_id: UUID,
    admin: CurrentAdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await ClientBriefService.convert_to_tasks(db, brief_id)
