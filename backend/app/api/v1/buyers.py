"""Tenant-scoped Buyer Network CRM API."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.buyer_crm import (
    BuyerActivityCreate,
    BuyerActivityListResponse,
    BuyerActivityResponse,
    BuyerCreate,
    BuyerDashboardResponse,
    BuyerDetailResponse,
    BuyerEntityLinkCreate,
    BuyerEntityLinkListResponse,
    BuyerLinkedEntity,
    BuyerListResponse,
    BuyerNoteCreate,
    BuyerNoteListResponse,
    BuyerNoteResponse,
    BuyerResponse,
    BuyerStatusHistoryListResponse,
    BuyerStatusHistoryResponse,
    BuyerTimelineResponse,
    BuyerUpdate,
    CENTRAL_ASIA_COUNTRIES,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.buyer_crm_service import BuyerCrmService
from app.services.platform_relationships_service import PlatformRelationshipsService
from app.schemas.platform_relationships import PlatformRelationshipsResponse
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/buyers", tags=["buyers"])


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if admin:
        return None
    if user:
        return user.tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_buyers_view(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        TenantAuthService.assert_permission(user, "buyers.view")
        return
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_buyers_manage(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        TenantAuthService.assert_permission(user, "buyers.manage")
        return
    raise HTTPException(status_code=401, detail="Authentication required")


def _actor(user: CurrentTenantUser | None) -> str | None:
    return user.email if user else None


@router.get("/meta/countries")
async def buyer_countries():
    return {"countries": CENTRAL_ASIA_COUNTRIES}


@router.get("/dashboard", response_model=BuyerDashboardResponse)
async def buyer_dashboard(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        BuyerCrmService.dashboard(db, tenant_id),
        label="buyers.dashboard",
    )


@router.get("", response_model=BuyerListResponse)
async def list_buyers(
    search: str | None = None,
    status: str | None = None,
    country: str | None = None,
    industry: str | None = None,
    tag: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    items, total = await run_guarded(
        BuyerCrmService.list_buyers(
            db, tenant_id,
            search=search, status=status, country=country,
            industry=industry, tag=tag, skip=skip, limit=limit,
        ),
        label="buyers.list",
    )
    return BuyerListResponse(items=items, total=total)


@router.post("", response_model=BuyerResponse, status_code=201)
async def create_buyer(
    body: BuyerCreate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_manage(user, admin)
    if admin and not user:
        raise HTTPException(status_code=400, detail="Admin must specify tenant via tenant user session")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return await run_guarded(
        BuyerCrmService.create_buyer(db, user.tenant_id, body, _actor(user)),
        label="buyers.create",
    )


@router.get("/{buyer_id}", response_model=BuyerDetailResponse)
async def get_buyer(
    buyer_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        BuyerCrmService.get_buyer(db, buyer_id, tenant_id),
        label="buyers.get",
    )


@router.patch("/{buyer_id}", response_model=BuyerResponse)
async def update_buyer(
    buyer_id: UUID,
    body: BuyerUpdate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        BuyerCrmService.update_buyer(db, buyer_id, tenant_id, body, _actor(user)),
        label="buyers.update",
    )


@router.delete("/{buyer_id}", status_code=204)
async def delete_buyer(
    buyer_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await run_guarded(
        BuyerCrmService.delete_buyer(db, buyer_id, tenant_id),
        label="buyers.delete",
    )


@router.get("/{buyer_id}/timeline", response_model=BuyerTimelineResponse)
async def buyer_timeline(
    buyer_id: UUID,
    limit: int = Query(100, ge=1, le=200),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        BuyerCrmService.timeline(db, buyer_id, tenant_id, limit=limit),
        label="buyers.timeline",
    )


@router.get("/{buyer_id}/activities", response_model=BuyerActivityListResponse)
async def list_buyer_activities(
    buyer_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    items, total = await run_guarded(
        BuyerCrmService.list_activities(db, buyer_id, tenant_id, skip=skip, limit=limit),
        label="buyers.activities.list",
    )
    return BuyerActivityListResponse(
        items=[BuyerActivityResponse.model_validate(i) for i in items],
        total=total,
    )


@router.post("/{buyer_id}/activities", response_model=BuyerActivityResponse, status_code=201)
async def create_buyer_activity(
    buyer_id: UUID,
    body: BuyerActivityCreate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    activity = await run_guarded(
        BuyerCrmService.create_activity(db, buyer_id, tenant_id, body, _actor(user)),
        label="buyers.activities.create",
    )
    return BuyerActivityResponse.model_validate(activity)


@router.get("/{buyer_id}/notes", response_model=BuyerNoteListResponse)
async def list_buyer_notes(
    buyer_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    items, total = await run_guarded(
        BuyerCrmService.list_notes(db, buyer_id, tenant_id, skip=skip, limit=limit),
        label="buyers.notes.list",
    )
    return BuyerNoteListResponse(
        items=[BuyerNoteResponse.model_validate(i) for i in items],
        total=total,
    )


@router.post("/{buyer_id}/notes", response_model=BuyerNoteResponse, status_code=201)
async def create_buyer_note(
    buyer_id: UUID,
    body: BuyerNoteCreate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    note = await run_guarded(
        BuyerCrmService.create_note(db, buyer_id, tenant_id, body, _actor(user)),
        label="buyers.notes.create",
    )
    return BuyerNoteResponse.model_validate(note)


@router.delete("/{buyer_id}/notes/{note_id}", status_code=204)
async def delete_buyer_note(
    buyer_id: UUID,
    note_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await run_guarded(
        BuyerCrmService.delete_note(db, buyer_id, note_id, tenant_id),
        label="buyers.notes.delete",
    )


@router.get("/{buyer_id}/status-history", response_model=BuyerStatusHistoryListResponse)
async def list_buyer_status_history(
    buyer_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    items, total = await run_guarded(
        BuyerCrmService.list_status_history(db, buyer_id, tenant_id, skip=skip, limit=limit),
        label="buyers.status_history.list",
    )
    return BuyerStatusHistoryListResponse(
        items=[BuyerStatusHistoryResponse.model_validate(i) for i in items],
        total=total,
    )


@router.get("/{buyer_id}/links", response_model=BuyerEntityLinkListResponse)
async def list_buyer_links(
    buyer_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    items = await run_guarded(
        BuyerCrmService.list_links(db, buyer_id, tenant_id),
        label="buyers.links.list",
    )
    return BuyerEntityLinkListResponse(items=items, total=len(items))


@router.post("/{buyer_id}/links", response_model=BuyerLinkedEntity, status_code=201)
async def create_buyer_link(
    buyer_id: UUID,
    body: BuyerEntityLinkCreate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    link = await run_guarded(
        BuyerCrmService.create_link(db, buyer_id, tenant_id, body, _actor(user)),
        label="buyers.links.create",
    )
    return link


@router.delete("/{buyer_id}/links/{link_id}", status_code=204)
async def delete_buyer_link(
    buyer_id: UUID,
    link_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await run_guarded(
        BuyerCrmService.delete_link(db, buyer_id, link_id, tenant_id),
        label="buyers.links.delete",
    )


@router.get("/{buyer_id}/related", response_model=PlatformRelationshipsResponse)
async def get_buyer_related(
    buyer_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_buyers_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        PlatformRelationshipsService.for_buyer(db, buyer_id, tenant_id),
        label="buyers.related",
    )
