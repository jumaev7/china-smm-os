"""Campaign CRUD + nested resources (goals, kpis, audiences, pillars, phases).

Tenant-scoped. Cross-tenant access always resolves to 404. Terminal campaigns
(completed/archived) reject mutations. Content pillars are tenant-reusable.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_planner import (
    CAMPAIGN_STATUSES,
    CAMPAIGN_TERMINAL_STATUSES,
    GOAL_TYPES,
    PHASE_TYPES,
    PLANNER_VERSION,
    POLICY_VERSION,
    SUPPORTED_LOCALES,
    SUPPORTED_PLATFORMS,
    TenantCampaignAudience,
    TenantCampaignGoal,
    TenantCampaignKpi,
    TenantCampaignPhase,
    TenantCampaignPillar,
    TenantContentPillar,
    TenantMarketingCampaign,
)
from app.services.automation_domain_events import emit_domain_event
from app.services.campaign_planner import limits
from app.services.campaign_planner.errors import (
    CampaignChildNotFoundError,
    CampaignNotFoundError,
    CampaignStateError,
    DuplicateError,
    PillarNotFoundError,
    ValidationError,
)

_MAX_STATUS_TRANSITIONS = {
    "draft": {"draft", "planning", "approved", "archived"},
    "planning": {"planning", "draft", "approved", "active", "archived"},
    "approved": {"approved", "active", "planning", "archived"},
    "active": {"active", "paused", "completed", "archived"},
    "paused": {"paused", "active", "completed", "archived"},
    "completed": {"completed", "archived"},
    "archived": {"archived"},
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "pillar"


class CampaignService:
    # ---------------------------------------------------------------- loaders
    @staticmethod
    async def load_campaign(
        db: AsyncSession, tenant_id: UUID, campaign_id: UUID,
    ) -> TenantMarketingCampaign:
        result = await db.execute(
            select(TenantMarketingCampaign).where(
                TenantMarketingCampaign.id == campaign_id,
                TenantMarketingCampaign.tenant_id == tenant_id,
            )
        )
        campaign = result.scalar_one_or_none()
        if campaign is None:
            raise CampaignNotFoundError("Campaign not found").to_http()
        return campaign

    @staticmethod
    def _assert_mutable(campaign: TenantMarketingCampaign) -> None:
        if campaign.status in CAMPAIGN_TERMINAL_STATUSES:
            raise CampaignStateError(
                "Campaign is archived or completed and cannot be modified",
                details={"status": campaign.status},
            ).to_http()

    # -------------------------------------------------------------- campaigns
    @classmethod
    async def create_campaign(
        cls, db: AsyncSession, tenant_id: UUID, data: dict[str, Any], *, created_by: UUID | None = None,
    ) -> TenantMarketingCampaign:
        platforms = cls._validate_platforms(data.get("platforms") or [])
        locales = cls._validate_locales(data.get("locales") or [])
        primary_locale = (data.get("primary_locale") or (locales[0] if locales else "en")).lower()
        if primary_locale not in SUPPORTED_LOCALES:
            raise ValidationError("Unsupported primary_locale", details={"field": "primary_locale"}).to_http()
        if primary_locale not in locales:
            locales = [primary_locale, *locales]

        start_date = cls._parse_date(data.get("start_date"))
        end_date = cls._parse_date(data.get("end_date"))
        if start_date and end_date and end_date < start_date:
            raise ValidationError("end_date must be on or after start_date", details={"field": "end_date"}).to_http()

        blackout = cls._parse_blackout(data.get("blackout_dates"))

        campaign = TenantMarketingCampaign(
            id=uuid4(),
            tenant_id=tenant_id,
            name=(data.get("name") or "").strip() or "Untitled Campaign",
            description=data.get("description"),
            status="draft",
            objective=data.get("objective"),
            timezone=(data.get("timezone") or "UTC").strip() or "UTC",
            primary_locale=primary_locale,
            locales=locales or [primary_locale],
            platforms=platforms,
            start_date=start_date,
            end_date=end_date,
            blackout_dates=[d.isoformat() for d in blackout],
            cadence=data.get("cadence") or {},
            brand_profile_id=cls._parse_uuid(data.get("brand_profile_id")),
            brand_profile_version_id=cls._parse_uuid(data.get("brand_profile_version_id")),
            planner_version=PLANNER_VERSION,
            policy_version=POLICY_VERSION,
            metadata_json=data.get("metadata") or None,
            created_by=created_by,
        )
        db.add(campaign)
        await db.flush()

        await emit_domain_event(
            db,
            "campaign.created",
            tenant_id,
            payload={
                "campaign_id": str(campaign.id),
                "status": campaign.status,
                "platform_count": len(platforms),
                "locale_count": len(campaign.locales or []),
                "has_date_range": bool(start_date and end_date),
            },
            resource_type="campaign",
            resource_id=str(campaign.id),
            title="Campaign created",
        )
        return campaign

    @classmethod
    async def update_campaign(
        cls, db: AsyncSession, tenant_id: UUID, campaign_id: UUID, data: dict[str, Any],
        *, expected_updated_at: datetime | None = None,
    ) -> TenantMarketingCampaign:
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        cls._check_optimistic(campaign, expected_updated_at)

        if "name" in data and data["name"] is not None:
            campaign.name = str(data["name"]).strip() or campaign.name
        if "description" in data:
            campaign.description = data["description"]
        if "objective" in data:
            campaign.objective = data["objective"]
        if "timezone" in data and data["timezone"]:
            campaign.timezone = str(data["timezone"]).strip()
        if "platforms" in data and data["platforms"] is not None:
            campaign.platforms = cls._validate_platforms(data["platforms"])
        if "locales" in data and data["locales"] is not None:
            campaign.locales = cls._validate_locales(data["locales"]) or campaign.locales
        if "primary_locale" in data and data["primary_locale"]:
            pl = str(data["primary_locale"]).lower()
            if pl not in SUPPORTED_LOCALES:
                raise ValidationError("Unsupported primary_locale", details={"field": "primary_locale"}).to_http()
            campaign.primary_locale = pl
            if pl not in (campaign.locales or []):
                campaign.locales = [pl, *(campaign.locales or [])]
        if "start_date" in data:
            campaign.start_date = cls._parse_date(data["start_date"])
        if "end_date" in data:
            campaign.end_date = cls._parse_date(data["end_date"])
        if campaign.start_date and campaign.end_date and campaign.end_date < campaign.start_date:
            raise ValidationError("end_date must be on or after start_date", details={"field": "end_date"}).to_http()
        if "blackout_dates" in data and data["blackout_dates"] is not None:
            campaign.blackout_dates = [d.isoformat() for d in cls._parse_blackout(data["blackout_dates"])]
        if "cadence" in data and data["cadence"] is not None:
            campaign.cadence = data["cadence"]
        if "brand_profile_id" in data:
            campaign.brand_profile_id = cls._parse_uuid(data["brand_profile_id"])
        if "brand_profile_version_id" in data:
            campaign.brand_profile_version_id = cls._parse_uuid(data["brand_profile_version_id"])
        if "metadata" in data:
            campaign.metadata_json = data["metadata"] or None

        status_changed = False
        if "status" in data and data["status"] is not None:
            new_status = str(data["status"]).lower()
            if new_status not in CAMPAIGN_STATUSES:
                raise ValidationError("Unsupported status", details={"field": "status"}).to_http()
            if new_status != campaign.status:
                allowed = _MAX_STATUS_TRANSITIONS.get(campaign.status, set())
                if new_status not in allowed:
                    raise CampaignStateError(
                        "Illegal status transition",
                        details={"from": campaign.status, "to": new_status},
                    ).to_http()
                campaign.status = new_status
                status_changed = True

        campaign.updated_at = _utcnow()
        await db.flush()

        await emit_domain_event(
            db,
            "campaign.updated",
            tenant_id,
            payload={
                "campaign_id": str(campaign.id),
                "status": campaign.status,
                "status_changed": status_changed,
            },
            resource_type="campaign",
            resource_id=str(campaign.id),
            title="Campaign updated",
        )
        return campaign

    @classmethod
    async def archive_campaign(
        cls, db: AsyncSession, tenant_id: UUID, campaign_id: UUID,
    ) -> TenantMarketingCampaign:
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        if campaign.status == "archived":
            return campaign
        campaign.status = "archived"
        campaign.archived_at = _utcnow()
        campaign.updated_at = _utcnow()
        await db.flush()
        await emit_domain_event(
            db,
            "campaign.archived",
            tenant_id,
            payload={"campaign_id": str(campaign.id)},
            resource_type="campaign",
            resource_id=str(campaign.id),
            title="Campaign archived",
        )
        return campaign

    @classmethod
    async def list_campaigns(
        cls, db: AsyncSession, tenant_id: UUID, *, status: str | None = None, limit: int = 100, offset: int = 0,
    ) -> tuple[list[TenantMarketingCampaign], int]:
        query = select(TenantMarketingCampaign).where(TenantMarketingCampaign.tenant_id == tenant_id)
        count_query = select(func.count()).select_from(TenantMarketingCampaign).where(
            TenantMarketingCampaign.tenant_id == tenant_id,
        )
        if status:
            query = query.where(TenantMarketingCampaign.status == status)
            count_query = count_query.where(TenantMarketingCampaign.status == status)
        query = query.order_by(TenantMarketingCampaign.created_at.desc()).limit(min(limit, 200)).offset(max(0, offset))
        rows = (await db.execute(query)).scalars().all()
        total = int((await db.execute(count_query)).scalar() or 0)
        return list(rows), total

    # -------------------------------------------------------------- children
    @classmethod
    async def _count_children(cls, db: AsyncSession, model, tenant_id: UUID, campaign_id: UUID) -> int:
        return int(
            (
                await db.execute(
                    select(func.count()).select_from(model).where(
                        model.tenant_id == tenant_id,
                        model.campaign_id == campaign_id,
                    )
                )
            ).scalar() or 0
        )

    @classmethod
    async def add_goal(cls, db, tenant_id, campaign_id, data, *, created_by=None):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        existing = await cls._count_children(db, TenantCampaignGoal, tenant_id, campaign_id)
        limits.enforce_child_count(existing, limits.MAX_GOALS_PER_CAMPAIGN, "goals_per_campaign")
        gt = (data.get("goal_type") or "other").lower()
        if gt not in GOAL_TYPES:
            raise ValidationError("Unsupported goal_type", details={"field": "goal_type"}).to_http()
        row = TenantCampaignGoal(
            id=uuid4(), tenant_id=tenant_id, campaign_id=campaign_id,
            goal_type=gt, title=(data.get("title") or "").strip() or "Goal",
            description=data.get("description"), priority=(data.get("priority") or "medium").lower(),
            target_metric=data.get("target_metric"), sort_order=int(data.get("sort_order") or 0),
        )
        db.add(row)
        await db.flush()
        return row

    @classmethod
    async def update_goal(cls, db, tenant_id, campaign_id, goal_id, data):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        row = await cls._load_child(db, TenantCampaignGoal, tenant_id, campaign_id, goal_id)
        if "goal_type" in data and data["goal_type"]:
            gt = str(data["goal_type"]).lower()
            if gt not in GOAL_TYPES:
                raise ValidationError("Unsupported goal_type", details={"field": "goal_type"}).to_http()
            row.goal_type = gt
        for f in ("title", "description", "priority", "target_metric"):
            if f in data and data[f] is not None:
                setattr(row, f, data[f])
        if "sort_order" in data and data["sort_order"] is not None:
            row.sort_order = int(data["sort_order"])
        row.updated_at = _utcnow()
        await db.flush()
        return row

    @classmethod
    async def add_kpi(cls, db, tenant_id, campaign_id, data):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        existing = await cls._count_children(db, TenantCampaignKpi, tenant_id, campaign_id)
        limits.enforce_child_count(existing, limits.MAX_KPIS_PER_CAMPAIGN, "kpis_per_campaign")
        row = TenantCampaignKpi(
            id=uuid4(), tenant_id=tenant_id, campaign_id=campaign_id,
            name=(data.get("name") or "").strip() or "KPI",
            metric_key=(data.get("metric_key") or "").strip() or "metric",
            target_value=data.get("target_value"),
            unit=data.get("unit"),
            comparator=(data.get("comparator") or ">=")[:10],
            timeframe=data.get("timeframe"),
            sort_order=int(data.get("sort_order") or 0),
        )
        db.add(row)
        await db.flush()
        return row

    @classmethod
    async def update_kpi(cls, db, tenant_id, campaign_id, kpi_id, data):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        row = await cls._load_child(db, TenantCampaignKpi, tenant_id, campaign_id, kpi_id)
        for f in ("name", "metric_key", "target_value", "unit", "comparator", "timeframe"):
            if f in data and data[f] is not None:
                setattr(row, f, data[f])
        if "sort_order" in data and data["sort_order"] is not None:
            row.sort_order = int(data["sort_order"])
        row.updated_at = _utcnow()
        await db.flush()
        return row

    @classmethod
    async def add_audience(cls, db, tenant_id, campaign_id, data):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        existing = await cls._count_children(db, TenantCampaignAudience, tenant_id, campaign_id)
        limits.enforce_child_count(existing, limits.MAX_AUDIENCES_PER_CAMPAIGN, "audiences_per_campaign")
        loc = data.get("locale")
        if loc and str(loc).lower() not in SUPPORTED_LOCALES:
            raise ValidationError("Unsupported locale", details={"field": "locale"}).to_http()
        row = TenantCampaignAudience(
            id=uuid4(), tenant_id=tenant_id, campaign_id=campaign_id,
            name=(data.get("name") or "").strip() or "Audience",
            description=data.get("description"),
            locale=str(loc).lower() if loc else None,
            platforms=cls._validate_platforms(data.get("platforms") or []) or None,
            segment=data.get("segment") or None,
            sort_order=int(data.get("sort_order") or 0),
        )
        db.add(row)
        await db.flush()
        return row

    @classmethod
    async def update_audience(cls, db, tenant_id, campaign_id, audience_id, data):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        row = await cls._load_child(db, TenantCampaignAudience, tenant_id, campaign_id, audience_id)
        for f in ("name", "description", "segment"):
            if f in data and data[f] is not None:
                setattr(row, f, data[f])
        if "locale" in data and data["locale"]:
            if str(data["locale"]).lower() not in SUPPORTED_LOCALES:
                raise ValidationError("Unsupported locale", details={"field": "locale"}).to_http()
            row.locale = str(data["locale"]).lower()
        if "platforms" in data and data["platforms"] is not None:
            row.platforms = cls._validate_platforms(data["platforms"]) or None
        if "sort_order" in data and data["sort_order"] is not None:
            row.sort_order = int(data["sort_order"])
        row.updated_at = _utcnow()
        await db.flush()
        return row

    @classmethod
    async def add_phase(cls, db, tenant_id, campaign_id, data):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        existing = await cls._count_children(db, TenantCampaignPhase, tenant_id, campaign_id)
        limits.enforce_child_count(existing, limits.MAX_PHASES_PER_CAMPAIGN, "phases_per_campaign")
        pt = (data.get("phase_type") or "custom").lower()
        if pt not in PHASE_TYPES:
            raise ValidationError("Unsupported phase_type", details={"field": "phase_type"}).to_http()
        start = cls._parse_date(data.get("start_date"))
        end = cls._parse_date(data.get("end_date"))
        if start and end and end < start:
            raise ValidationError("Phase end_date before start_date", details={"field": "end_date"}).to_http()
        row = TenantCampaignPhase(
            id=uuid4(), tenant_id=tenant_id, campaign_id=campaign_id,
            name=(data.get("name") or "").strip() or "Phase",
            phase_type=pt, description=data.get("description"),
            start_date=start, end_date=end,
            weight=int(data.get("weight") or 1), sort_order=int(data.get("sort_order") or 0),
        )
        db.add(row)
        await db.flush()
        return row

    @classmethod
    async def update_phase(cls, db, tenant_id, campaign_id, phase_id, data):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        row = await cls._load_child(db, TenantCampaignPhase, tenant_id, campaign_id, phase_id)
        if "phase_type" in data and data["phase_type"]:
            pt = str(data["phase_type"]).lower()
            if pt not in PHASE_TYPES:
                raise ValidationError("Unsupported phase_type", details={"field": "phase_type"}).to_http()
            row.phase_type = pt
        for f in ("name", "description"):
            if f in data and data[f] is not None:
                setattr(row, f, data[f])
        if "start_date" in data:
            row.start_date = cls._parse_date(data["start_date"])
        if "end_date" in data:
            row.end_date = cls._parse_date(data["end_date"])
        if row.start_date and row.end_date and row.end_date < row.start_date:
            raise ValidationError("Phase end_date before start_date", details={"field": "end_date"}).to_http()
        if "weight" in data and data["weight"] is not None:
            row.weight = int(data["weight"])
        if "sort_order" in data and data["sort_order"] is not None:
            row.sort_order = int(data["sort_order"])
        row.updated_at = _utcnow()
        await db.flush()
        return row

    @classmethod
    async def add_campaign_pillar(cls, db, tenant_id, campaign_id, data):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        pillar_id = cls._parse_uuid(data.get("pillar_id"))
        if pillar_id is None:
            raise ValidationError("pillar_id is required", details={"field": "pillar_id"}).to_http()
        pillar = (
            await db.execute(
                select(TenantContentPillar).where(
                    TenantContentPillar.id == pillar_id,
                    TenantContentPillar.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if pillar is None:
            raise PillarNotFoundError("Content pillar not found").to_http()
        dup = (
            await db.execute(
                select(TenantCampaignPillar).where(
                    TenantCampaignPillar.campaign_id == campaign_id,
                    TenantCampaignPillar.pillar_id == pillar_id,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise DuplicateError("Pillar already linked to campaign").to_http()
        existing = await cls._count_children(db, TenantCampaignPillar, tenant_id, campaign_id)
        limits.enforce_child_count(existing, limits.MAX_PILLARS_PER_CAMPAIGN, "pillars_per_campaign")
        row = TenantCampaignPillar(
            id=uuid4(), tenant_id=tenant_id, campaign_id=campaign_id, pillar_id=pillar_id,
            weight=int(data.get("weight") or pillar.default_weight or 1),
            sort_order=int(data.get("sort_order") or 0),
        )
        db.add(row)
        await db.flush()
        return row

    @classmethod
    async def update_campaign_pillar(cls, db, tenant_id, campaign_id, link_id, data):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        row = await cls._load_child(db, TenantCampaignPillar, tenant_id, campaign_id, link_id)
        if "weight" in data and data["weight"] is not None:
            row.weight = int(data["weight"])
        if "sort_order" in data and data["sort_order"] is not None:
            row.sort_order = int(data["sort_order"])
        row.updated_at = _utcnow()
        await db.flush()
        return row

    @classmethod
    async def delete_child(cls, db, tenant_id, campaign_id, model, child_id):
        campaign = await cls.load_campaign(db, tenant_id, campaign_id)
        cls._assert_mutable(campaign)
        row = await cls._load_child(db, model, tenant_id, campaign_id, child_id)
        await db.delete(row)
        await db.flush()

    @classmethod
    async def list_children(cls, db, tenant_id, campaign_id, model):
        await cls.load_campaign(db, tenant_id, campaign_id)
        rows = (
            await db.execute(
                select(model).where(
                    model.tenant_id == tenant_id,
                    model.campaign_id == campaign_id,
                ).order_by(model.sort_order.asc(), model.created_at.asc())
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def _load_child(db, model, tenant_id, campaign_id, child_id):
        row = (
            await db.execute(
                select(model).where(
                    model.id == child_id,
                    model.tenant_id == tenant_id,
                    model.campaign_id == campaign_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise CampaignChildNotFoundError("Resource not found").to_http()
        return row

    # --------------------------------------------------------- content pillars
    @classmethod
    async def create_pillar(cls, db, tenant_id, data, *, created_by=None):
        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError("Pillar name is required", details={"field": "name"}).to_http()
        slug = _slugify(data.get("slug") or name)
        dup = (
            await db.execute(
                select(TenantContentPillar).where(
                    TenantContentPillar.tenant_id == tenant_id,
                    TenantContentPillar.slug == slug,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise DuplicateError("A pillar with this slug already exists", details={"slug": slug}).to_http()
        row = TenantContentPillar(
            id=uuid4(), tenant_id=tenant_id, name=name, slug=slug,
            description=data.get("description"), color=data.get("color"),
            default_weight=int(data.get("default_weight") or 1),
            is_active=bool(data.get("is_active", True)), created_by=created_by,
        )
        db.add(row)
        await db.flush()
        return row

    @classmethod
    async def list_pillars(cls, db, tenant_id, *, active_only: bool = False):
        query = select(TenantContentPillar).where(TenantContentPillar.tenant_id == tenant_id)
        if active_only:
            query = query.where(TenantContentPillar.is_active.is_(True))
        rows = (await db.execute(query.order_by(TenantContentPillar.name.asc()))).scalars().all()
        return list(rows)

    @classmethod
    async def get_pillar(cls, db, tenant_id, pillar_id):
        row = (
            await db.execute(
                select(TenantContentPillar).where(
                    TenantContentPillar.id == pillar_id,
                    TenantContentPillar.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise PillarNotFoundError("Content pillar not found").to_http()
        return row

    @classmethod
    async def update_pillar(cls, db, tenant_id, pillar_id, data):
        row = await cls.get_pillar(db, tenant_id, pillar_id)
        if "name" in data and data["name"]:
            row.name = str(data["name"]).strip()
        if "description" in data:
            row.description = data["description"]
        if "color" in data:
            row.color = data["color"]
        if "default_weight" in data and data["default_weight"] is not None:
            row.default_weight = int(data["default_weight"])
        if "is_active" in data and data["is_active"] is not None:
            row.is_active = bool(data["is_active"])
        row.updated_at = _utcnow()
        await db.flush()
        return row

    @classmethod
    async def delete_pillar(cls, db, tenant_id, pillar_id):
        row = await cls.get_pillar(db, tenant_id, pillar_id)
        await db.delete(row)
        await db.flush()

    # ----------------------------------------------------------- validation
    @staticmethod
    def _validate_platforms(platforms: list[Any]) -> list[str]:
        out: list[str] = []
        for p in platforms:
            key = str(p).lower().strip()
            if key not in SUPPORTED_PLATFORMS:
                raise ValidationError(f"Unsupported platform: {p}", details={"field": "platforms"}).to_http()
            if key not in out:
                out.append(key)
        if len(out) > limits.MAX_PLATFORMS_PER_CAMPAIGN:
            raise limits.LimitExceededError(  # type: ignore[attr-defined]
                "Too many platforms", details={"limit_key": "platforms_per_campaign", "max": limits.MAX_PLATFORMS_PER_CAMPAIGN},
            ).to_http()
        return out

    @staticmethod
    def _validate_locales(locales: list[Any]) -> list[str]:
        out: list[str] = []
        for loc in locales:
            key = str(loc).lower().strip()
            if key not in SUPPORTED_LOCALES:
                raise ValidationError(f"Unsupported locale: {loc}", details={"field": "locales"}).to_http()
            if key not in out:
                out.append(key)
        if len(out) > limits.MAX_LOCALES_PER_CAMPAIGN:
            raise limits.LimitExceededError(  # type: ignore[attr-defined]
                "Too many locales", details={"limit_key": "locales_per_campaign", "max": limits.MAX_LOCALES_PER_CAMPAIGN},
            ).to_http()
        return out

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            raise ValidationError("Invalid date format (expected YYYY-MM-DD)", details={"value": str(value)[:20]}).to_http()

    @classmethod
    def _parse_blackout(cls, value: Any) -> list[date]:
        if not value:
            return []
        out: list[date] = []
        for raw in value:
            d = cls._parse_date(raw)
            if d and d not in out:
                out.append(d)
        if len(out) > limits.MAX_BLACKOUT_DATES:
            raise limits.LimitExceededError(  # type: ignore[attr-defined]
                "Too many blackout dates", details={"limit_key": "blackout_dates", "max": limits.MAX_BLACKOUT_DATES},
            ).to_http()
        return sorted(out)

    @staticmethod
    def _parse_uuid(value: Any) -> UUID | None:
        if value is None or value == "":
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (ValueError, TypeError):
            raise ValidationError("Invalid UUID", details={"value": str(value)[:40]}).to_http()

    @staticmethod
    def _check_optimistic(campaign: TenantMarketingCampaign, expected_updated_at: datetime | None) -> None:
        if expected_updated_at is None:
            return
        current = campaign.updated_at
        if current is None:
            return
        # Compare to second precision to avoid tz/microsecond drift.
        if abs((current - expected_updated_at).total_seconds()) > 1.0:
            from app.services.campaign_planner.errors import ConcurrencyConflictError

            raise ConcurrencyConflictError(
                "Campaign was modified by another request",
                details={"expected_updated_at": expected_updated_at.isoformat()},
            ).to_http()
