from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.schemas.content_repurpose import (
    ContentRepurposeGenerateRequest,
    ContentRepurposeGenerateResponse,
    ContentRepurposeSuggestionsRequest,
    ContentRepurposeSuggestionsResponse,
    RepurposeSourceType,
)
from app.services.content_repurpose_service import ContentRepurposeService

router = APIRouter(prefix="/content-repurpose", tags=["content-repurpose"])


@router.post("/generate", response_model=ContentRepurposeGenerateResponse)
async def content_repurpose_generate(
    body: ContentRepurposeGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ContentRepurposeService.generate(db, body),
        label="content-repurpose.generate",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/suggestions", response_model=ContentRepurposeSuggestionsResponse)
async def content_repurpose_suggestions(
    client_id: UUID,
    source_type: RepurposeSourceType,
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ContentRepurposeService.suggestions(
            db,
            ContentRepurposeSuggestionsRequest(
                client_id=client_id,
                source_type=source_type,
                source_id=source_id,
            ),
        ),
        label="content-repurpose.suggestions",
        timeout=SCAN_TIMEOUT_SEC,
    )
