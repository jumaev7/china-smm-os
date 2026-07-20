"""Slot assignment — attach content to calendar slots (advisory only).

Assignment NEVER schedules or publishes. It records which content is intended for a
slot plus advisory readiness metadata. Cross-tenant content resolves to 404.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_planner import (
    TenantCampaignCalendarSlot,
    TenantCampaignSlotAssignment,
)
from app.models.client import Client
from app.models.content import ContentItem
from app.services.automation_domain_events import emit_domain_event
from app.services.campaign_planner.calendar_service import CalendarService
from app.services.campaign_planner.errors import (
    AssignmentBlockedError,
    ContentNotFoundError,
    PlanImmutableError,
)
from app.services.campaign_planner.readiness_service import ReadinessService

_ASSIGNABLE_PLAN_STATUSES = frozenset({"draft", "reviewed", "published"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SlotAssignmentService:
    @staticmethod
    async def _load_content(db: AsyncSession, tenant_id: UUID, content_id: UUID) -> ContentItem:
        item = (
            await db.execute(select(ContentItem).where(ContentItem.id == content_id))
        ).scalar_one_or_none()
        if item is None:
            raise ContentNotFoundError("Content not found").to_http()
        owner = (
            await db.execute(select(Client.tenant_id).where(Client.id == item.client_id))
        ).scalar_one_or_none()
        if owner != tenant_id:
            raise ContentNotFoundError("Content not found").to_http()
        return item

    @classmethod
    async def assign(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
        plan_id: UUID,
        slot_id: UUID,
        content_id: UUID,
        *,
        content_variant_id: UUID | None = None,
        platform_override: str | None = None,
        locale_override: str | None = None,
        allow_warnings: bool = True,
        run_publish_safety: bool = True,
        assigned_by: UUID | None = None,
    ) -> TenantCampaignSlotAssignment:
        plan = await CalendarService.load_plan(db, tenant_id, campaign_id, plan_id)
        if plan.status not in _ASSIGNABLE_PLAN_STATUSES:
            raise PlanImmutableError(
                "Plan version does not accept assignments",
                details={"status": plan.status},
            ).to_http()
        slot = await CalendarService.load_slot(db, tenant_id, plan_id, slot_id)
        item = await cls._load_content(db, tenant_id, content_id)

        platform = (platform_override or slot.platform).lower()
        locale = (locale_override or slot.locale).lower()

        readiness = await ReadinessService.evaluate(
            db, tenant_id, item, platform=platform, locale=locale,
            run_publish_safety=run_publish_safety,
        )

        has_issues = bool(readiness.warnings or readiness.blockers)
        if not allow_warnings and has_issues:
            raise AssignmentBlockedError(
                "Assignment blocked by readiness warnings",
                details={
                    "warnings": readiness.warnings,
                    "blockers": readiness.blockers,
                    "readiness_status": readiness.status,
                },
            ).to_http()

        if readiness.blockers:
            assignment_status = "blocked"
            slot_status = "blocked"
        elif readiness.warnings:
            assignment_status = "ready_with_warnings"
            slot_status = "ready_with_warnings"
        else:
            assignment_status = "ready" if readiness.status == "ready" else "assigned"
            slot_status = "ready" if assignment_status == "ready" else "assigned"

        assignment_type = "content"
        if content_variant_id is not None:
            assignment_type = "deterministic_variant"

        # Upsert (slot_id is unique).
        existing = (
            await db.execute(
                select(TenantCampaignSlotAssignment).where(
                    TenantCampaignSlotAssignment.slot_id == slot_id,
                    TenantCampaignSlotAssignment.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()

        warnings_payload = {"warnings": readiness.warnings, "blockers": readiness.blockers}
        if existing is not None:
            existing.content_id = content_id
            existing.content_variant_id = content_variant_id
            existing.assignment_type = assignment_type
            existing.assigned_platform = platform
            existing.assigned_locale = locale
            existing.assignment_status = assignment_status
            existing.readiness_status = readiness.status
            existing.readiness_score = readiness.score
            existing.publishing_review_id = readiness.publishing_review_id
            existing.warnings = warnings_payload
            existing.assigned_by = assigned_by
            existing.assigned_at = _utcnow()
            existing.updated_at = _utcnow()
            assignment = existing
        else:
            assignment = TenantCampaignSlotAssignment(
                id=uuid4(), tenant_id=tenant_id, campaign_id=campaign_id, plan_version_id=plan_id,
                slot_id=slot_id, content_id=content_id, content_variant_id=content_variant_id,
                assignment_type=assignment_type,
                assigned_platform=platform, assigned_locale=locale,
                assignment_status=assignment_status, readiness_status=readiness.status,
                readiness_score=readiness.score, publishing_review_id=readiness.publishing_review_id,
                warnings=warnings_payload, assigned_by=assigned_by, assigned_at=_utcnow(),
            )
            db.add(assignment)

        slot.status = slot_status
        slot.updated_at = _utcnow()
        await db.flush()

        event_type = "campaign.slot_blocked" if assignment_status == "blocked" else "campaign.slot_assigned"
        await emit_domain_event(
            db, event_type, tenant_id,
            payload={
                "campaign_id": str(campaign_id), "plan_version_id": str(plan_id),
                "slot_id": str(slot_id), "platform": platform, "locale": locale,
                "assignment_status": assignment_status, "readiness_status": readiness.status,
                "warning_count": len(readiness.warnings), "blocker_count": len(readiness.blockers),
            },
            resource_type="campaign", resource_id=str(campaign_id),
        )
        return assignment

    @classmethod
    async def unassign(cls, db, tenant_id, campaign_id, plan_id, slot_id) -> None:
        plan = await CalendarService.load_plan(db, tenant_id, campaign_id, plan_id)
        slot = await CalendarService.load_slot(db, tenant_id, plan_id, slot_id)
        existing = (
            await db.execute(
                select(TenantCampaignSlotAssignment).where(
                    TenantCampaignSlotAssignment.slot_id == slot_id,
                    TenantCampaignSlotAssignment.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            await db.delete(existing)
        slot.status = "unassigned"
        slot.updated_at = _utcnow()
        await db.flush()
        await emit_domain_event(
            db, "campaign.slot_unassigned", tenant_id,
            payload={"campaign_id": str(campaign_id), "plan_version_id": str(plan_id), "slot_id": str(slot_id)},
            resource_type="campaign", resource_id=str(campaign_id),
        )

    @classmethod
    async def auto_assign(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
        plan_id: UUID,
        *,
        allow_warnings: bool = True,
        run_publish_safety: bool = False,
        assigned_by: UUID | None = None,
    ) -> dict[str, Any]:
        """Deterministically fill open slots with eligible unused content."""
        plan = await CalendarService.load_plan(db, tenant_id, campaign_id, plan_id)
        if plan.status not in _ASSIGNABLE_PLAN_STATUSES:
            raise PlanImmutableError(
                "Plan version does not accept assignments",
                details={"status": plan.status},
            ).to_http()

        slots = await CalendarService.list_slots(db, tenant_id, plan_id)
        # Existing assignments in the whole campaign to avoid reusing content.
        assigned_content = {
            str(cid) for cid in (
                await db.execute(
                    select(TenantCampaignSlotAssignment.content_id).where(
                        TenantCampaignSlotAssignment.tenant_id == tenant_id,
                        TenantCampaignSlotAssignment.campaign_id == campaign_id,
                        TenantCampaignSlotAssignment.content_id.isnot(None),
                    )
                )
            ).scalars().all() if cid
        }
        assigned_slot_ids = {
            str(sid) for sid in (
                await db.execute(
                    select(TenantCampaignSlotAssignment.slot_id).where(
                        TenantCampaignSlotAssignment.tenant_id == tenant_id,
                        TenantCampaignSlotAssignment.plan_version_id == plan_id,
                    )
                )
            ).scalars().all()
        }

        # Candidate content pool (deterministic ordering).
        candidates = (
            await db.execute(
                select(ContentItem)
                .join(Client, Client.id == ContentItem.client_id)
                .where(Client.tenant_id == tenant_id)
                .order_by(ContentItem.created_at.asc(), ContentItem.id.asc())
            )
        ).scalars().all()

        from app.services.campaign_planner.readiness_service import _LOCALE_CAPTION_FIELDS

        def eligible(item: ContentItem, platform: str, locale: str) -> bool:
            platforms = list(item.platforms or [])
            if platforms and platform not in platforms:
                return False
            fields = _LOCALE_CAPTION_FIELDS.get(locale, ("caption_long_en", "caption_short_en"))
            return any((getattr(item, f, None) or "").strip() for f in fields)

        assigned_count = 0
        skipped = 0
        results: list[dict[str, Any]] = []
        used = set(assigned_content)
        for slot in slots:
            if str(slot.id) in assigned_slot_ids:
                continue
            match = None
            for item in candidates:
                if str(item.id) in used:
                    continue
                if eligible(item, slot.platform, slot.locale):
                    match = item
                    break
            if match is None:
                skipped += 1
                continue
            used.add(str(match.id))
            assignment = await cls.assign(
                db, tenant_id, campaign_id, plan_id, slot.id, match.id,
                allow_warnings=allow_warnings, run_publish_safety=run_publish_safety,
                assigned_by=assigned_by,
            )
            assigned_count += 1
            results.append({
                "slot_id": str(slot.id),
                "content_id": str(match.id),
                "assignment_status": assignment.assignment_status,
                "readiness_status": assignment.readiness_status,
            })

        return {
            "assigned": assigned_count,
            "skipped": skipped,
            "total_open": sum(1 for s in slots if str(s.id) not in assigned_slot_ids),
            "results": results,
        }
