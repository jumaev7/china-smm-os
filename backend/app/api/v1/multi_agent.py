from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.schemas.multi_agent_team import (
    MultiAgentAgentsResponse,
    MultiAgentBriefingRequest,
    MultiAgentBriefingResponse,
    MultiAgentHealthResponse,
    MultiAgentOverviewResponse,
    MultiAgentRecommendationsResponse,
)
from app.services.multi_agent_team_service import MultiAgentTeamService

router = APIRouter(prefix="/multi-agent", tags=["multi-agent"])


@router.get("/overview", response_model=MultiAgentOverviewResponse)
async def multi_agent_overview(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MultiAgentTeamService.overview(db, client_id=client_id),
        label="multi_agent.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/agents", response_model=MultiAgentAgentsResponse)
async def multi_agent_agents(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MultiAgentTeamService.agents(db, client_id=client_id),
        label="multi_agent.agents",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/recommendations", response_model=MultiAgentRecommendationsResponse)
async def multi_agent_recommendations(
    client_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MultiAgentTeamService.recommendations(db, client_id=client_id, limit=limit),
        label="multi_agent.recommendations",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/health", response_model=MultiAgentHealthResponse)
async def multi_agent_health(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        MultiAgentTeamService.health(db, client_id=client_id),
        label="multi_agent.health",
    )


@router.post("/generate-briefing", response_model=MultiAgentBriefingResponse)
async def multi_agent_generate_briefing(
    body: MultiAgentBriefingRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    client_id = body.client_id if body else None
    return await run_guarded(
        MultiAgentTeamService.generate_briefing(db, client_id=client_id),
        label="multi_agent.generate_briefing",
        timeout=SCAN_TIMEOUT_SEC,
    )
