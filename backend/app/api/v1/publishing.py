from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.publishing import (
    PublishingAccountCreate,
    PublishingAccountUpdate,
    PublishingAccountResponse,
    PublishingAccountListResponse,
    ScheduledPublishDebugResponse,
    PublishingCalendarResponse,
    PublishingQueueResponse,
    PublishingQueueActionResponse,
    PublishAttemptListResponse,
    PublishAttemptResponse,
    PublishAttemptActionResponse,
)
from app.schemas.publish_alerts import (
    PublishAlertAcknowledgeResponse,
    PublishAlertCountsResponse,
    PublishAlertListResponse,
    PublishAlertResolveRequest,
    PublishAlertResolveResponse,
    TelegramAlertSettingsResponse,
    TelegramAlertSettingsUpdate,
    TelegramDeliveryListResponse,
    TelegramEnrollmentConfirmRequest,
    TelegramEnrollmentConfirmResponse,
    TelegramEnrollmentResponse,
    TelegramRecipientListResponse,
    TelegramRecipientRemoveResponse,
    TelegramTestSendRequest,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.publishing_account_service import PublishingAccountService
from app.services.publishing_calendar_service import PublishingCalendarService
from app.services.publishing_queue_service import PublishingQueueService
from app.services.publish_attempt_ops_service import PublishAttemptOpsService
from app.services.publish_operator_alert_service import PublishOperatorAlertService
from app.services.publish_alert_telegram_enrollment_service import (
    PublishAlertTelegramEnrollmentService,
)
from app.services.publish_alert_telegram_outbox_service import PublishAlertTelegramOutboxService
from app.services.publishing_tenant_scope import resolve_publishing_tenant_id
from app.services.scheduled_publish_diagnostics_service import ScheduledPublishDiagnosticsService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/publishing", tags=["publishing"])


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
    tenant_id: UUID | None,
) -> UUID:
    return resolve_publishing_tenant_id(user, admin, tenant_id)


