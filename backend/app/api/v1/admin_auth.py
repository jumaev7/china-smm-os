"""Admin Authentication & RBAC v1 — login, session, user management, audit."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin, require_admin_permission
from app.core.admin_route_registry import permission_route_matrix
from app.core.config import settings
from app.core.database import get_db
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.admin_auth import (
    AdminAuthLoginRequest,
    AdminAuthLoginResponse,
    AdminAuthLogoutResponse,
    AdminAuthMeResponse,
    AdminAuthRefreshRequest,
    AdminAuthRefreshResponse,
    AdminBootstrapResponse,
    AdminUserResponse,
)
from app.schemas.admin_rbac import (
    AdminAuditLogListResponse,
    AdminCreateClientAccountRequest,
    AdminCreateClientAccountResponse,
    AdminPermissionsResponse,
    AdminPlatformAnalyticsResponse,
    AdminPlatformBillingResponse,
    AdminPlatformTenantsResponse,
    AdminRolesResponse,
    AdminSecurityChecksResponse,
    AdminSecurityStatusResponse,
    AdminSessionListResponse,
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserUpdateRequest,
)
from app.services.admin_client_provisioning_service import AdminClientProvisioningService
from app.services.admin_auth_service import AdminAuthService
from app.services.admin_rbac_service import AdminRbacService, CurrentAdminUser
from app.services.admin_security_service import AdminSecurityService
from app.services.tenant_operations_service import TenantOperationsService
from app.schemas.tenant_operations import TenantOperationsResponse

router = APIRouter(prefix="/admin-auth", tags=["admin-auth"])


@router.post("/login", response_model=AdminAuthLoginResponse)
async def admin_login(
    body: AdminAuthLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await AdminAuthService.login(db, email=body.email, password=body.password, request=request)


@router.post("/logout", response_model=AdminAuthLogoutResponse)
async def admin_logout(
    request: Request,
    admin: CurrentAdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminAuthService.logout(
        db, user_id=admin.id, session_id=admin.session_id, request=request,
    )


@router.get("/me", response_model=AdminAuthMeResponse)
async def admin_me(
    admin: CurrentAdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await AdminAuthService.load_user_by_id(db, admin.id)
    if not user:
        raise HTTPException(status_code=404, detail="Admin user not found")
    return await AdminAuthService.me(db, user, session_id=admin.session_id)


@router.post("/refresh", response_model=AdminAuthRefreshResponse)
async def admin_refresh(
    body: AdminAuthRefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await AdminAuthService.refresh_session(db, body.refresh_token, request=request)


@router.post("/bootstrap", response_model=AdminBootstrapResponse)
async def admin_bootstrap(db: AsyncSession = Depends(get_db)):
    if settings.APP_ENV != "development":
        raise HTTPException(
            status_code=403,
            detail="Bootstrap disabled — only available when APP_ENV=development",
        )
    result = await AdminAuthService.ensure_bootstrap_admin(db)
    if not result:
        raise HTTPException(
            status_code=403,
            detail="Bootstrap unavailable — set ADMIN_BOOTSTRAP_EMAIL/PASSWORD in development or create admin manually",
        )
    return result


@router.get("/users", response_model=AdminUserListResponse)
async def list_admin_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.full")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminRbacService.list_users(db, admin, skip=skip, limit=limit)


@router.post("/users", response_model=AdminUserResponse, status_code=201)
async def create_admin_user(
    body: AdminUserCreateRequest,
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.full")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminRbacService.create_user(
        db,
        admin,
        email=body.email,
        role=body.role,
        password=body.password,
        status=body.status,
    )


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_admin_user(
    user_id: UUID,
    body: AdminUserUpdateRequest,
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.full")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminRbacService.update_user(
        db,
        admin,
        user_id,
        role=body.role,
        email=body.email,
        password=body.password,
        status=body.status,
    )


@router.get("/roles", response_model=AdminRolesResponse)
async def list_admin_roles(
    admin: CurrentAdminUser = Depends(get_current_admin),
):
    from app.core.admin_permissions import ADMIN_ROLES, permissions_for_role

    AdminRbacService.assert_permission(admin, "logs.read")
    return {
        "roles": sorted(ADMIN_ROLES),
        "role_permissions": {
            role: permissions_for_role(role) for role in sorted(ADMIN_ROLES)
        },
    }


@router.get("/permissions", response_model=AdminPermissionsResponse)
async def list_admin_permissions(
    admin: CurrentAdminUser = Depends(get_current_admin),
):
    from app.core.admin_permissions import ADMIN_ROLES, permissions_for_role

    AdminRbacService.assert_permission(admin, "logs.read")
    perms: set[str] = set()
    for role in ADMIN_ROLES:
        perms.update(permissions_for_role(role))
    return {
        "permissions": sorted(perms),
        "role_permissions": {
            role: permissions_for_role(role) for role in sorted(ADMIN_ROLES)
        },
    }


@router.get("/audit-logs", response_model=AdminAuditLogListResponse)
async def list_admin_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    event_type: str | None = Query(None),
    admin: CurrentAdminUser = Depends(require_admin_permission("logs.read")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminRbacService.list_audit_logs(
        db, admin, skip=skip, limit=limit, event_type=event_type,
    )


@router.get("/sessions", response_model=AdminSessionListResponse)
async def list_admin_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    status: str | None = Query(None),
    admin: CurrentAdminUser = Depends(require_admin_permission("logs.read")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminRbacService.list_sessions(db, admin, skip=skip, limit=limit, status=status)


@router.get("/platform/tenants", response_model=AdminPlatformTenantsResponse)
async def admin_platform_tenants(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminRbacService.platform_tenants(db, admin, skip=skip, limit=limit)


@router.post(
    "/platform/tenants/create-client",
    response_model=AdminCreateClientAccountResponse,
    status_code=201,
)
async def admin_create_client_account(
    body: AdminCreateClientAccountRequest,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminClientProvisioningService.create_client_account(
        db,
        admin,
        company_name=body.company_name,
        owner_email=body.owner_email,
        owner_name=body.owner_name,
        phone=body.phone,
        wechat=body.wechat,
        whatsapp=body.whatsapp,
        country=body.country,
        industry=body.industry,
        plan=body.plan,
        locale=body.locale,
    )


@router.get(
    "/platform/tenants/{tenant_id}/operations",
    response_model=TenantOperationsResponse,
)
async def admin_tenant_operations(
    tenant_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await TenantOperationsService.get_tenant_operations(db, admin, tenant_id)


@router.get("/platform/billing", response_model=AdminPlatformBillingResponse)
async def admin_platform_billing(
    admin: CurrentAdminUser = Depends(require_admin_permission("billing.read")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminRbacService.platform_billing(db, admin)


@router.get("/platform/analytics", response_model=AdminPlatformAnalyticsResponse)
async def admin_platform_analytics(
    admin: CurrentAdminUser = Depends(require_admin_permission("analytics.read")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminRbacService.platform_analytics(db, admin)


@router.get("/security-checks", response_model=AdminSecurityChecksResponse)
async def admin_security_checks(
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminRbacService.security_checks(db)


@router.get("/security-status", response_model=AdminSecurityStatusResponse)
async def admin_security_status(
    request: Request,
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
    db: AsyncSession = Depends(get_db),
):
    return await AdminSecurityService.security_status(request.app, db)


@router.get("/platform/subscriptions")
async def admin_platform_subscriptions(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    admin: CurrentAdminUser = Depends(require_admin_permission("subscriptions.read")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.subscription_service import SubscriptionService

    return await SubscriptionService.list_subscriptions(db, tenant_id=None, skip=skip, limit=limit)


@router.post("/platform/subscriptions/{subscription_id}/suspend")
async def admin_suspend_subscription(
    subscription_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("subscriptions.manage")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.subscription_service import SubscriptionService

    return await SubscriptionService.suspend_subscription(db, subscription_id)


@router.get("/platform/settings")
async def admin_platform_settings(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
):
    return {
        "app_env": settings.APP_ENV,
        "demo_mode": settings.DEMO_MODE,
        "bootstrap_enabled": settings.APP_ENV == "development",
        "jwt_secrets_separated": bool(
            settings.ADMIN_SECRET_KEY
            and settings.TENANT_SECRET_KEY
            and settings.ADMIN_SECRET_KEY != settings.TENANT_SECRET_KEY
        ),
        "permission_route_matrix": permission_route_matrix(),
    }


@router.post("/platform/billing/suspend-subscription")
async def admin_billing_suspend_subscription(
    subscription_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("billing.manage")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.subscription_service import SubscriptionService

    return await SubscriptionService.suspend_subscription(db, subscription_id)


@router.get("/support/tools")
async def admin_support_tools(
    admin: CurrentAdminUser = Depends(require_admin_permission("support.tools")),
    db: AsyncSession = Depends(get_db),
):
    pending = await AdminRbacService.platform_tenants(db, admin, skip=0, limit=5)
    return {
        "support_tools_available": True,
        "recent_tenants_sample": pending.get("items", []),
        "permission_route_matrix": permission_route_matrix(),
    }
