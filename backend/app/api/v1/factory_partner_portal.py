from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.customer_portal import CustomerPortalCreateAccountResponse
from app.schemas.factory_partner_portal import (
    FactoryPartnerApplyRequest,
    FactoryPartnerApplicationListResponse,
    FactoryPartnerApplicationResponse,
    FactoryPartnerApplicationUpdate,
    FactoryPartnerCreateClientResponse,
    FactoryPartnerStatusActionResponse,
    FactoryPartnerSummaryWidget,
)
from app.schemas.tenant import TenantCreateResponse
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.customer_portal_service import CustomerPortalService
from app.services.factory_partner_portal_service import FactoryPartnerPortalService
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/factory-partner", tags=["factory-partner"])


@router.get("/applications", response_model=FactoryPartnerApplicationListResponse)
async def list_factory_applications(
    status: str | None = Query(
        None,
        description="draft | submitted | under_review | approved | rejected",
    ),
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        FactoryPartnerPortalService.list_applications(
            db, status=status, search=search, skip=skip, limit=limit,
        ),
        label="factory_partner.applications",
    )


@router.get("/summary-widget", response_model=FactoryPartnerSummaryWidget)
async def factory_partner_summary_widget(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await FactoryPartnerPortalService.summary_widget(db)


@router.get("/applications/{application_id}", response_model=FactoryPartnerApplicationResponse)
async def get_factory_application(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await FactoryPartnerPortalService.get_application(db, application_id)


@router.post("/apply", response_model=FactoryPartnerApplicationResponse, status_code=201)
async def factory_partner_apply(
    body: FactoryPartnerApplyRequest,
    db: AsyncSession = Depends(get_db),
):
    return await FactoryPartnerPortalService.apply(db, body)


@router.patch("/applications/{application_id}", response_model=FactoryPartnerApplicationResponse)
async def patch_factory_application(
    application_id: UUID,
    body: FactoryPartnerApplicationUpdate,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await FactoryPartnerPortalService.update_application(db, application_id, body)


@router.post(
    "/applications/{application_id}/submit",
    response_model=FactoryPartnerStatusActionResponse,
)
async def submit_factory_application(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await FactoryPartnerPortalService.submit(db, application_id)


@router.post(
    "/applications/{application_id}/approve",
    response_model=FactoryPartnerStatusActionResponse,
)
async def approve_factory_application(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await FactoryPartnerPortalService.approve(db, application_id)


@router.post(
    "/applications/{application_id}/reject",
    response_model=FactoryPartnerStatusActionResponse,
)
async def reject_factory_application(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await FactoryPartnerPortalService.reject(db, application_id)


@router.post(
    "/applications/{application_id}/create-client",
    response_model=FactoryPartnerCreateClientResponse,
)
async def create_client_from_factory_application(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await FactoryPartnerPortalService.create_client_from_application(db, application_id)


@router.post(
    "/applications/{application_id}/create-portal-account",
    response_model=CustomerPortalCreateAccountResponse,
)
async def create_portal_account_from_factory_application(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await CustomerPortalService.create_portal_account_from_application(db, application_id)


@router.post(
    "/applications/{application_id}/create-tenant",
    response_model=TenantCreateResponse,
)
async def create_tenant_from_factory_application(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await TenantService.create_tenant_from_application(db, application_id)
