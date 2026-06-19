import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.assistant import (
    AssistantApplyRequest,
    AssistantApplyResponse,
    AssistantChatRequest,
    AssistantChatResponse,
)
from app.services.assistant_service import apply_assistant_patch, assistant_chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantChatResponse)
async def assistant_chat_endpoint(
    data: AssistantChatRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await assistant_chat(
            db,
            message=data.message,
            page_context=data.page_context.model_dump(),
            client_id=data.client_id,
            content_id=data.content_id,
            history=[h.model_dump() for h in data.history],
            auto_apply=data.auto_apply,
        )
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Assistant chat failed: %s", exc, exc_info=True)
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail=f"Assistant error: {exc}") from exc

    return AssistantChatResponse(**result)


@router.post("/apply", response_model=AssistantApplyResponse)
async def assistant_apply_endpoint(
    data: AssistantApplyRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        applied_fields = await apply_assistant_patch(
            db,
            data.content_id,
            data.patch,
            auto=data.auto,
        )
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Assistant apply failed: %s", exc, exc_info=True)
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail=f"Assistant apply error: {exc}") from exc

    return AssistantApplyResponse(applied_fields=applied_fields)
