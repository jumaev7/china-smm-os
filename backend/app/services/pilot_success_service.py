"""Pilot success dashboard — onboarding, usage, ROI, adoption metrics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_ops import PilotFactory, PlatformFeedback
from app.models.tenant import TenantUser
from app.models.tenant_onboarding import TenantOnboardingProgress


class PilotSuccessService:
    @staticmethod
    async def dashboard(db: AsyncSession) -> dict[str, Any]:
        now = datetime.now(timezone.utc)

        pilot_total = (
            await db.execute(select(func.count()).select_from(PilotFactory))
        ).scalar_one()
        pilot_active = (
            await db.execute(
                select(func.count()).select_from(PilotFactory).where(
                    PilotFactory.pilot_status.in_(["active", "feedback_phase"]),
                ),
            )
        ).scalar_one()
        feedback_open = (
            await db.execute(
                select(func.count()).select_from(PlatformFeedback).where(
                    PlatformFeedback.status == "open",
                ),
            )
        ).scalar_one()

        onboarding_rows = (
            await db.execute(select(TenantOnboardingProgress))
        ).scalars().all()
        if onboarding_rows:
            avg_onboarding = sum(r.progress_percent for r in onboarding_rows) / len(onboarding_rows)
            completed_onboarding = sum(1 for r in onboarding_rows if r.status == "completed")
            onboarding_pct = int(avg_onboarding)
        else:
            onboarding_pct = 0
            completed_onboarding = 0

        active_users = (
            await db.execute(
                select(func.count()).select_from(TenantUser).where(TenantUser.status == "active"),
            )
        ).scalar_one()

        pilots_with_score = (
            await db.execute(
                select(PilotFactory).where(PilotFactory.success_score.isnot(None)),
            )
        ).scalars().all()
        if pilots_with_score:
            cs_score = int(
                sum(p.success_score for p in pilots_with_score) / len(pilots_with_score),
            )
        else:
            cs_score = 0

        adoption = min(100, int((completed_onboarding * 30 + active_users * 5 + pilot_active * 15)))

        metrics: list[dict[str, Any]] = [
            {
                "key": "onboarding_completion",
                "label": "Onboarding Completion",
                "value": f"{onboarding_pct}%",
                "status": "ok" if onboarding_pct >= 70 else "warning",
            },
            {
                "key": "active_users",
                "label": "Active Users",
                "value": active_users,
                "status": "ok" if active_users > 0 else "warning",
            },
            {
                "key": "pilot_factories_active",
                "label": "Active Pilots",
                "value": pilot_active,
                "status": "ok" if pilot_active > 0 else "warning",
            },
            {
                "key": "adoption_score",
                "label": "Adoption Score",
                "value": adoption,
                "status": "ok" if adoption >= 50 else "warning",
            },
            {
                "key": "customer_success_score",
                "label": "Customer Success Score",
                "value": cs_score,
                "status": "ok" if cs_score >= 60 else "warning",
            },
            {
                "key": "open_feedback",
                "label": "Open Feedback Items",
                "value": feedback_open,
                "status": "ok" if feedback_open < 10 else "warning",
            },
            {
                "key": "roi_indicator",
                "label": "ROI Indicator",
                "value": f"{min(100, adoption + cs_score) // 2}%",
                "status": "ok",
            },
        ]

        overall = int(
            (onboarding_pct * 0.25 + adoption * 0.25 + cs_score * 0.25 + min(100, pilot_active * 25) * 0.25),
        )

        return {
            "overall_score": min(100, overall),
            "metrics": metrics,
            "pilot_factories_active": int(pilot_active),
            "pilot_factories_total": int(pilot_total),
            "feedback_open_count": int(feedback_open),
            "refreshed_at": now,
        }
