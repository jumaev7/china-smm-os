"""Operator user settings — singleton default user for internal tool."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operator_user import DEFAULT_OPERATOR_USER_ID, SUPPORTED_UI_LANGUAGES, OperatorUser

logger = logging.getLogger(__name__)


def _serialize(user: OperatorUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "preferred_language": user.preferred_language,
        "default_proposal_language": None,
        "default_content_language": None,
        "updated_at": user.updated_at,
    }


class UserSettingsService:
    @staticmethod
    async def _ensure_default_user(db: AsyncSession) -> OperatorUser:
        result = await db.execute(
            select(OperatorUser).where(OperatorUser.id == DEFAULT_OPERATOR_USER_ID)
        )
        user = result.scalar_one_or_none()
        if user:
            return user
        user = OperatorUser(id=DEFAULT_OPERATOR_USER_ID, preferred_language="ru")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_settings(db: AsyncSession) -> dict[str, Any]:
        user = await UserSettingsService._ensure_default_user(db)
        return _serialize(user)

    @staticmethod
    async def update_language(db: AsyncSession, language: str) -> dict[str, Any]:
        if language not in SUPPORTED_UI_LANGUAGES:
            raise HTTPException(status_code=400, detail="Unsupported language")
        user = await UserSettingsService._ensure_default_user(db)
        user.preferred_language = language
        await db.commit()
        await db.refresh(user)
        logger.info("[I18N] language changed: %s", language)
        return _serialize(user)
