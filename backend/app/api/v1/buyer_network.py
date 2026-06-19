"""Export Buyer Network v1 — global buyer intelligence endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.buyer_network import (
    BuyerNetworkExecutiveSummary,
    BuyerNetworkGraphResponse,
    BuyerNetworkInsightsResponse,
    BuyerNetworkOverview,
    BuyerNetworkProfilesResponse,
    BuyerNetworkRecalculateRequest,
    BuyerNetworkRecalculateResponse,
    BuyerNetworkRelationshipsResponse,
    BuyerNetworkSummaryWidget,
    BuyerNetworkTopBuyersResponse,
)
from app.services.buyer_network_service import BuyerNetworkService

router = APIRouter(prefix="/buyer-network", tags=["buyer-network"])


@router.get("/overview", response_model=BuyerNetworkOverview)
async def buyer_network_overview(
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerNetworkService.overview(db, tenant_id=tenant_id),
        label="buyer_network.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/profiles", response_model=BuyerNetworkProfilesResponse)
async def buyer_network_profiles(
    country: str | None = None,
    industry: str | None = None,
    classification: str | None = None,
    buyer_status: str | None = None,
    tenant_id: UUID | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerNetworkService.list_profiles(
            db,
            country=country,
            industry=industry,
            classification=classification,
            buyer_status=buyer_status,
            tenant_id=tenant_id,
            skip=skip,
            limit=limit,
        ),
        label="buyer_network.profiles",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/relationships", response_model=BuyerNetworkRelationshipsResponse)
async def buyer_network_relationships(
    tenant_id: UUID | None = Query(None),
    buyer_id: UUID | None = None,
    relationship_type: str | None = Query(
        None,
        description="discovered | contacted | active | customer | strategic",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerNetworkService.list_relationships(
            db,
            tenant_id=tenant_id,
            buyer_id=buyer_id,
            relationship_type=relationship_type,
            skip=skip,
            limit=limit,
        ),
        label="buyer_network.relationships",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/graph", response_model=BuyerNetworkGraphResponse)
async def buyer_network_graph(
    buyer_id: UUID | None = None,
    limit: int = Query(12, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerNetworkService.graph(db, buyer_id=buyer_id, limit=limit),
        label="buyer_network.graph",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/insights", response_model=BuyerNetworkInsightsResponse)
async def buyer_network_insights(
    tenant_id: UUID | None = Query(None),
    limit: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerNetworkService.insights(db, tenant_id=tenant_id, limit=limit),
        label="buyer_network.insights",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/top-buyers", response_model=BuyerNetworkTopBuyersResponse)
async def buyer_network_top_buyers(
    tenant_id: UUID | None = Query(None),
    limit: int = Query(10, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerNetworkService.top_buyers(db, tenant_id=tenant_id, limit=limit),
        label="buyer_network.top_buyers",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/executive-summary", response_model=BuyerNetworkExecutiveSummary)
async def buyer_network_executive_summary(
    tenant_id: UUID | None = Query(None),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerNetworkService.executive_summary(db, tenant_id=tenant_id, limit=limit),
        label="buyer_network.executive_summary",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary-widget", response_model=BuyerNetworkSummaryWidget)
async def buyer_network_summary_widget(
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerNetworkService.summary_widget(db, tenant_id=tenant_id),
        label="buyer_network.summary_widget",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/recalculate", response_model=BuyerNetworkRecalculateResponse)
async def buyer_network_recalculate(
    body: BuyerNetworkRecalculateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or BuyerNetworkRecalculateRequest()
    return await run_guarded(
        BuyerNetworkService.recalculate(db, tenant_id=req.tenant_id, limit=req.limit),
        label="buyer_network.recalculate",
        timeout=SCAN_TIMEOUT_SEC,
    )
