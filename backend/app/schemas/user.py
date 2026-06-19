from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

UiLanguage = Literal["ru", "en", "zh"]


class UserSettingsResponse(BaseModel):
    id: UUID
    preferred_language: UiLanguage
    # Future-ready: content languages independent from UI (not auto-translated)
    default_proposal_language: UiLanguage | None = None
    default_content_language: UiLanguage | None = None
    updated_at: datetime


class UserLanguageUpdate(BaseModel):
    preferred_language: UiLanguage = Field(..., description="UI interface language")
