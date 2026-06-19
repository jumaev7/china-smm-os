from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.executive_access import ExecutiveCopilotActor, get_executive_copilot_actor
from app.schemas.executive_copilot import (
    ExecutiveCopilotAlertsResponse,
    ExecutiveCopilotBriefingRequest,
    ExecutiveCopilotBriefingResponse,
    ExecutiveCopilotOverviewResponse,
    ExecutiveCopilotRecommendationsResponse,
    ExecutiveCopilotSummaryWidget,
)
from app.services.executive_copilot_service import ExecutiveCopilotService
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/executive-copilot", tags=["executive-copilot"])

SUMMARY_WIDGET_TIMEOUT_SEC = 20.0


def _scoped_tenant_id(actor: ExecutiveCopilotActor, tenant_id: UUID | None) -> UUID | None:
    if actor.kind == "tenant":
        return actor.tenant_id
    return tenant_id


async def _resolve_executive_client_id(
    db: AsyncSession,
    actor: ExecutiveCopilotActor,
    client_id: UUID | None,
) -> UUID | None:
    if actor.kind != "tenant" or not actor.tenant_id:
        return client_id
    scoped_id, client_ids = await TenantService.resolve_tenant_client_scope(
        db,
        tenant_id=actor.tenant_id,
        client_id=client_id,
    )
    if scoped_id:
        return scoped_id
    if client_ids and len(client_ids) == 1:
        return client_ids[0]
    return client_id


@router.get("/overview", response_model=ExecutiveCopilotOverviewResponse)
async def executive_copilot_overview(
    client_id: UUID | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope for executive overview"),
    actor: ExecutiveCopilotActor = Depends(get_executive_copilot_actor),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ExecutiveCopilotService.overview(
            db,
            client_id=client_id,
            tenant_id=_scoped_tenant_id(actor, tenant_id),
        ),
        label="executive_copilot.overview",
    )


@router.get("/alerts", response_model=ExecutiveCopilotAlertsResponse)
async def executive_copilot_alerts(
    client_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    actor: ExecutiveCopilotActor = Depends(get_executive_copilot_actor),
    db: AsyncSession = Depends(get_db),
):
    resolved_client_id = await _resolve_executive_client_id(db, actor, client_id)
    return await run_guarded(
        ExecutiveCopilotService.alerts(db, client_id=resolved_client_id, limit=limit),
        label="executive_copilot.alerts",
    )


@router.get("/recommendations", response_model=ExecutiveCopilotRecommendationsResponse)
async def executive_copilot_recommendations(
    client_id: UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    actor: ExecutiveCopilotActor = Depends(get_executive_copilot_actor),
    db: AsyncSession = Depends(get_db),
):
    resolved_client_id = await _resolve_executive_client_id(db, actor, client_id)
    return await run_guarded(
        ExecutiveCopilotService.recommendations(db, client_id=resolved_client_id, limit=limit),
        label="executive_copilot.recommendations",
    )


@router.get("/summary-widget", response_model=ExecutiveCopilotSummaryWidget)
async def executive_copilot_summary_widget(
    client_id: UUID | None = None,
    actor: ExecutiveCopilotActor = Depends(get_executive_copilot_actor),
    db: AsyncSession = Depends(get_db),
):
    resolved_client_id = await _resolve_executive_client_id(db, actor, client_id)
    return await run_guarded(
        ExecutiveCopilotService.summary_widget(db, client_id=resolved_client_id),
        label="executive_copilot.summary_widget",
        timeout=SUMMARY_WIDGET_TIMEOUT_SEC,
    )


@router.post("/generate-briefing", response_model=ExecutiveCopilotBriefingResponse)
async def executive_copilot_generate_briefing(
    body: ExecutiveCopilotBriefingRequest | None = None,
    actor: ExecutiveCopilotActor = Depends(get_executive_copilot_actor),
    db: AsyncSession = Depends(get_db),
):
    client_id = body.client_id if body else None
    resolved_client_id = await _resolve_executive_client_id(db, actor, client_id)
    return await run_guarded(
        ExecutiveCopilotService.generate_briefing(db, client_id=resolved_client_id),
        label="executive_copilot.generate_briefing",
        timeout=SCAN_TIMEOUT_SEC,
    )
