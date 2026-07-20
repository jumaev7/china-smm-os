"""Campaign plan review orchestration.

Combines deterministic coverage, conflict, gap, and readiness analysis into a
persisted review snapshot plus campaign-scoped recommendations. Emits advisory
events for the Marketing Intelligence Platform. Never schedules or publishes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_planner import (
    PLANNER_VERSION,
    TenantCampaignCalendarSlot,
    TenantCampaignGap,
    TenantCampaignPhase,
    TenantCampaignPillar,
    TenantCampaignPlanVersion,
    TenantCampaignRecommendation,
    TenantCampaignReview,
    TenantCampaignSlotAssignment,
    TenantContentPillar,
    TenantMarketingCampaign,
)
from app.services.automation_domain_events import emit_domain_event
from app.services.campaign_planner.conflict_detector import detect_conflicts
from app.services.campaign_planner.coverage_engine import compute_coverage
from app.services.campaign_planner.gap_analysis import analyze_gaps

# Advisory thresholds (deterministic).
COVERAGE_LOW_THRESHOLD = 60
READINESS_LOW_THRESHOLD = 60
UNASSIGNED_HIGH_RATIO = 0.4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CampaignReviewEngine:
    @staticmethod
    async def _gather(db, tenant_id, campaign, plan):
        slots_rows = (
            await db.execute(
                select(TenantCampaignCalendarSlot).where(
                    TenantCampaignCalendarSlot.tenant_id == tenant_id,
                    TenantCampaignCalendarSlot.plan_version_id == plan.id,
                )
            )
        ).scalars().all()
        pillar_key_by_id = {}
        link_rows = (
            await db.execute(
                select(TenantCampaignPillar, TenantContentPillar)
                .join(TenantContentPillar, TenantContentPillar.id == TenantCampaignPillar.pillar_id)
                .where(TenantCampaignPillar.campaign_id == campaign.id)
            )
        ).all()
        pillar_weights: dict[str, int] = {}
        for link, cp in link_rows:
            pillar_key_by_id[str(cp.id)] = cp.slug
            pillar_weights[cp.slug] = int(link.weight or 1)

        slots = [
            {
                "slot_id": s.id,
                "platform": s.platform,
                "locale": s.locale,
                "date": s.scheduled_date.isoformat(),
                "time": s.scheduled_time.strftime("%H:%M"),
                "pillar_key": pillar_key_by_id.get(str(s.pillar_id)) if s.pillar_id else None,
            }
            for s in slots_rows
        ]

        assignment_rows = (
            await db.execute(
                select(TenantCampaignSlotAssignment).where(
                    TenantCampaignSlotAssignment.tenant_id == tenant_id,
                    TenantCampaignSlotAssignment.plan_version_id == plan.id,
                )
            )
        ).scalars().all()
        assignments_by_slot = {
            str(a.slot_id): {
                "content_id": str(a.content_id) if a.content_id else None,
                "assignment_status": a.assignment_status,
                "readiness_status": a.readiness_status,
                "readiness_score": a.readiness_score,
            }
            for a in assignment_rows
        }

        phase_rows = (
            await db.execute(
                select(TenantCampaignPhase).where(TenantCampaignPhase.campaign_id == campaign.id)
            )
        ).scalars().all()
        phases = [
            {
                "name": ph.name,
                "start_date": ph.start_date.isoformat() if ph.start_date else None,
                "end_date": ph.end_date.isoformat() if ph.end_date else None,
            }
            for ph in phase_rows
        ]
        return slots, assignments_by_slot, pillar_weights, phases, assignment_rows

    @classmethod
    async def review_plan(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        campaign: TenantMarketingCampaign,
        plan: TenantCampaignPlanVersion,
        *,
        created_by: UUID | None = None,
    ) -> TenantCampaignReview:
        slots, assignments_by_slot, pillar_weights, phases, assignment_rows = await cls._gather(
            db, tenant_id, campaign, plan,
        )

        cadence_hard = ((plan.parameters or {}).get("cadence") or {}).get("hard_constraints") or {}
        max_per_day = int(cadence_hard.get("max_posts_per_day_per_platform", 2))
        min_spacing = int(cadence_hard.get("min_spacing_minutes", 120))

        coverage = compute_coverage(
            slots=slots,
            assignments_by_slot=assignments_by_slot,
            campaign_platforms=list(campaign.platforms or []),
            campaign_locales=list(campaign.locales or []),
        )
        conflicts = detect_conflicts(
            slots=slots,
            assignments_by_slot=assignments_by_slot,
            max_posts_per_day_per_platform=max_per_day,
            min_spacing_minutes=min_spacing,
        )
        gaps = analyze_gaps(
            slots=slots,
            assignments_by_slot=assignments_by_slot,
            campaign_platforms=list(campaign.platforms or []),
            campaign_locales=list(campaign.locales or []),
            pillar_weights=pillar_weights,
            phases=phases,
        )

        readiness_scores = [a.readiness_score for a in assignment_rows if a.readiness_score is not None]
        readiness_score = int(round(sum(readiness_scores) / len(readiness_scores))) if readiness_scores else None

        review = TenantCampaignReview(
            id=uuid4(),
            tenant_id=tenant_id,
            campaign_id=campaign.id,
            plan_version_id=plan.id,
            review_type="plan",
            coverage_score=coverage.coverage_score,
            readiness_score=readiness_score,
            total_slots=coverage.total_slots,
            assigned_slots=coverage.assigned_slots,
            blocked_slots=coverage.blocked_slots,
            unassigned_slots=coverage.unassigned_slots,
            conflict_count=len(conflicts),
            gap_count=len(gaps),
            summary={
                "coverage": coverage.to_dict(),
                "conflicts": conflicts[:50],
                "gap_types": _count_by(gaps, "gap_type"),
                "note": "Coverage and readiness are advisory; PublishSafety remains authoritative.",
            },
            engine_version=PLANNER_VERSION,
            created_by=created_by,
        )
        db.add(review)
        await db.flush()

        for g in gaps:
            db.add(TenantCampaignGap(
                id=uuid4(),
                tenant_id=tenant_id,
                campaign_id=campaign.id,
                plan_version_id=plan.id,
                review_id=review.id,
                gap_type=g["gap_type"],
                severity=g.get("severity", "medium"),
                dimension=g.get("dimension"),
                dimension_value=(str(g.get("dimension_value")) if g.get("dimension_value") is not None else None),
                detail=g.get("detail"),
                status="open",
            ))
        await db.flush()

        # Campaign-scoped deterministic recommendations.
        recs = cls._build_recommendations(coverage, conflicts, gaps, readiness_score, campaign)
        await cls._upsert_recommendations(db, tenant_id, campaign.id, plan.id, recs)

        pillar_imbalance = any(g["gap_type"] == "pillar_underrepresented" for g in gaps)
        unassigned_ratio = (coverage.unassigned_slots / coverage.total_slots) if coverage.total_slots else 0.0

        await emit_domain_event(
            db, "campaign.plan_reviewed", tenant_id,
            payload={
                "campaign_id": str(campaign.id),
                "plan_version_id": str(plan.id),
                "review_id": str(review.id),
                "coverage_score": coverage.coverage_score,
                "readiness_score": readiness_score,
                "total_slots": coverage.total_slots,
                "assigned_slots": coverage.assigned_slots,
                "blocked_slots": coverage.blocked_slots,
                "unassigned_slots": coverage.unassigned_slots,
                "unassigned_ratio": round(unassigned_ratio, 4),
                "conflict_count": len(conflicts),
                "gap_count": len(gaps),
                "pillar_imbalance": pillar_imbalance,
                "coverage_low": coverage.coverage_score < COVERAGE_LOW_THRESHOLD,
                "readiness_low": readiness_score is not None and readiness_score < READINESS_LOW_THRESHOLD,
                "unassigned_slots_high": unassigned_ratio >= UNASSIGNED_HIGH_RATIO,
                "engine_version": PLANNER_VERSION,
            },
            resource_type="campaign", resource_id=str(campaign.id),
            title="Campaign plan reviewed",
        )

        if gaps:
            high = [g for g in gaps if g.get("severity") in ("high", "critical")]
            await emit_domain_event(
                db, "campaign.gap_detected", tenant_id,
                payload={
                    "campaign_id": str(campaign.id),
                    "plan_version_id": str(plan.id),
                    "review_id": str(review.id),
                    "gap_count": len(gaps),
                    "high_severity_count": len(high),
                    "gap_types": _count_by(gaps, "gap_type"),
                },
                resource_type="campaign", resource_id=str(campaign.id),
            )

        return review

    # ------------------------------------------------------- recommendations
    @staticmethod
    def _build_recommendations(coverage, conflicts, gaps, readiness_score, campaign) -> list[dict[str, Any]]:
        recs: list[dict[str, Any]] = []
        gap_types = {g["gap_type"] for g in gaps}

        if coverage.unassigned_slots > 0:
            recs.append({
                "key": "campaign.assign_unfilled_slots",
                "title": "Assign content to unfilled slots",
                "reason": f"{coverage.unassigned_slots} of {coverage.total_slots} slots have no content assigned.",
                "evidence": {"unassigned_slots": coverage.unassigned_slots, "total_slots": coverage.total_slots},
                "priority": "high" if coverage.unassigned_slots >= max(1, coverage.total_slots // 2) else "medium",
                "rule_id": "rule.campaign_unfilled_slots",
                "action_url": None,
            })
        if "blocked_account" in gap_types:
            recs.append({
                "key": "campaign.resolve_blocked_accounts",
                "title": "Resolve blocked accounts",
                "reason": "One or more slots are blocked by hard readiness (publishing account/permissions).",
                "evidence": {"blocked_slots": coverage.blocked_slots},
                "priority": "high",
                "rule_id": "rule.campaign_blocked_accounts",
                "action_url": "/integrations",
            })
        if "pillar_underrepresented" in gap_types:
            under = [g for g in gaps if g["gap_type"] == "pillar_underrepresented"]
            recs.append({
                "key": "campaign.balance_pillars",
                "title": "Add content for underrepresented pillar",
                "reason": f"{len(under)} content pillar(s) are below their target share of the plan.",
                "evidence": {"pillars": [g.get("dimension_value") for g in under][:10]},
                "priority": "medium",
                "rule_id": "rule.campaign_pillar_imbalance",
                "action_url": None,
            })
        if "locale_missing" in gap_types:
            missing = [g.get("dimension_value") for g in gaps if g["gap_type"] == "locale_missing"]
            recs.append({
                "key": "campaign.complete_locale_coverage",
                "title": "Complete missing locale coverage",
                "reason": f"Locale(s) {', '.join(str(m) for m in missing)} have no slots in this plan.",
                "evidence": {"missing_locales": missing},
                "priority": "medium",
                "rule_id": "rule.campaign_locale_missing",
                "action_url": None,
            })
        if "stale_content" in gap_types:
            recs.append({
                "key": "campaign.review_stale_variants",
                "title": "Review stale content variants",
                "reason": "Some assigned content has readiness warnings and may be stale.",
                "evidence": {"note": "Advisory — re-check content before publishing."},
                "priority": "low",
                "rule_id": "rule.campaign_stale_content",
                "action_url": None,
            })
        same_day = [c for c in conflicts if c.get("conflict_type") in ("same_content_same_day", "max_posts_per_day_exceeded", "duplicate_platform_time")]
        if same_day:
            recs.append({
                "key": "campaign.reduce_same_day_conflicts",
                "title": "Reduce same-day conflicts",
                "reason": f"{len(same_day)} scheduling conflict(s) detected on the calendar.",
                "evidence": {"conflict_count": len(same_day)},
                "priority": "medium",
                "rule_id": "rule.campaign_same_day_conflicts",
                "action_url": None,
            })
        # Brand profile before AI planning.
        if not campaign.brand_profile_version_id:
            recs.append({
                "key": "campaign.publish_brand_profile_for_ai",
                "title": "Publish a Brand Profile before AI campaign planning",
                "reason": "AI campaign planning uses an approved Brand Profile version for tone and claim constraints.",
                "evidence": {"has_brand_profile_version": False},
                "priority": "low",
                "rule_id": "rule.campaign_brand_profile_for_ai",
                "action_url": "/settings/brand-profile",
            })

        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recs.sort(key=lambda r: (priority_order.get(r["priority"], 9), r["key"]))
        return recs

    @staticmethod
    async def _upsert_recommendations(db, tenant_id, campaign_id, plan_id, recs):
        active_keys = {r["key"] for r in recs}
        existing_rows = (
            await db.execute(
                select(TenantCampaignRecommendation).where(
                    TenantCampaignRecommendation.tenant_id == tenant_id,
                    TenantCampaignRecommendation.campaign_id == campaign_id,
                )
            )
        ).scalars().all()
        existing_by_key = {r.recommendation_key: r for r in existing_rows}

        for r in recs:
            row = existing_by_key.get(r["key"])
            if row is None:
                db.add(TenantCampaignRecommendation(
                    id=uuid4(), tenant_id=tenant_id, campaign_id=campaign_id, plan_version_id=plan_id,
                    recommendation_key=r["key"], category="campaign", title=r["title"], reason=r["reason"],
                    evidence=r["evidence"], priority=r["priority"], rule_id=r["rule_id"],
                    rule_version=PLANNER_VERSION, status="open", action_url=r.get("action_url"),
                ))
            else:
                row.plan_version_id = plan_id
                row.title = r["title"]
                row.reason = r["reason"]
                row.evidence = r["evidence"]
                row.priority = r["priority"]
                row.rule_id = r["rule_id"]
                row.action_url = r.get("action_url")
                if row.status == "resolved":
                    row.status = "open"
                row.updated_at = _utcnow()
        # Resolve recommendations no longer active.
        for key, row in existing_by_key.items():
            if key not in active_keys and row.status != "resolved":
                row.status = "resolved"
                row.updated_at = _utcnow()
        await db.flush()

    @staticmethod
    async def list_reviews(db, tenant_id, campaign_id):
        rows = (
            await db.execute(
                select(TenantCampaignReview).where(
                    TenantCampaignReview.tenant_id == tenant_id,
                    TenantCampaignReview.campaign_id == campaign_id,
                ).order_by(TenantCampaignReview.created_at.desc())
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def get_review(db, tenant_id, review_id):
        from app.services.campaign_planner.errors import ReviewNotFoundError

        row = (
            await db.execute(
                select(TenantCampaignReview).where(
                    TenantCampaignReview.id == review_id,
                    TenantCampaignReview.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ReviewNotFoundError("Review not found").to_http()
        return row


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it[key]] = out.get(it[key], 0) + 1
    return out
