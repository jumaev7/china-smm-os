from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.schemas.sales_department import (
    SalesDepartmentAiBriefingResponse,
    SalesDepartmentDashboardResponse,
)
from app.services.sales_department_dashboard_service import SalesDepartmentDashboardService

router = APIRouter(prefix="/sales-department", tags=["sales-department"])


@router.get("/dashboard", response_model=SalesDepartmentDashboardResponse)
async def sales_department_dashboard(
    client_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesDepartmentDashboardService.dashboard(
            db,
            client_id=client_id,
            date_from=date_from,
            date_to=date_to,
        ),
        label="sales_department.dashboard",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/ai-briefing", response_model=SalesDepartmentAiBriefingResponse)
async def sales_department_ai_briefing(
    client_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesDepartmentDashboardService.ai_briefing(db, client_id=client_id),
        label="sales_department.ai_briefing",
        timeout=SCAN_TIMEOUT_SEC,
    )
