"""Brand Profile management — draft editing + immutable published versions."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governed_ai import TenantBrandProfile, TenantBrandProfileVersion
from app.services.ai_content.errors import AINotFoundError, AIPlatformError, AISafetyBlockedError
from app.services.ai_platform.redaction import redact_text
from app.services.automation_domain_events import emit_domain_event

MAX_NAME = 160
MAX_COMPANY_NAME = 200
MAX_DESCRIPTION = 2000
MAX_AUDIENCE = 1000
MAX_LIST_ITEMS = 40
MAX_LIST_ITEM_LEN = 200
MAX_CLAIM_LEN = 400

_SECRET_FIELD_RE = re.compile(
    r"(?i)\b(api[_-]?key|password|secret|token|private[_-]?key|bearer)\b"
)

SUPPORTED_BRAND_LOCALES = ("en", "ru", "uz", "zh")


class BrandProfileValidationError(AIPlatformError):
    code = "brand_profile_invalid"
    http_status = 422


class BrandProfileConflictError(AIPlatformError):
    code = "brand_profile_conflict"
    http_status = 409


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_draft_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    locale = (payload.get("locale") or "en").lower().strip()
    if locale not in SUPPORTED_BRAND_LOCALES:
        raise BrandProfileValidationError("Unsupported locale", details={"locale": locale})
    out["locale"] = locale

    company_name = (payload.get("company_name") or "").strip()
    if len(company_name) > MAX_COMPANY_NAME:
        raise BrandProfileValidationError("company_name too long")
    out["company_name"] = company_name

    for field, limit in (
        ("company_description", MAX_DESCRIPTION),
        ("audience_description", MAX_AUDIENCE),
    ):
        val = (payload.get(field) or "").strip()
        if len(val) > limit:
            raise BrandProfileValidationError(f"{field} too long")
        # Block secret-like content
        if _SECRET_FIELD_RE.search(val) or redact_text(val).blocked:
            raise AISafetyBlockedError(
                "Brand profile fields must not contain secrets",
                details={"field": field},
            )
        out[field] = val

    for list_field in (
        "tone_traits", "preferred_terms", "forbidden_terms",
        "approved_claims", "prohibited_claims", "source_references",
    ):
        items = payload.get(list_field) or []
        if not isinstance(items, list):
            raise BrandProfileValidationError(f"{list_field} must be a list")
        if len(items) > MAX_LIST_ITEMS:
            raise BrandProfileValidationError(f"{list_field} exceeds list size limit")
        cleaned: list[str] = []
        for item in items:
            s = str(item).strip()
            lim = MAX_CLAIM_LEN if "claim" in list_field else MAX_LIST_ITEM_LEN
            if len(s) > lim:
                raise BrandProfileValidationError(f"{list_field} item too long")
            if _SECRET_FIELD_RE.search(s) or redact_text(s).blocked:
                raise AISafetyBlockedError(
                    "Brand profile fields must not contain secrets",
                    details={"field": list_field},
                )
            if s:
                cleaned.append(s)
        out[list_field] = cleaned

    for obj_field in ("cta_preferences", "emoji_policy", "formatting_preferences", "platform_guidance"):
        val = payload.get(obj_field) or {}
        if val is None:
            val = {}
        if not isinstance(val, dict):
            raise BrandProfileValidationError(f"{obj_field} must be an object")
        # Shallow size guard
        if len(str(val)) > 8000:
            raise BrandProfileValidationError(f"{obj_field} too large")
        out[obj_field] = val

    # Reject secret-named keys in draft
    for key in payload:
        if _SECRET_FIELD_RE.search(str(key)):
            raise AISafetyBlockedError(
                "Brand profile must not include secret fields",
                details={"field": key},
            )
    return out


class BrandProfileService:
    @staticmethod
    async def list_profiles(db: AsyncSession, tenant_id: UUID) -> list[TenantBrandProfile]:
        result = await db.execute(
            select(TenantBrandProfile)
            .where(TenantBrandProfile.tenant_id == tenant_id)
            .order_by(TenantBrandProfile.updated_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_profile(db: AsyncSession, tenant_id: UUID, profile_id: UUID) -> TenantBrandProfile:
        result = await db.execute(
            select(TenantBrandProfile).where(
                TenantBrandProfile.id == profile_id,
                TenantBrandProfile.tenant_id == tenant_id,
            )
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise AINotFoundError("Brand profile not found").to_http()
        return profile

    @classmethod
    async def create_profile(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        name: str,
        draft: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> TenantBrandProfile:
        name_s = (name or "").strip()
        if not name_s or len(name_s) > MAX_NAME:
            raise BrandProfileValidationError("Invalid name").to_http()
        payload = _validate_draft_payload(draft or {"locale": "en"})
        profile = TenantBrandProfile(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name_s,
            status="draft",
            draft_payload=payload,
            draft_version=1,
            created_by=created_by,
        )
        db.add(profile)
        await db.flush()
        return profile

    @classmethod
    async def update_draft(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        profile_id: UUID,
        *,
        draft: dict[str, Any],
        expected_draft_version: int | None = None,
        name: str | None = None,
    ) -> TenantBrandProfile:
        profile = await cls.get_profile(db, tenant_id, profile_id)
        if expected_draft_version is not None and profile.draft_version != expected_draft_version:
            raise BrandProfileConflictError(
                "Draft was modified concurrently",
                details={"expected": expected_draft_version, "current": profile.draft_version},
            ).to_http()
        payload = _validate_draft_payload(draft)
        if name is not None:
            name_s = name.strip()
            if not name_s or len(name_s) > MAX_NAME:
                raise BrandProfileValidationError("Invalid name").to_http()
            profile.name = name_s
        profile.draft_payload = payload
        profile.draft_version = int(profile.draft_version or 0) + 1
        profile.updated_at = _utcnow()
        await db.flush()
        return profile

    @classmethod
    async def publish(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        profile_id: UUID,
        *,
        created_by: UUID | None = None,
    ) -> TenantBrandProfileVersion:
        profile = await cls.get_profile(db, tenant_id, profile_id)
        payload = _validate_draft_payload(profile.draft_payload or {})
        # Next version number
        result = await db.execute(
            select(TenantBrandProfileVersion.version)
            .where(
                TenantBrandProfileVersion.brand_profile_id == profile.id,
                TenantBrandProfileVersion.tenant_id == tenant_id,
            )
            .order_by(TenantBrandProfileVersion.version.desc())
            .limit(1)
        )
        last = result.scalar_one_or_none()
        next_version = int(last or 0) + 1
        version = TenantBrandProfileVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            brand_profile_id=profile.id,
            version=next_version,
            locale=payload["locale"],
            company_name=payload.get("company_name") or "",
            company_description=payload.get("company_description") or "",
            audience_description=payload.get("audience_description") or "",
            tone_traits=payload.get("tone_traits") or [],
            preferred_terms=payload.get("preferred_terms") or [],
            forbidden_terms=payload.get("forbidden_terms") or [],
            approved_claims=payload.get("approved_claims") or [],
            prohibited_claims=payload.get("prohibited_claims") or [],
            cta_preferences=payload.get("cta_preferences") or {},
            emoji_policy=payload.get("emoji_policy") or {},
            formatting_preferences=payload.get("formatting_preferences") or {},
            platform_guidance=payload.get("platform_guidance") or {},
            source_references=payload.get("source_references") or [],
            created_by=created_by,
            published_at=_utcnow(),
        )
        db.add(version)
        await db.flush()
        profile.current_version_id = version.id
        profile.status = "published"
        profile.updated_at = _utcnow()
        await db.flush()
        await emit_domain_event(
            db,
            "brand.profile_published",
            tenant_id,
            payload={
                "brand_profile_id": str(profile.id),
                "brand_profile_version": next_version,
                "brand_profile_version_id": str(version.id),
                "locale": version.locale,
            },
        )
        return version

    @staticmethod
    async def list_versions(
        db: AsyncSession, tenant_id: UUID, profile_id: UUID
    ) -> list[TenantBrandProfileVersion]:
        # 404 if profile wrong tenant
        await BrandProfileService.get_profile(db, tenant_id, profile_id)
        result = await db.execute(
            select(TenantBrandProfileVersion)
            .where(
                TenantBrandProfileVersion.brand_profile_id == profile_id,
                TenantBrandProfileVersion.tenant_id == tenant_id,
            )
            .order_by(TenantBrandProfileVersion.version.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_version(
        db: AsyncSession, tenant_id: UUID, profile_id: UUID, version_id: UUID
    ) -> TenantBrandProfileVersion:
        await BrandProfileService.get_profile(db, tenant_id, profile_id)
        result = await db.execute(
            select(TenantBrandProfileVersion).where(
                TenantBrandProfileVersion.id == version_id,
                TenantBrandProfileVersion.brand_profile_id == profile_id,
                TenantBrandProfileVersion.tenant_id == tenant_id,
            )
        )
        version = result.scalar_one_or_none()
        if version is None:
            raise AINotFoundError("Brand profile version not found").to_http()
        return version

    @staticmethod
    def serialize_profile(profile: TenantBrandProfile) -> dict[str, Any]:
        return {
            "id": profile.id,
            "name": profile.name,
            "status": profile.status,
            "current_version_id": profile.current_version_id,
            "draft_payload": profile.draft_payload or {},
            "draft_version": profile.draft_version,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    @staticmethod
    def serialize_version(version: TenantBrandProfileVersion) -> dict[str, Any]:
        return {
            "id": version.id,
            "brand_profile_id": version.brand_profile_id,
            "version": version.version,
            "locale": version.locale,
            "company_name": version.company_name,
            "company_description": version.company_description,
            "audience_description": version.audience_description,
            "tone_traits": version.tone_traits or [],
            "preferred_terms": version.preferred_terms or [],
            "forbidden_terms": version.forbidden_terms or [],
            "approved_claims": version.approved_claims or [],
            "prohibited_claims": version.prohibited_claims or [],
            "cta_preferences": version.cta_preferences or {},
            "emoji_policy": version.emoji_policy or {},
            "formatting_preferences": version.formatting_preferences or {},
            "platform_guidance": version.platform_guidance or {},
            "source_references": version.source_references or [],
            "published_at": version.published_at,
            "created_at": version.created_at,
        }
