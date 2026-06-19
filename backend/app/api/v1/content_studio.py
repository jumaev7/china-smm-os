from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.schemas.content_studio import (
    ContentStudioGenerateRequest,
    ContentStudioGenerateResponse,
    ContentStudioSuggestionsRequest,
    ContentStudioSuggestionsResponse,
)
from app.services.content_studio_service import ContentStudioService

router = APIRouter(prefix="/content-studio", tags=["content-studio"])


@router.post("/generate", response_model=ContentStudioGenerateResponse)
async def content_studio_generate(
    body: ContentStudioGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ContentStudioService.generate(db, body),
        label="content-studio.generate",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/suggestions", response_model=ContentStudioSuggestionsResponse)
async def content_studio_suggestions(
    client_id: UUID,
    campaign_id: UUID | None = None,
    media_asset_ids: list[UUID] = Query(default=[]),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ContentStudioService.suggestions(
            db,
            ContentStudioSuggestionsRequest(
                client_id=client_id,
                campaign_id=campaign_id,
                media_asset_ids=media_asset_ids,
            ),
        ),
        label="content-studio.suggestions",
        timeout=SCAN_TIMEOUT_SEC,
    )
