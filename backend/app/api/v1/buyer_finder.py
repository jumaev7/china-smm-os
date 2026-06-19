from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.schemas.buyer_finder import BuyerFinderAnalyzeResponse, BuyerFinderProductResponse
from app.services.buyer_finder_service import BuyerFinderService

router = APIRouter(prefix="/buyer-finder", tags=["buyer-finder"])


@router.get("/product/{product_id}", response_model=BuyerFinderProductResponse)
async def get_buyer_recommendations(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await BuyerFinderService.get_for_product(db, product_id)


@router.post("/analyze/{product_id}", response_model=BuyerFinderAnalyzeResponse)
async def analyze_buyer_recommendations(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        BuyerFinderService.analyze_product(db, product_id),
        label="buyer_finder.analyze",
        timeout=SCAN_TIMEOUT_SEC,
    )
