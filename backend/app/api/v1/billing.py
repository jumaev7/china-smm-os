from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.billing import (
    BillingOverviewResponse,
    ClientBillingResponse,
    ClientBillingUpdate,
)
from app.core.admin_access import require_admin_permission
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.billing_service import BillingService

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/overview", response_model=BillingOverviewResponse)
async def billing_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("billing.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BillingService.overview(db),
        label="billing.overview",
    )
