"""Strict structured-output parsing for AI adaptation responses."""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.services.ai_platform.errors import AIOutputInvalidError


SUPPORTED_PLATFORMS = frozenset({"telegram", "facebook", "instagram", "tiktok", "linkedin"})
SUPPORTED_LOCALES = frozenset({"en", "ru", "uz", "zh"})
SUPPORTED_LENGTH_PROFILES = frozenset({"short", "standard", "extended"})
MAX_CAPTION_LENGTH = 5000
MAX_HASHTAGS = 30
MAX_HASHTAG_LENGTH = 64
_HASHTAG_RE = re.compile(r"^#?[\w\u0400-\u04FF\u4e00-\u9fff]+$", re.UNICODE)


class TransformationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=120)
    source_sections: list[str] = Field(default_factory=list, max_length=50)


class ClaimOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    source_reference: str = Field(min_length=1, max_length=120)


class PlatformAdaptationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    locale: str
    length_profile: str
    caption: str = Field(min_length=1, max_length=MAX_CAPTION_LENGTH)
    hashtags: list[str] = Field(default_factory=list, max_length=MAX_HASHTAGS)
    cta: str | None = Field(default=None, max_length=500)
    link: str | None = Field(default=None, max_length=2000)
    transformations: list[TransformationOut] = Field(default_factory=list, max_length=50)
    claims: list[ClaimOut] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("platform")
    @classmethod
    def _platform(cls, v: str) -> str:
        key = (v or "").lower().strip()
        if key not in SUPPORTED_PLATFORMS:
            raise ValueError(f"unsupported platform: {v}")
        return key

    @field_validator("locale")
    @classmethod
    def _locale(cls, v: str) -> str:
        key = (v or "").lower().strip()
        if key not in SUPPORTED_LOCALES:
            raise ValueError(f"unsupported locale: {v}")
        return key

    @field_validator("length_profile")
    @classmethod
    def _profile(cls, v: str) -> str:
        key = (v or "").lower().strip()
        if key not in SUPPORTED_LENGTH_PROFILES:
            raise ValueError(f"unsupported length_profile: {v}")
        return key

    @field_validator("hashtags")
    @classmethod
    def _hashtags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for tag in values:
            t = (tag or "").strip()
            if not t:
                continue
            if len(t) > MAX_HASHTAG_LENGTH or not _HASHTAG_RE.match(t):
                raise ValueError(f"malformed hashtag: {t[:40]}")
            if not t.startswith("#"):
                t = f"#{t}"
            cleaned.append(t)
        return cleaned

    @field_validator("link")
    @classmethod
    def _link(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("invalid URL")
        return v


def parse_structured_output(raw: Any) -> PlatformAdaptationOutput:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AIOutputInvalidError(
                "Provider output is not valid JSON",
                details={"reason": "json_decode"},
            ) from exc
    if not isinstance(raw, dict):
        raise AIOutputInvalidError(
            "Provider output must be an object",
            details={"reason": "not_object"},
        )
    try:
        return PlatformAdaptationOutput.model_validate(raw)
    except ValidationError as exc:
        raise AIOutputInvalidError(
            "Provider output failed schema validation",
            details={"reason": "schema", "errors": exc.errors()[:10]},
        ) from exc
