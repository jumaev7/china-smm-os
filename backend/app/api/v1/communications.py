from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.communication import (
    CommunicationAiSummaryResponse,
    CommunicationContactCreate,
    CommunicationContactListResponse,
    CommunicationContactResponse,
    CommunicationCreateLeadResponse,
    CommunicationCrmCreateLeadRequest,
    CommunicationCrmCreateTaskRequest,
    CommunicationCrmCreateTaskResponse,
    CommunicationCrmExtractResponse,
    CommunicationCrmSuggestReplyResponse,
    CommunicationLinkLeadRequest,
    CommunicationMessageCreate,
    CommunicationMessageStoredResponse,
    CommunicationThreadCreate,
    CommunicationThreadDetailResponse,
    CommunicationThreadListResponse,
    CommunicationThreadResponse,
)
from app.schemas.communication_hub import (
    CommunicationAiCapabilitiesResponse,
    CommunicationDashboardResponse,
    CommunicationRecordCreate,
    CommunicationRecordListResponse,
    CommunicationRecordResponse,
    FollowUpCreate,
    FollowUpListResponse,
    FollowUpResponse,
    FollowUpUpdate,
    MessageTemplateCreate,
    MessageTemplateListResponse,
    MessageTemplateResponse,
    MessageTemplateUpdate,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.communication_ai_hub_service import CommunicationAiHubService
from app.services.communication_crm_service import CommunicationCrmService
from app.services.communication_followup_service import CommunicationFollowUpService
from app.services.communication_hub_dashboard_service import CommunicationHubDashboardService
from app.services.communication_record_service import CommunicationRecordService
from app.services.communication_service import CommunicationHubService
from app.services.communication_template_service import CommunicationTemplateService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/communications", tags=["communications"])


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if admin:
        return None
    if user:
        return user.tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_hub_view(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        if user.has_permission("inbox.manage") or user.has_permission("leads.view") or user.has_permission("tenant.read"):
            return
        raise HTTPException(status_code=403, detail="Permission denied")
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_hub_manage(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        if user.has_permission("inbox.manage") or user.has_permission("leads.manage"):
            return
        raise HTTPException(status_code=403, detail="Permission denied")
    raise HTTPException(status_code=401, detail="Authentication required")


@router.get("/dashboard", response_model=CommunicationDashboardResponse)
async def communication_dashboard(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await CommunicationHubDashboardService.dashboard(db, tenant_id)


@router.get("/inbox", response_model=CommunicationRecordListResponse)
async def communication_inbox(
    channel: str | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await CommunicationRecordService.list_records(
        db, tenant_id, channel=channel, status=status, skip=skip, limit=limit,
    )


@router.get("/records", response_model=CommunicationRecordListResponse)
async def list_communication_records(
    channel: str | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await CommunicationRecordService.list_records(
        db, tenant_id, channel=channel, status=status, skip=skip, limit=limit,
    )


@router.post("/records", response_model=CommunicationRecordResponse, status_code=201)
async def create_communication_record(
    body: CommunicationRecordCreate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await CommunicationRecordService.create_manual_record(db, tenant_id, body)


@router.get("/followups", response_model=FollowUpListResponse)
async def list_followups(
    bucket: str | None = Query(None, pattern="^(overdue|today|upcoming)$"),
    status: str | None = None,
    assigned_user: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await CommunicationFollowUpService.list_followups(
        db, tenant_id, bucket=bucket, status=status, assigned_user=assigned_user,
        skip=skip, limit=limit,
    )


@router.post("/followups", response_model=FollowUpResponse, status_code=201)
async def create_followup(
    body: FollowUpCreate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await CommunicationFollowUpService.create_followup(db, tenant_id, body)


@router.patch("/followups/{follow_up_id}", response_model=FollowUpResponse)
async def update_followup(
    follow_up_id: UUID,
    body: FollowUpUpdate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await CommunicationFollowUpService.update_followup(db, tenant_id, follow_up_id, body)


@router.post("/followups/{follow_up_id}/complete", response_model=FollowUpResponse)
async def complete_followup(
    follow_up_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await CommunicationFollowUpService.complete_followup(db, tenant_id, follow_up_id)


@router.get("/templates", response_model=MessageTemplateListResponse)
async def list_templates(
    category: str | None = None,
    language: str | None = None,
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await CommunicationTemplateService.list_templates(
        db, tenant_id, category=category, language=language, search=search,
        skip=skip, limit=limit,
    )


@router.post("/templates", response_model=MessageTemplateResponse, status_code=201)
async def create_template(
    body: MessageTemplateCreate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await CommunicationTemplateService.create_template(db, tenant_id, body)


@router.patch("/templates/{template_id}", response_model=MessageTemplateResponse)
async def update_template(
    template_id: UUID,
    body: MessageTemplateUpdate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await CommunicationTemplateService.update_template(db, tenant_id, template_id, body)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    await CommunicationTemplateService.delete_template(db, tenant_id, template_id)


@router.get("/ai/capabilities", response_model=CommunicationAiCapabilitiesResponse)
async def ai_capabilities(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_hub_view(user, admin)
    return CommunicationAiHubService.capabilities()


@router.get("/ai/suggest-follow-ups")
async def ai_suggest_followups(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_hub_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context required")
    return await CommunicationAiHubService.suggest_follow_up_actions(db, tenant_id)


@router.get("/contacts", response_model=CommunicationContactListResponse)
async def list_contacts(
    client_id: UUID | None = None,
    lead_id: UUID | None = None,
    partner_id: UUID | None = None,
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await CommunicationHubService.list_contacts(
        db,
        client_id=client_id,
        lead_id=lead_id,
        partner_id=partner_id,
        search=search,
        skip=skip,
        limit=limit,
    )


@router.post("/contacts", response_model=CommunicationContactResponse, status_code=201)
async def create_contact(
    body: CommunicationContactCreate,
    db: AsyncSession = Depends(get_db),
):
    return await CommunicationHubService.create_contact(db, body)


@router.get("/contacts/{contact_id}")
async def get_contact(
    contact_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await CommunicationHubService.get_contact(db, contact_id)


@router.get("/threads", response_model=CommunicationThreadListResponse)
async def list_threads(
    client_id: UUID | None = None,
    contact_id: UUID | None = None,
    lead_id: UUID | None = None,
    channel: str | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await CommunicationHubService.list_threads(
        db,
        client_id=client_id,
        contact_id=contact_id,
        lead_id=lead_id,
        channel=channel,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post("/threads", response_model=CommunicationThreadResponse, status_code=201)
async def create_thread(
    body: CommunicationThreadCreate,
    db: AsyncSession = Depends(get_db),
):
    return await CommunicationHubService.create_thread(db, body)


@router.get("/threads/{thread_id}", response_model=CommunicationThreadDetailResponse)
async def get_thread(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await CommunicationHubService.get_thread(db, thread_id)


@router.post("/threads/{thread_id}/messages", response_model=CommunicationMessageStoredResponse, status_code=201)
async def add_message(
    thread_id: UUID,
    body: CommunicationMessageCreate,
    db: AsyncSession = Depends(get_db),
):
    return await CommunicationHubService.add_message(db, thread_id, body)


@router.post("/threads/{thread_id}/ai-summary", response_model=CommunicationAiSummaryResponse)
async def ai_summary(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CommunicationHubService.ai_summary(db, thread_id),
        label="communications.ai-summary",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/threads/{thread_id}/extract-crm", response_model=CommunicationCrmExtractResponse)
async def extract_crm(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CommunicationCrmService.extract_crm(db, thread_id),
        label="communications.extract-crm",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/threads/{thread_id}/suggest-reply", response_model=CommunicationCrmSuggestReplyResponse)
async def suggest_reply(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CommunicationCrmService.suggest_reply(db, thread_id),
        label="communications.suggest-reply",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/threads/{thread_id}/link-lead")
async def link_lead(
    thread_id: UUID,
    body: CommunicationLinkLeadRequest,
    db: AsyncSession = Depends(get_db),
):
    return await CommunicationHubService.link_lead(db, thread_id, body.lead_id)


@router.post("/threads/{thread_id}/create-lead", response_model=CommunicationCreateLeadResponse)
async def create_lead_from_thread(
    thread_id: UUID,
    body: CommunicationCrmCreateLeadRequest | None = Body(None),
    db: AsyncSession = Depends(get_db),
):
    return await CommunicationCrmService.create_lead_from_thread(db, thread_id, body)


@router.post("/threads/{thread_id}/create-task", response_model=CommunicationCrmCreateTaskResponse, status_code=201)
async def create_task_from_thread(
    thread_id: UUID,
    body: CommunicationCrmCreateTaskRequest,
    db: AsyncSession = Depends(get_db),
):
    return await CommunicationCrmService.create_task(db, thread_id, body)
