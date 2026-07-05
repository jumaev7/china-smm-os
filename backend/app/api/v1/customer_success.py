"""Customer Success & Factory ROI Center API."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.customer_success import (
    AdminTenantSummary,
    ChurnRiskItem,
    CustomerSuccessDashboardResponse,
    CustomerSuccessSummaryResponse,
    ExecutiveReport,
    RoiConfigWeights,
)
from app.schemas.customer_success_journey import (
    CustomerSuccessJourneyDashboard,
    JourneyAdminOverview,
    JourneyDismissRecommendationResponse,
    JourneyRefreshResponse,
    NorthStarGoalOption,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.customer_success_service import CustomerSuccessService
from app.services.customer_success_journey_service import CustomerSuccessJourneyService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/customer-success", tags=["customer-success"])
SUMMARY_TIMEOUT_SEC = 1.0


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if admin:
        return None
    if user:
        return user.tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_customer_success_view(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> None:
    if admin:
        return
    if user:
        if user.has_permission("leads.view") or user.has_permission("buyers.view"):
            return
        raise HTTPException(status_code=403, detail="Permission denied")
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_admin(admin: CurrentAdminUser | None) -> None:
    if not admin:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/journey", response_model=CustomerSuccessJourneyDashboard)
async def customer_success_journey(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    if admin:
        raise HTTPException(status_code=400, detail="Journey dashboard requires tenant context")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return await run_guarded(
        CustomerSuccessJourneyService.dashboard(db, user.tenant_id),
        label="customer-success.journey",
    )


@router.get("/journey/checkpoints", response_model=CustomerSuccessJourneyDashboard)
async def customer_success_journey_checkpoints(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    if admin:
        raise HTTPException(status_code=400, detail="Journey checkpoints require tenant context")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return await run_guarded(
        CustomerSuccessJourneyService.dashboard(db, user.tenant_id),
        label="customer-success.journey.checkpoints",
    )


@router.get("/journey/north-star-options", response_model=list[NorthStarGoalOption])
async def customer_success_journey_north_star_options():
    return CustomerSuccessJourneyService.north_star_options()


@router.post("/journey/refresh", response_model=JourneyRefreshResponse)
async def customer_success_journey_refresh(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    if admin:
        raise HTTPException(status_code=400, detail="Journey refresh requires tenant context")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return await run_guarded(
        CustomerSuccessJourneyService.refresh(db, user.tenant_id),
        label="customer-success.journey.refresh",
    )


@router.post(
    "/journey/recommendations/{recommendation_id}/dismiss",
    response_model=JourneyDismissRecommendationResponse,
)
async def customer_success_journey_dismiss_recommendation(
    recommendation_id: str,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    if admin:
        raise HTTPException(status_code=400, detail="Journey dismiss requires tenant context")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return await run_guarded(
        CustomerSuccessJourneyService.dismiss_recommendation(
            db, user.tenant_id, recommendation_id,
        ),
        label="customer-success.journey.dismiss",
    )


@router.get("/admin/journey-overview", response_model=JourneyAdminOverview)
async def admin_journey_overview(
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(admin)
    return await run_guarded(
        CustomerSuccessJourneyService.admin_overview(db),
        label="customer-success.admin.journey-overview",
    )


@router.get("/dashboard", response_model=CustomerSuccessDashboardResponse)
async def customer_success_dashboard(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        CustomerSuccessService.dashboard(db, tenant_id),
        label="customer-success.dashboard",
    )


@router.get("/summary", response_model=CustomerSuccessSummaryResponse)
async def customer_success_summary(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        CustomerSuccessService.summary(db, tenant_id),
        label="customer-success.summary",
        timeout=SUMMARY_TIMEOUT_SEC,
    )


@router.get("/roi")
async def factory_roi_dashboard(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        CustomerSuccessService.roi_dashboard(db, tenant_id),
        label="customer-success.roi",
    )


@router.post("/roi/calculate")
async def calculate_roi(
    config: RoiConfigWeights | None = None,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        CustomerSuccessService.roi_dashboard(db, tenant_id, config),
        label="customer-success.roi.calculate",
    )


@router.get("/adoption")
async def adoption_dashboard(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        CustomerSuccessService.adoption_dashboard(db, tenant_id),
        label="customer-success.adoption",
    )


@router.get("/business-impact")
async def business_impact_dashboard(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        CustomerSuccessService.business_impact_dashboard(db, tenant_id),
        label="customer-success.business-impact",
    )


@router.get("/reports/{period}", response_model=ExecutiveReport)
async def executive_report(
    period: str,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    if period not in ("monthly", "quarterly"):
        raise HTTPException(status_code=400, detail="Period must be monthly or quarterly")
    _require_customer_success_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        CustomerSuccessService.executive_report(db, tenant_id, period),
        label=f"customer-success.report.{period}",
    )


@router.get("/insights")
async def ai_insights(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_customer_success_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    dash = await run_guarded(
        CustomerSuccessService.dashboard(db, tenant_id),
        label="customer-success.insights",
    )
    return {"insights": dash.insights, "generated_at": dash.generated_at}


@router.get("/admin/tenants", response_model=list[AdminTenantSummary])
async def admin_tenant_overview(
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(admin)
    return await run_guarded(
        CustomerSuccessService.admin_tenant_overview(db),
        label="customer-success.admin.tenants",
    )


@router.get("/admin/churn-risk", response_model=list[ChurnRiskItem])
async def admin_churn_risk(
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(admin)
    return await run_guarded(
        CustomerSuccessService.churn_risk_report(db),
        label="customer-success.admin.churn-risk",
    )
