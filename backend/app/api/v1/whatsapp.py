from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.communication import CommunicationContactResponse, CommunicationMessageResponse
from app.schemas.whatsapp_business import (
    WhatsAppAccountCreate,
    WhatsAppAccountListResponse,
    WhatsAppAccountResponse,
    WhatsAppAccountUpdate,
    WhatsAppAiCapabilitiesResponse,
    WhatsAppContactListExtendedResponse,
    WhatsAppCrmLinkResponse,
    WhatsAppDashboardResponse,
    WhatsAppDemoSeedResponse,
    WhatsAppLinkBuyerRequest,
    WhatsAppLinkCustomerRequest,
    WhatsAppLinkDealRequest,
    WhatsAppLinkLeadRequest,
    WhatsAppLinkProposalRequest,
)
from app.schemas.whatsapp_contact_center import (
    WhatsAppContactListResponse as LegacyWhatsAppContactListResponse,
    WhatsAppDraftRequest,
    WhatsAppDraftResponse,
    WhatsAppLinkCrmRequest,
    WhatsAppLinkCrmResponse,
    WhatsAppMessageListResponse,
    WhatsAppThreadListResponse as LegacyWhatsAppThreadListResponse,
)
from app.schemas.whatsapp_message_center import (
    WhatsAppContactCreate,
    WhatsAppContactListResponse,
    WhatsAppCreateLeadRequest,
    WhatsAppCreateLeadResponse,
    WhatsAppGenerateReplyRequest,
    WhatsAppGenerateReplyResponse,
    WhatsAppLinkResponse,
    WhatsAppMarkCopiedResponse,
    WhatsAppMarkManuallySentResponse,
    WhatsAppPasteInboundRequest,
    WhatsAppThreadCreate,
    WhatsAppThreadDetailResponse,
    WhatsAppThreadListResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.tenant_auth_service import CurrentTenantUser
from app.services.whatsapp_business_service import WhatsAppBusinessService
from app.services.whatsapp_contact_service import WhatsAppContactService
from app.services.whatsapp_draft_service import WhatsAppDraftService
from app.services.whatsapp_message_center_service import WhatsAppMessageCenterService
from app.services.whatsapp_thread_service import WhatsAppThreadService

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if admin:
        return None
    if user:
        return user.tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_whatsapp_view(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        if user.has_permission("inbox.manage") or user.has_permission("leads.view") or user.has_permission("tenant.read"):
            return
        raise HTTPException(status_code=403, detail="Permission denied")
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_whatsapp_manage(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        if user.has_permission("inbox.manage") or user.has_permission("leads.manage"):
            return
        raise HTTPException(status_code=403, detail="Permission denied")
    raise HTTPException(status_code=401, detail="Authentication required")


@router.get("/dashboard", response_model=WhatsAppDashboardResponse)
async def whatsapp_dashboard(
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppBusinessService.dashboard(db, tenant_id)


@router.get("/accounts", response_model=WhatsAppAccountListResponse)
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppBusinessService.list_accounts(db, tenant_id)


@router.post("/accounts", response_model=WhatsAppAccountResponse, status_code=201)
async def create_account(
    body: WhatsAppAccountCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await WhatsAppBusinessService.create_account(
        db,
        tenant_id,
        account_name=body.account_name,
        account_type=body.account_type,
        phone_number=body.phone_number,
        business_display_name=body.business_display_name,
        provider=body.provider,
    )


@router.patch("/accounts/{account_id}", response_model=WhatsAppAccountResponse)
async def update_account(
    account_id: UUID,
    body: WhatsAppAccountUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppBusinessService.update_account(
        db,
        tenant_id,
        account_id,
        account_name=body.account_name,
        phone_number=body.phone_number,
        business_display_name=body.business_display_name,
        status=body.status,
        provider=body.provider,
    )


@router.post("/demo/seed", response_model=WhatsAppDemoSeedResponse)
async def seed_demo(
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await WhatsAppBusinessService.seed_demo_environment(db, tenant_id)


@router.get("/ai/capabilities", response_model=WhatsAppAiCapabilitiesResponse)
async def ai_capabilities(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_view(user, admin)
    return WhatsAppBusinessService.ai_capabilities()


@router.get("/contacts/extended", response_model=WhatsAppContactListExtendedResponse)
async def list_contacts_extended(
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppBusinessService.list_contacts_extended(
        db, tenant_id, search=search, skip=skip, limit=limit,
    )


@router.get("/contacts", response_model=WhatsAppContactListResponse)
async def list_contacts(
    client_id: UUID | None = None,
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppMessageCenterService.list_contacts(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        search=search,
        skip=skip,
        limit=limit,
    )


@router.post("/contacts", response_model=CommunicationContactResponse, status_code=201)
async def create_contact(
    body: WhatsAppContactCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppMessageCenterService.create_contact(db, body, tenant_id=tenant_id)


@router.post("/contacts/{contact_id}/link-buyer", response_model=WhatsAppCrmLinkResponse)
async def link_contact_buyer(
    contact_id: UUID,
    body: WhatsAppLinkBuyerRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppBusinessService.link_contact_buyer(db, tenant_id, contact_id, body.buyer_id)


@router.post("/contacts/{contact_id}/link-customer", response_model=WhatsAppCrmLinkResponse)
async def link_contact_customer(
    contact_id: UUID,
    body: WhatsAppLinkCustomerRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppBusinessService.link_contact_customer(
        db, tenant_id, contact_id, body.customer_id,
    )


@router.post("/contacts/{contact_id}/link-lead", response_model=WhatsAppCrmLinkResponse)
async def link_contact_lead(
    contact_id: UUID,
    body: WhatsAppLinkLeadRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppBusinessService.link_contact_lead(db, tenant_id, contact_id, body.lead_id)


@router.get("/threads", response_model=WhatsAppThreadListResponse)
async def list_threads(
    client_id: UUID | None = None,
    contact_id: UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppMessageCenterService.list_threads(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        contact_id=contact_id,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post("/threads", response_model=WhatsAppThreadDetailResponse, status_code=201)
async def create_thread(
    body: WhatsAppThreadCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    created = await WhatsAppMessageCenterService.create_thread(db, body, tenant_id=tenant_id)
    return await WhatsAppMessageCenterService.get_thread(db, created["id"], tenant_id=tenant_id)


@router.get("/threads/{thread_id}", response_model=WhatsAppThreadDetailResponse)
async def get_thread(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppMessageCenterService.get_thread(db, thread_id, tenant_id=tenant_id)


@router.post("/threads/{thread_id}/messages", response_model=CommunicationMessageResponse, status_code=201)
async def paste_inbound_message(
    thread_id: UUID,
    body: WhatsAppPasteInboundRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await WhatsAppBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
    return await WhatsAppMessageCenterService.paste_inbound(db, thread_id, body)


@router.post("/threads/{thread_id}/generate-reply", response_model=WhatsAppGenerateReplyResponse)
async def generate_reply(
    thread_id: UUID,
    body: WhatsAppGenerateReplyRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await WhatsAppBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
    return await run_guarded(
        WhatsAppMessageCenterService.generate_reply(db, thread_id, body),
        label="whatsapp.generate-reply",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/messages/{message_id}/mark-copied", response_model=WhatsAppMarkCopiedResponse)
async def mark_copied(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    return await WhatsAppMessageCenterService.mark_copied(db, message_id)


@router.post("/messages/{message_id}/mark-manually-sent", response_model=WhatsAppMarkManuallySentResponse)
async def mark_manually_sent(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    return await WhatsAppMessageCenterService.mark_manually_sent(db, message_id)


@router.post("/threads/{thread_id}/create-lead", response_model=WhatsAppCreateLeadResponse)
async def create_lead(
    thread_id: UUID,
    body: WhatsAppCreateLeadRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await WhatsAppBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
    return await WhatsAppMessageCenterService.create_lead(db, thread_id, body)


@router.post("/threads/{thread_id}/link-lead", response_model=WhatsAppLinkResponse)
async def link_lead(
    thread_id: UUID,
    body: WhatsAppLinkLeadRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await WhatsAppBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
    return await WhatsAppMessageCenterService.link_lead(db, thread_id, body.lead_id)


@router.post("/threads/{thread_id}/link-deal", response_model=WhatsAppLinkResponse)
async def link_deal(
    thread_id: UUID,
    body: WhatsAppLinkDealRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppBusinessService.link_thread_deal(db, tenant_id, thread_id, body.deal_id)


@router.post("/threads/{thread_id}/link-proposal", response_model=WhatsAppCrmLinkResponse)
async def link_proposal(
    thread_id: UUID,
    body: WhatsAppLinkProposalRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await WhatsAppBusinessService.link_thread_proposal(
        db, tenant_id, thread_id, body.proposal_id,
    )


# Legacy isolated-table endpoints (unified inbox / deal room compatibility)
@router.get("/legacy/contacts", response_model=LegacyWhatsAppContactListResponse)
async def list_legacy_contacts(
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_view(user, admin)
    return await WhatsAppContactService.list_contacts(db, search=search, skip=skip, limit=limit)


@router.get("/legacy/threads", response_model=LegacyWhatsAppThreadListResponse)
async def list_legacy_threads(
    contact_id: UUID | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_view(user, admin)
    return await WhatsAppThreadService.list_threads(db, contact_id=contact_id, skip=skip, limit=limit)


@router.get("/legacy/messages/{thread_id}", response_model=WhatsAppMessageListResponse)
async def list_legacy_messages(
    thread_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_view(user, admin)
    return await WhatsAppThreadService.list_messages(db, thread_id, skip=skip, limit=limit)


@router.post("/legacy/draft", response_model=WhatsAppDraftResponse)
async def create_legacy_draft(
    body: WhatsAppDraftRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    return await WhatsAppDraftService.create_draft(
        db,
        thread_id=body.thread_id,
        operator_notes=body.operator_notes,
    )


@router.post("/legacy/link-crm", response_model=WhatsAppLinkCrmResponse)
async def link_legacy_crm(
    body: WhatsAppLinkCrmRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_whatsapp_manage(user, admin)
    return await WhatsAppContactService.link_crm(
        db,
        contact_id=body.contact_id,
        crm_client_id=body.crm_client_id,
    )
