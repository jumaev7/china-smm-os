from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.communication import CommunicationContactResponse, CommunicationMessageResponse
from app.schemas.wechat_business import (
    WeChatAccountCreate,
    WeChatAccountListResponse,
    WeChatAccountResponse,
    WeChatAccountUpdate,
    WeChatAiCapabilitiesResponse,
    WeChatContactListExtendedResponse,
    WeChatCrmLinkResponse,
    WeChatDashboardResponse,
    WeChatDemoSeedResponse,
    WeChatLinkBuyerRequest,
    WeChatLinkCustomerRequest,
    WeChatLinkProposalRequest,
)
from app.schemas.wechat_contact_center import (
    WeChatContactCreate,
    WeChatContactListResponse,
    WeChatCreateLeadRequest,
    WeChatCreateLeadResponse,
    WeChatGenerateReplyRequest,
    WeChatGenerateReplyResponse,
    WeChatLinkDealRequest,
    WeChatLinkLeadRequest,
    WeChatLinkResponse,
    WeChatMarkCopiedResponse,
    WeChatMarkManuallySentResponse,
    WeChatPasteInboundRequest,
    WeChatThreadCreate,
    WeChatThreadDetailResponse,
    WeChatThreadListResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.tenant_auth_service import CurrentTenantUser
from app.services.wechat_business_service import WeChatBusinessService
from app.services.wechat_contact_center_service import WeChatContactCenterService

router = APIRouter(prefix="/wechat", tags=["wechat"])


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if admin:
        return None
    if user:
        return user.tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_wechat_view(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        if user.has_permission("inbox.manage") or user.has_permission("leads.view") or user.has_permission("tenant.read"):
            return
        raise HTTPException(status_code=403, detail="Permission denied")
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_wechat_manage(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        if user.has_permission("inbox.manage") or user.has_permission("leads.manage"):
            return
        raise HTTPException(status_code=403, detail="Permission denied")
    raise HTTPException(status_code=401, detail="Authentication required")


@router.get("/dashboard", response_model=WeChatDashboardResponse)
async def wechat_dashboard(
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatBusinessService.dashboard(db, tenant_id)


@router.get("/accounts", response_model=WeChatAccountListResponse)
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatBusinessService.list_accounts(db, tenant_id)


@router.post("/accounts", response_model=WeChatAccountResponse, status_code=201)
async def create_account(
    body: WeChatAccountCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await WeChatBusinessService.create_account(
        db,
        tenant_id,
        account_name=body.account_name,
        account_type=body.account_type,
        provider=body.provider,
    )


@router.patch("/accounts/{account_id}", response_model=WeChatAccountResponse)
async def update_account(
    account_id: UUID,
    body: WeChatAccountUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatBusinessService.update_account(
        db,
        tenant_id,
        account_id,
        account_name=body.account_name,
        status=body.status,
        provider=body.provider,
    )


@router.post("/demo/seed", response_model=WeChatDemoSeedResponse)
async def seed_demo(
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await WeChatBusinessService.seed_demo_environment(db, tenant_id)


@router.get("/ai/capabilities", response_model=WeChatAiCapabilitiesResponse)
async def ai_capabilities(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_view(user, admin)
    return WeChatBusinessService.ai_capabilities()


@router.get("/contacts", response_model=WeChatContactListResponse)
async def list_contacts(
    client_id: UUID | None = None,
    search: str | None = None,
    channel: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatContactCenterService.list_contacts(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        search=search,
        channel=channel,
        skip=skip,
        limit=limit,
    )


@router.get("/contacts/extended", response_model=WeChatContactListExtendedResponse)
async def list_contacts_extended(
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatBusinessService.list_contacts_extended(
        db, tenant_id, search=search, skip=skip, limit=limit,
    )


@router.post("/contacts", response_model=CommunicationContactResponse, status_code=201)
async def create_contact(
    body: WeChatContactCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatContactCenterService.create_contact(db, body, tenant_id=tenant_id)


@router.post("/contacts/{contact_id}/link-buyer", response_model=WeChatCrmLinkResponse)
async def link_contact_buyer(
    contact_id: UUID,
    body: WeChatLinkBuyerRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatBusinessService.link_contact_buyer(db, tenant_id, contact_id, body.buyer_id)


@router.post("/contacts/{contact_id}/link-customer", response_model=WeChatCrmLinkResponse)
async def link_contact_customer(
    contact_id: UUID,
    body: WeChatLinkCustomerRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatBusinessService.link_contact_customer(
        db, tenant_id, contact_id, body.customer_id,
    )


@router.get("/threads", response_model=WeChatThreadListResponse)
async def list_threads(
    client_id: UUID | None = None,
    contact_id: UUID | None = None,
    channel: str | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatContactCenterService.list_threads(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        contact_id=contact_id,
        channel=channel,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post("/threads", response_model=WeChatThreadDetailResponse, status_code=201)
async def create_thread(
    body: WeChatThreadCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    created = await WeChatContactCenterService.create_thread(db, body, tenant_id=tenant_id)
    return await WeChatContactCenterService.get_thread(db, created["id"], tenant_id=tenant_id)


@router.get("/threads/{thread_id}", response_model=WeChatThreadDetailResponse)
async def get_thread(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatContactCenterService.get_thread(db, thread_id, tenant_id=tenant_id)


@router.post(
    "/threads/{thread_id}/messages",
    response_model=CommunicationMessageResponse,
    status_code=201,
)
async def paste_inbound_message(
    thread_id: UUID,
    body: WeChatPasteInboundRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await WeChatBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
    return await WeChatContactCenterService.paste_inbound(db, thread_id, body)


@router.post("/threads/{thread_id}/generate-reply", response_model=WeChatGenerateReplyResponse)
async def generate_reply(
    thread_id: UUID,
    body: WeChatGenerateReplyRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await WeChatBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
    return await run_guarded(
        WeChatContactCenterService.generate_reply(db, thread_id, body),
        label="wechat.generate-reply",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/messages/{message_id}/mark-copied", response_model=WeChatMarkCopiedResponse)
async def mark_copied(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    return await WeChatContactCenterService.mark_copied(db, message_id)


@router.post("/messages/{message_id}/mark-manually-sent", response_model=WeChatMarkManuallySentResponse)
async def mark_manually_sent(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    return await WeChatContactCenterService.mark_manually_sent(db, message_id)


@router.post("/threads/{thread_id}/create-lead", response_model=WeChatCreateLeadResponse)
async def create_lead(
    thread_id: UUID,
    body: WeChatCreateLeadRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await WeChatBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
    return await WeChatContactCenterService.create_lead(db, thread_id, body)


@router.post("/threads/{thread_id}/link-lead", response_model=WeChatLinkResponse)
async def link_lead(
    thread_id: UUID,
    body: WeChatLinkLeadRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await WeChatBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
    return await WeChatContactCenterService.link_lead(db, thread_id, body.lead_id)


@router.post("/threads/{thread_id}/link-deal", response_model=WeChatLinkResponse)
async def link_deal(
    thread_id: UUID,
    body: WeChatLinkDealRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await WeChatBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
    return await WeChatContactCenterService.link_deal(db, thread_id, body.deal_id)


@router.post("/threads/{thread_id}/link-proposal", response_model=WeChatCrmLinkResponse)
async def link_proposal(
    thread_id: UUID,
    body: WeChatLinkProposalRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_wechat_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WeChatBusinessService.link_thread_proposal(
        db, tenant_id, thread_id, body.proposal_id,
    )
