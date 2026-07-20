"""Calendar slot CRUD + plan version lifecycle (list/get/publish/clone).

Published plan versions are immutable: their slots cannot be created, edited, or
deleted. Slot mutations only ever change the *plan*, never schedule or publish
anything downstream.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_planner import (
    PLAN_IMMUTABLE_STATUSES,
    SUPPORTED_LOCALES,
    SUPPORTED_PLATFORMS,
    TenantCampaignCalendarSlot,
    TenantCampaignPlanVersion,
    TenantCampaignSlotAssignment,
)
from app.services.automation_domain_events import emit_domain_event
from app.services.campaign_planner import limits
from app.services.campaign_planner.errors import (
    PlanImmutableError,
    PlanVersionNotFoundError,
    SlotNotFoundError,
    ValidationError,
)
from app.services.campaign_planner.plan_fingerprint import compute_slot_fingerprint


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CalendarService:
    # ------------------------------------------------------------ plan loaders
    @staticmethod
    async def load_plan(db: AsyncSession, tenant_id: UUID, campaign_id: UUID, plan_id: UUID) -> TenantCampaignPlanVersion:
        row = (
            await db.execute(
                select(TenantCampaignPlanVersion).where(
                    TenantCampaignPlanVersion.id == plan_id,
                    TenantCampaignPlanVersion.tenant_id == tenant_id,
                    TenantCampaignPlanVersion.campaign_id == campaign_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise PlanVersionNotFoundError("Plan version not found").to_http()
        return row

    @staticmethod
    def _assert_plan_mutable(plan: TenantCampaignPlanVersion) -> None:
        if plan.status in PLAN_IMMUTABLE_STATUSES:
            raise PlanImmutableError(
                "Plan version is immutable and cannot be modified",
                details={"status": plan.status},
            ).to_http()

    @staticmethod
    async def list_plans(db, tenant_id, campaign_id) -> list[TenantCampaignPlanVersion]:
        rows = (
            await db.execute(
                select(TenantCampaignPlanVersion).where(
                    TenantCampaignPlanVersion.tenant_id == tenant_id,
                    TenantCampaignPlanVersion.campaign_id == campaign_id,
                ).order_by(TenantCampaignPlanVersion.version.desc())
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_slots(db, tenant_id, plan_id) -> list[TenantCampaignCalendarSlot]:
        rows = (
            await db.execute(
                select(TenantCampaignCalendarSlot).where(
                    TenantCampaignCalendarSlot.tenant_id == tenant_id,
                    TenantCampaignCalendarSlot.plan_version_id == plan_id,
                ).order_by(
                    TenantCampaignCalendarSlot.scheduled_date.asc(),
                    TenantCampaignCalendarSlot.scheduled_time.asc(),
                    TenantCampaignCalendarSlot.platform.asc(),
                )
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def load_slot(db, tenant_id, plan_id, slot_id) -> TenantCampaignCalendarSlot:
        row = (
            await db.execute(
                select(TenantCampaignCalendarSlot).where(
                    TenantCampaignCalendarSlot.id == slot_id,
                    TenantCampaignCalendarSlot.tenant_id == tenant_id,
                    TenantCampaignCalendarSlot.plan_version_id == plan_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise SlotNotFoundError("Calendar slot not found").to_http()
        return row

    # ---------------------------------------------------------------- slot CRUD
    @classmethod
    async def create_slot(cls, db, tenant_id, campaign_id, plan_id, data, *, created_by=None):
        plan = await cls.load_plan(db, tenant_id, campaign_id, plan_id)
        cls._assert_plan_mutable(plan)
        count = int(
            (
                await db.execute(
                    select(func.count()).select_from(TenantCampaignCalendarSlot).where(
                        TenantCampaignCalendarSlot.plan_version_id == plan_id,
                    )
                )
            ).scalar() or 0
        )
        limits.enforce_child_count(count, limits.MAX_SLOTS_PER_PLAN, "slots_per_plan")

        platform = str(data.get("platform") or "").lower()
        if platform not in SUPPORTED_PLATFORMS:
            raise ValidationError("Unsupported platform", details={"field": "platform"}).to_http()
        locale = str(data.get("locale") or "en").lower()
        if locale not in SUPPORTED_LOCALES:
            raise ValidationError("Unsupported locale", details={"field": "locale"}).to_http()
        scheduled_date = cls._parse_date(data.get("scheduled_date"))
        scheduled_time = cls._parse_time(data.get("scheduled_time"))
        if scheduled_date is None or scheduled_time is None:
            raise ValidationError("scheduled_date and scheduled_time are required", details={"field": "scheduled_date"}).to_http()

        # Reject exact duplicate platform/time within the plan.
        dup = (
            await db.execute(
                select(TenantCampaignCalendarSlot).where(
                    TenantCampaignCalendarSlot.plan_version_id == plan_id,
                    TenantCampaignCalendarSlot.platform == platform,
                    TenantCampaignCalendarSlot.scheduled_date == scheduled_date,
                    TenantCampaignCalendarSlot.scheduled_time == scheduled_time,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise ValidationError(
                "A slot for this platform/date/time already exists",
                details={"field": "scheduled_time"},
            ).to_http()

        slot_dict = {
            "platform": platform, "locale": locale,
            "date": scheduled_date.isoformat(), "time": scheduled_time.strftime("%H:%M"),
            "pillar_key": str(data.get("pillar_id")) if data.get("pillar_id") else None,
            "phase_key": str(data.get("phase_id")) if data.get("phase_id") else None,
            "index": count,
        }
        row = TenantCampaignCalendarSlot(
            id=uuid4(), tenant_id=tenant_id, campaign_id=campaign_id, plan_version_id=plan_id,
            slot_index=count, platform=platform, locale=locale,
            pillar_id=cls._parse_uuid(data.get("pillar_id")),
            phase_id=cls._parse_uuid(data.get("phase_id")),
            scheduled_date=scheduled_date, scheduled_time=scheduled_time,
            suggested_time_label=data.get("suggested_time_label") or "manual",
            status="unassigned", slot_fingerprint=compute_slot_fingerprint(slot_dict),
            notes=data.get("notes"),
        )
        db.add(row)
        plan.slot_count = count + 1
        await db.flush()

        await emit_domain_event(
            db, "campaign.slot_created", tenant_id,
            payload={
                "campaign_id": str(campaign_id), "plan_version_id": str(plan_id),
                "slot_id": str(row.id), "platform": platform, "locale": locale,
            },
            resource_type="campaign", resource_id=str(campaign_id),
        )
        return row

    @classmethod
    async def update_slot(cls, db, tenant_id, campaign_id, plan_id, slot_id, data):
        plan = await cls.load_plan(db, tenant_id, campaign_id, plan_id)
        cls._assert_plan_mutable(plan)
        row = await cls.load_slot(db, tenant_id, plan_id, slot_id)

        if "platform" in data and data["platform"]:
            p = str(data["platform"]).lower()
            if p not in SUPPORTED_PLATFORMS:
                raise ValidationError("Unsupported platform", details={"field": "platform"}).to_http()
            row.platform = p
        if "locale" in data and data["locale"]:
            loc = str(data["locale"]).lower()
            if loc not in SUPPORTED_LOCALES:
                raise ValidationError("Unsupported locale", details={"field": "locale"}).to_http()
            row.locale = loc
        if "scheduled_date" in data and data["scheduled_date"] is not None:
            row.scheduled_date = cls._parse_date(data["scheduled_date"])
        if "scheduled_time" in data and data["scheduled_time"] is not None:
            row.scheduled_time = cls._parse_time(data["scheduled_time"])
        if "pillar_id" in data:
            row.pillar_id = cls._parse_uuid(data["pillar_id"])
        if "phase_id" in data:
            row.phase_id = cls._parse_uuid(data["phase_id"])
        if "notes" in data:
            row.notes = data["notes"]

        # Re-check duplicate platform/time.
        dup = (
            await db.execute(
                select(TenantCampaignCalendarSlot).where(
                    TenantCampaignCalendarSlot.plan_version_id == plan_id,
                    TenantCampaignCalendarSlot.platform == row.platform,
                    TenantCampaignCalendarSlot.scheduled_date == row.scheduled_date,
                    TenantCampaignCalendarSlot.scheduled_time == row.scheduled_time,
                    TenantCampaignCalendarSlot.id != row.id,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise ValidationError(
                "A slot for this platform/date/time already exists",
                details={"field": "scheduled_time"},
            ).to_http()

        row.slot_fingerprint = compute_slot_fingerprint({
            "platform": row.platform, "locale": row.locale,
            "date": row.scheduled_date.isoformat(), "time": row.scheduled_time.strftime("%H:%M"),
            "pillar_key": str(row.pillar_id) if row.pillar_id else None,
            "phase_key": str(row.phase_id) if row.phase_id else None,
            "index": row.slot_index,
        })
        row.updated_at = _utcnow()
        await db.flush()
        return row

    @classmethod
    async def delete_slot(cls, db, tenant_id, campaign_id, plan_id, slot_id):
        plan = await cls.load_plan(db, tenant_id, campaign_id, plan_id)
        cls._assert_plan_mutable(plan)
        row = await cls.load_slot(db, tenant_id, plan_id, slot_id)
        await db.delete(row)
        plan.slot_count = max(0, (plan.slot_count or 1) - 1)
        await db.flush()

    # ------------------------------------------------------------- validation
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
            raise ValidationError("Invalid date", details={"value": str(value)[:20]}).to_http()

    @staticmethod
    def _parse_time(value: Any) -> time | None:
        if value is None or value == "":
            return None
        if isinstance(value, time):
            return value.replace(second=0, microsecond=0)
        s = str(value)
        try:
            parts = s.split(":")
            return time(hour=int(parts[0]), minute=int(parts[1]))
        except (ValueError, IndexError):
            raise ValidationError("Invalid time (expected HH:MM)", details={"value": s[:20]}).to_http()

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