def _actor_id(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if user is not None:
        return getattr(user, "id", None) or getattr(user, "user_id", None)
    if admin is not None:
        return getattr(admin, "id", None) or getattr(admin, "user_id", None)
    return None


def _reveal_chat_id(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> bool:
    """Full chat IDs only for tenant owner/manager or platform admin."""
    if admin is not None:
        return True
    if user is None:
        return False
    role = getattr(user, "role", None)
    return role in ("owner", "manager")


def _require_tenant_admin_for_settings(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> None:
    if admin is not None:
        return
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    role = getattr(user, "role", None)
    if role not in ("owner", "manager"):
        raise HTTPException(
            status_code=403,
            detail="Tenant owner or manager role required to change Telegram alert settings",
        )

@router.get("/accounts", response_model=PublishingAccountListResponse)
async def list_publishing_accounts(
    platform: str | None = None,
    status: str | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    items, total = await PublishingAccountService.list_all(
        db, scope_tenant_id, platform=platform, status=status,
    )
    return {
        "items": [PublishingAccountService._serialize(a) for a in items],
        "total": total,
    }


@router.post("/accounts", response_model=PublishingAccountResponse, status_code=201)
async def create_publishing_account(
    data: PublishingAccountCreate,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    account = await PublishingAccountService.create(db, scope_tenant_id, data)
    return PublishingAccountService._serialize(account)


@router.patch("/accounts/{account_id}", response_model=PublishingAccountResponse)
async def update_publishing_account(
    account_id: UUID,
    data: PublishingAccountUpdate,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    account = await PublishingAccountService.update(db, scope_tenant_id, account_id, data)
    return PublishingAccountService._serialize(account)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_publishing_account(
    account_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    await PublishingAccountService.delete(db, scope_tenant_id, account_id)


@router.get("/queue", response_model=PublishingQueueResponse)
async def publishing_queue(
    client_timezone: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Scheduled / publishing queue with block reasons and safety status."""
    return await PublishingQueueService.list_queue(db, client_timezone=client_timezone)


@router.post("/queue/{content_id}/cancel", response_model=PublishingQueueActionResponse)
async def cancel_scheduled_queue_item(
    content_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await PublishingQueueService.cancel_schedule(db, content_id)


@router.post("/queue/{content_id}/retry", response_model=PublishingQueueActionResponse)
async def retry_scheduled_queue_item(
    content_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await PublishingQueueService.retry_publish(db, content_id)


@router.post("/queue/{content_id}/send-client-review", response_model=PublishingQueueActionResponse)
async def send_client_review_queue_item(
    content_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await PublishingQueueService.send_client_review(db, content_id)


@router.get("/scheduled-debug", response_model=ScheduledPublishDebugResponse)
async def scheduled_publish_debug(
    client_timezone: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Diagnostics: why scheduled content is or is not picked up by the scheduler."""
    return await ScheduledPublishDiagnosticsService.list_scheduled_debug(
        db, client_timezone=client_timezone,
    )


@router.get("/calendar", response_model=PublishingCalendarResponse)
async def publishing_calendar(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    client_id: UUID | None = None,
    platform: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Scheduled, published, and failed posts for the publishing calendar view."""
    if to_date < from_date:
        from_date, to_date = to_date, from_date
    return await PublishingCalendarService.list_calendar(
        db,
        from_date=from_date,
        to_date=to_date,
        client_id=client_id,
        platform=platform,
        status=status,
    )


@router.get("/attempts", response_model=PublishAttemptListResponse)
async def list_publish_attempts(
    status: str | None = Query(
        None,
        description="failed | retrying | in_progress | operator_review | exhausted",
    ),
    platform: str | None = None,
    content_id: UUID | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """List failed, retrying, stale, and operator-review publish attempts."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return await PublishAttemptOpsService.list_attempts(
        db,
        tenant_id=scope_tenant_id,
        status=status,
        platform=platform,
        content_id=content_id,
        limit=limit,
        offset=offset,
    )


@router.get("/attempts/{attempt_id}", response_model=PublishAttemptResponse)
async def get_publish_attempt(
    attempt_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return await PublishAttemptOpsService.get_attempt(
        db, attempt_id, tenant_id=scope_tenant_id,
    )


@router.post("/attempts/{attempt_id}/retry", response_model=PublishAttemptActionResponse)
async def retry_publish_attempt(
    attempt_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Manually retry an eligible publish attempt; blocks unsafe duplicates."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return await PublishAttemptOpsService.manual_retry(
        db, attempt_id, tenant_id=scope_tenant_id,
    )


@router.get("/alerts/counts", response_model=PublishAlertCountsResponse)
async def publish_alert_counts(
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Open / acknowledged / severity counts for the publishing alert inbox."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return await PublishOperatorAlertService.counts(db, scope_tenant_id)


@router.get("/alerts", response_model=PublishAlertListResponse)
async def list_publish_alerts(
    state: str | None = Query(None, description="open | acknowledged | resolved"),
    severity: str | None = Query(None, description="warning | critical | info"),
    platform: str | None = None,
    client_id: UUID | None = None,
    alert_type: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """List deduplicated publishing operator alerts (tenant-scoped)."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return await PublishOperatorAlertService.list_alerts(
        db,
        scope_tenant_id,
        page=page,
        page_size=page_size,
        state=state,
        severity=severity,
        platform=platform,
        client_id=client_id,
        alert_type=alert_type,
        created_from=created_from,
        created_to=created_to,
    )


@router.post("/alerts/{alert_id}/acknowledge", response_model=PublishAlertAcknowledgeResponse)
async def acknowledge_publish_alert(
    alert_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    # Service returns a detached-safe response model (no ORM after commit).
    response = await PublishOperatorAlertService.acknowledge(
        db,
        scope_tenant_id,
        alert_id,
        actor_id=_actor_id(user, admin),
    )
    await db.commit()
    return response


@router.post("/alerts/{alert_id}/resolve", response_model=PublishAlertResolveResponse)
async def resolve_publish_alert(
    alert_id: UUID,
    body: PublishAlertResolveRequest | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    note = body.note if body else None
    # Service returns a detached-safe response model (no ORM after commit).
    response = await PublishOperatorAlertService.resolve_manual(
        db,
        scope_tenant_id,
        alert_id,
        actor_id=_actor_id(user, admin),
        note=note,
    )
    await db.commit()
    return response


# ── Telegram outbound delivery (separate from in-app alerts) ───────────────


@router.get(
    "/alerts/telegram-settings",
    response_model=TelegramAlertSettingsResponse,
)
async def get_telegram_alert_settings(
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """View tenant Telegram operator-alert delivery settings (not client destinations)."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    row = await PublishAlertTelegramOutboxService.get_settings(db, scope_tenant_id)
    return PublishAlertTelegramOutboxService.serialize_settings(
        row,
        reveal_chat_id=_reveal_chat_id(user, admin),
    )


@router.put(
    "/alerts/telegram-settings",
    response_model=TelegramAlertSettingsResponse,
)
async def update_telegram_alert_settings(
    body: TelegramAlertSettingsUpdate,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Configure numeric recipient + filters. Requires tenant owner/manager."""
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    payload = body.model_dump(exclude_unset=True)
    row = await PublishAlertTelegramOutboxService.update_settings(
        db,
        scope_tenant_id,
        actor_id=_actor_id(user, admin),
        payload=payload,
    )
    # Build detached-safe DTO before commit — never lazy-load expired ORM attrs after.
    response = PublishAlertTelegramOutboxService.serialize_settings(
        row,
        reveal_chat_id=_reveal_chat_id(user, admin),
    )
    await db.commit()
    return response


@router.get(
    "/alerts/telegram-deliveries",
    response_model=TelegramDeliveryListResponse,
)
async def list_telegram_alert_deliveries(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Recent Telegram outbox attempts for operator alerts (not in-app alert rows)."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return await PublishAlertTelegramOutboxService.list_deliveries(
        db,
        scope_tenant_id,
        page=page,
        page_size=page_size,
        status=status,
        reveal_chat_id=_reveal_chat_id(user, admin),
    )


@router.post("/alerts/telegram-deliveries/{delivery_id}/cancel")
async def cancel_telegram_alert_delivery(
    delivery_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    # Detached-safe dict from service (refreshed before serialize).
    result = await PublishAlertTelegramOutboxService.cancel_delivery(
        db,
        scope_tenant_id,
        delivery_id,
        actor_id=_actor_id(user, admin),
    )
    await db.commit()
    return result


@router.post("/alerts/telegram-deliveries/{delivery_id}/retry")
async def retry_telegram_alert_delivery(
    delivery_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    result = await PublishAlertTelegramOutboxService.manual_retry(
        db,
        scope_tenant_id,
        delivery_id,
    )
    await db.commit()
    return result


@router.post("/alerts/telegram-deliveries/test")
async def send_telegram_alert_test(
    body: TelegramTestSendRequest,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Guarded test enqueue. Refuses while global kill switch is false. Requires confirm=true."""
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    result = await PublishAlertTelegramOutboxService.enqueue_test(
        db,
        scope_tenant_id,
        actor_id=_actor_id(user, admin),
        confirm=bool(body.confirm),
    )
    await db.commit()
    return result


# ── Operator Telegram enrollment (self-serve; does not enable delivery) ────


@router.post(
    "/alerts/telegram-enrollment",
    response_model=TelegramEnrollmentResponse,
)
async def create_telegram_enrollment(
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Create a short-lived enrollment deep-link. Revokes older unfinished enrollments."""
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    actor = _actor_id(user, admin)
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    # Detached-safe dict serialized before commit.
    result = await PublishAlertTelegramEnrollmentService.create_enrollment(
        db,
        scope_tenant_id,
        actor_id=actor,
    )
    await db.commit()
    return result


@router.get(
    "/alerts/telegram-enrollment",
    response_model=TelegramEnrollmentResponse,
)
async def get_telegram_enrollment_status(
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Current enrollment status for this tenant admin (masked candidate identity)."""
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    result = await PublishAlertTelegramEnrollmentService.get_status(
        db,
        scope_tenant_id,
        actor_id=_actor_id(user, admin),
    )
    await db.commit()
    return result


@router.post(
    "/alerts/telegram-enrollment/{enrollment_id}/revoke",
    response_model=TelegramEnrollmentResponse,
)
async def revoke_telegram_enrollment(
    enrollment_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    actor = _actor_id(user, admin)
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    result = await PublishAlertTelegramEnrollmentService.revoke_enrollment(
        db,
        scope_tenant_id,
        enrollment_id,
        actor_id=actor,
    )
    await db.commit()
    return result


@router.post(
    "/alerts/telegram-enrollment/{enrollment_id}/confirm",
    response_model=TelegramEnrollmentConfirmResponse,
)
async def confirm_telegram_enrollment(
    enrollment_id: UUID,
    body: TelegramEnrollmentConfirmRequest | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Confirm a received candidate. Does not enable delivery. Idempotent."""
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    actor = _actor_id(user, admin)
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    replace = bool(body.replace_existing) if body else False
    # Detached-safe dict serialized before commit (service refreshes ORM first).
    result = await PublishAlertTelegramEnrollmentService.confirm_candidate(
        db,
        scope_tenant_id,
        enrollment_id,
        actor_id=actor,
        replace_existing=replace,
    )
    await db.commit()
    return result


@router.post(
    "/alerts/telegram-enrollment/{enrollment_id}/reject",
    response_model=TelegramEnrollmentResponse,
)
async def reject_telegram_enrollment(
    enrollment_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    actor = _actor_id(user, admin)
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    result = await PublishAlertTelegramEnrollmentService.reject_candidate(
        db,
        scope_tenant_id,
        enrollment_id,
        actor_id=actor,
    )
    await db.commit()
    return result


@router.get(
    "/alerts/telegram-recipients",
    response_model=TelegramRecipientListResponse,
)
async def list_telegram_operator_recipients(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_history: bool = Query(True),
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return await PublishAlertTelegramEnrollmentService.list_recipients(
        db,
        scope_tenant_id,
        page=page,
        page_size=page_size,
        include_history=include_history,
        reveal_chat_id=_reveal_chat_id(user, admin),
    )


@router.post(
    "/alerts/telegram-recipients/remove",
    response_model=TelegramRecipientRemoveResponse,
)
async def remove_telegram_operator_recipient(
    enrollment_id: UUID | None = Query(None),
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Remove the confirmed recipient. Clears allowlist and disables tenant delivery flag."""
    _require_tenant_admin_for_settings(user, admin)
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    actor = _actor_id(user, admin)
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    # Detached-safe dict serialized before commit (service refreshes ORM first).
    result = await PublishAlertTelegramEnrollmentService.remove_recipient(
        db,
        scope_tenant_id,
        actor_id=actor,
        enrollment_id=enrollment_id,
    )
    await db.commit()
    return result
