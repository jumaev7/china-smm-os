from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.config import settings
from app.services.ai_service import generate_content
from app.services.brand_profile import brand_profile_from_client
from app.services.context_ai_service import build_context_signals
from app.services.content_service import ContentService
from app.services.telegram_instruction_service import (
    build_generation_context_hint,
    extract_admin_instruction,
    extract_client_source_text,
)
from app.schemas.content import GenerateRequest, ContentResponse
from app.models.client import Client
from uuid import UUID

router = APIRouter(tags=["ai"])


async def _run_generation(
    content_item_id: UUID,
    source_language: str | None,
    source_text: str | None,
    context_hint: str | None,
    db: AsyncSession,
    response: Response,
) -> dict:
    """Shared logic for both generate endpoints."""
    item = await ContentService.get(db, content_item_id)

    client_result = await db.execute(select(Client).where(Client.id == item.client_id))
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Request language overrides client default; client default overrides hardcoded zh
    resolved_lang = source_language or client.source_language or "zh"
    resolved_source = source_text or extract_client_source_text(item.internal_notes)
    admin_instruction = extract_admin_instruction(item.internal_notes)
    resolved_hint = build_generation_context_hint(admin_instruction, context_hint)

    context_signals = await build_context_signals(
        db, client=client, item=item, source_text=resolved_source,
    )

    from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
    kb_block = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, context="content_generation",
    )

    try:
        generated = await generate_content(
            company_name=client.company_name,
            business_category=client.business_category,
            content_style=client.content_style,
            source_language=resolved_lang,
            source_text=resolved_source,
            context_hint=resolved_hint,
            client_notes=client.notes,
            brand_profile=brand_profile_from_client(client),
            context_signals=context_signals,
            knowledge_base_block=kb_block or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {e}")

    item = await ContentService.apply_generated(db, item.id, generated)

    # Let the client know when demo content was returned
    if settings.DEMO_MODE:
        response.headers["X-Demo-Mode"] = "true"

    return ContentService.serialize(item)


# ── Route 1: POST /api/v1/generate  (legacy, kept for compatibility) ──────────
@router.post("/generate", response_model=ContentResponse)
async def generate_via_body(
    data: GenerateRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Generate multilingual captions. Accepts full request body with content_item_id."""
    return await _run_generation(
        content_item_id=data.content_item_id,
        source_language=data.source_language,
        source_text=data.source_text,
        context_hint=data.context_hint,
        db=db,
        response=response,
    )


# ── Route 2: POST /api/v1/content/{content_id}/generate  (RESTful) ────────────
class GenerateBodyOptional(GenerateRequest):
    content_item_id: UUID | None = None  # ignored — taken from path


@router.post("/content/{content_id}/generate", response_model=ContentResponse)
async def generate_for_content(
    content_id: UUID,
    response: Response,
    data: GenerateBodyOptional | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate multilingual captions for a specific content item.
    content_item_id is taken from the URL path.
    Body is optional — send source_text / context_hint / source_language as needed.
    """
    body = data or GenerateBodyOptional(content_item_id=content_id)
    return await _run_generation(
        content_item_id=content_id,
        source_language=body.source_language,
        source_text=body.source_text,
        context_hint=body.context_hint,
        db=db,
        response=response,
    )
