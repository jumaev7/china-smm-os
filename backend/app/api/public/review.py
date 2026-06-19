from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.content_review_service import ContentReviewService

router = APIRouter(tags=["public-review"])


class ClientReviewFeedbackRequest(BaseModel):
    feedback: str = Field(..., min_length=1, max_length=2000)


@router.get("/review/{token}")
async def get_public_review(token: str, db: AsyncSession = Depends(get_db)):
    return await ContentReviewService.get_public_review(db, token)


@router.post("/review/{token}/approve")
async def public_review_approve(token: str, db: AsyncSession = Depends(get_db)):
    return await ContentReviewService.client_approve(db, token)


@router.post("/review/{token}/request-changes")
async def public_review_request_changes(
    token: str,
    body: ClientReviewFeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ContentReviewService.client_request_changes(db, token, body.feedback)


@router.post("/review/{token}/regenerate")
async def public_review_regenerate(token: str, db: AsyncSession = Depends(get_db)):
    return await ContentReviewService.client_regenerate(db, token, via="web")
