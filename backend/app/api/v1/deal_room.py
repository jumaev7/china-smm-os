from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_auth_context import resolve_tenant_id_param
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC
from app.schemas.deal_room import (
    DealRoomCreateRequest,
    DealRoomDetailResponse,
    DealRoomFindOrCreateRequest,
    DealRoomItem,
    DealRoomListResponse,
    DealRoomUpdateStageRequest,
    DealRoomV2ListResponse,
    DealRoomV2Overview,
    DealRoomV2RefreshResponse,
    DealRoomV2SummaryWidget,
    DealRoomV2WorkspaceResponse,
)
from app.services.deal_room_service import DealRoomService
from app.services.deal_room_v2_service import DealRoomV2Service

router = APIRouter(prefix="/deal-room", tags=["deal-room"])


@router.get("", response_model=DealRoomListResponse)
async def list_deal_rooms(
    crm_client_id: UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRoomService.list_rooms(
            db, crm_client_id=crm_client_id, status=status, skip=skip, limit=limit,
        ),
        label="deal_room.list",
    )


@router.get("/v2/overview", response_model=DealRoomV2Overview)
async def deal_room_v2_overview(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    scoped_tenant = resolve_tenant_id_param(tenant_id)
    return await run_guarded(
        DealRoomV2Service.overview(db, client_id=client_id, tenant_id=scoped_tenant),
        label="deal_room.v2.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/v2/workspaces", response_model=DealRoomV2ListResponse)
async def deal_room_v2_workspaces(
    crm_client_id: UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRoomV2Service.list_workspaces(
            db, crm_client_id=crm_client_id, status=status, skip=skip, limit=limit,
        ),
        label="deal_room.v2.workspaces",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/v2/summary-widget", response_model=DealRoomV2SummaryWidget)
async def deal_room_v2_summary_widget(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    scoped_tenant = resolve_tenant_id_param(tenant_id)
    return await run_guarded(
        DealRoomV2Service.summary_widget(db, client_id=client_id, tenant_id=scoped_tenant),
        label="deal_room.v2.summary_widget",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/v2/deal-acquisition-panel")
async def deal_room_v2_deal_acquisition_panel(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    scoped_tenant = resolve_tenant_id_param(tenant_id)
    return await run_guarded(
        DealRoomV2Service.deal_acquisition_panel(
            db, client_id=client_id, tenant_id=scoped_tenant,
        ),
        label="deal_room.v2.deal_acquisition_panel",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/v2/deal-revenue-panel")
async def deal_room_v2_deal_revenue_panel(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    scoped_tenant = resolve_tenant_id_param(tenant_id)
    return await run_guarded(
        DealRoomV2Service.deal_revenue_panel(
            db, client_id=client_id, tenant_id=scoped_tenant,
        ),
        label="deal_room.v2.deal_revenue_panel",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/v2/refresh", response_model=DealRoomV2RefreshResponse)
async def deal_room_v2_refresh(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    scoped_tenant = resolve_tenant_id_param(tenant_id)
    return await DealRoomV2Service.refresh(
        db, client_id=client_id, tenant_id=scoped_tenant,
    )


@router.get("/v2/workspace/{room_id}", response_model=DealRoomV2WorkspaceResponse)
async def deal_room_v2_workspace(
    room_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRoomV2Service.workspace(db, room_id),
        label="deal_room.v2.workspace",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/{room_id}", response_model=DealRoomDetailResponse)
async def get_deal_room(
    room_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRoomService.get_detail(db, room_id),
        label="deal_room.detail",
    )


@router.post("/create", response_model=DealRoomItem, status_code=201)
async def create_deal_room(
    body: DealRoomCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRoomService.create_room(db, body),
        label="deal_room.create",
    )


@router.post("/update-stage", response_model=DealRoomItem)
async def update_deal_room_stage(
    body: DealRoomUpdateStageRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRoomService.update_stage(db, body),
        label="deal_room.update_stage",
    )


@router.post("/find-or-create", response_model=DealRoomItem)
async def find_or_create_deal_room(
    body: DealRoomFindOrCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealRoomService.find_or_create_for_lead(
            db,
            crm_client_id=body.crm_client_id,
            crm_lead_id=body.crm_lead_id,
            deal_name=body.deal_name,
        ),
        label="deal_room.find_or_create",
    )
