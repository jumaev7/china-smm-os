from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.database import get_db
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from fastapi import Query
from app.schemas.attribution_link import (
    AttributionLinkCreate,
    AttributionLinkListResponse,
    AttributionLinkResponse,
)
from app.services.attribution_link_service import AttributionLinkService

router = APIRouter(tags=["attribution-redirect"])


@router.get("/r/{code}")
async def attribution_redirect(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    destination = await AttributionLinkService.record_click_and_redirect(db, code, request)
    return RedirectResponse(url=destination, status_code=302)
