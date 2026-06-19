from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.user import UserLanguageUpdate, UserSettingsResponse
from app.services.user_settings_service import UserSettingsService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/settings", response_model=UserSettingsResponse)
async def get_user_settings(db: AsyncSession = Depends(get_db)):
    return await UserSettingsService.get_settings(db)


@router.patch("/language", response_model=UserSettingsResponse)
async def update_user_language(
    body: UserLanguageUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await UserSettingsService.update_language(db, body.preferred_language)
