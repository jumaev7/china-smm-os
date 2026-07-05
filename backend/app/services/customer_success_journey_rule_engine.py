"""Rule engine for Customer Success Journey — checkpoints, features, recommendations, weekly wins."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Literal
from uuid import uuid4

from app.schemas.customer_success import AdoptionDashboard
from app.schemas.customer_success_journey import (
    ExpansionOpportunity,
    JourneyCheckpoint,
    JourneyCriterionResult,
    JourneyFeatureAdoption,
    JourneyRecommendation,
    JourneySuccessScore,
    JourneyTimelineEntry,
    JourneyWeeklyWin,
    NorthStarGoal,
    RenewalReadinessScore,
)

NorthStarGoalType = Literal[
    "export_leads",
    "better_publishing",
    "more_buyers",
    "better_sales_pipeline",
    "brand_awareness",
]

NORTH_STAR_OPTIONS: tuple[tuple[NorthStarGoalType, str, str], ...] = (
    ("export_leads", "More export leads", "Grow inbound inquiries and export opportunities."),
    ("better_publishing", "Better publishing", "Publish consistently across connected channels."),
    ("more_buyers", "More buyers", "Build and nurture your buyer network."),
    ("better_sales_pipeline", "Better sales pipeline", "Move deals through the executive CRM pipeline."),
    ("brand_awareness", "Brand awareness", "Increase visibility with content and social presence."),
)

CHECKPOINT_IDS = ("day_1", "day_3", "day_7", "day_14", "day_30")
CHECKPOINT_DAYS = {"day_1": 1, "day_3": 3, "day_7": 7, "day_14": 14, "day_30": 30}

FEATURE_DEFS: tuple[tuple[str, str, Callable[[dict[str, Any]], bool]], ...] = (
    ("publishing", "Publishing", lambda s: s.get("publishing_accounts", 0) >= 1),
    ("content", "Content creation", lambda s: s.get("content_items", 0) >= 1),
    ("crm_leads", "Lead capture", lambda s: s.get("leads_count", 0) >= 1),
    ("crm_deals", "Deal pipeline", lambda s: s.get("deals_count", 0) >= 1),
    ("buyers", "Buyer profiles", lambda s: s.get("buyers_count", 0) >= 1),
    ("proposals", "Commercial proposals", lambda s: s.get("proposals_count", 0) >= 1),
    ("communication", "Buyer communication", lambda s: s.get("comm_messages", 0) >= 1),
    ("growth_center", "Growth Center", lambda s: s.get("growth_center_viewed", False)),
    ("executive_dashboard", "Executive dashboard", lambda s: s.get("walkthrough_completed", False)),
    ("team_collaboration", "Team collaboration", lambda s: s.get("team_count", 0) >= 2),
    ("export_leads", "Export lead intake", lambda s: s.get("leads_count", 0) >= 3),
    ("meta_connected", "Meta channels", lambda s: s.get("meta_connected", False)),
)


@dataclass
class JourneyRuleContext:
    journey_day: int
    north_star_goal: NorthStarGoalType | None
    signals: dict[str, Any]
    adoption: AdoptionDashboard
    engagement_score: int
    pipeline_value: Decimal
    roi_measurable: bool
    dismissed_ids: set[str] = field(default_factory=set)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _criterion(key: str, label: str, met: bool, current: str, target: str) -> JourneyCriterionResult:
    return JourneyCriterionResult(
        key=key, label=label, met=met, current_value=current, target=target,
    )


def _checkpoint_status(
    day: int,
    journey_day: int,
    completion_pct: int,
    achieved_at: datetime | None,
) -> str:
    if achieved_at or completion_pct >= 100:
        return "achieved"
    if journey_day < day:
        return "locked"
    if journey_day == day:
        return "in_progress" if completion_pct > 0 else "pending"
    if completion_pct >= 100:
        return "achieved"
    return "missed" if journey_day > day + 2 else "pending"


class CustomerSuccessJourneyRuleEngine:
    """Deterministic rule engine — no AI."""

    @staticmethod
    def evaluate_checkpoints(
        ctx: JourneyRuleContext,
        prior_achieved: dict[str, str],
    ) -> list[JourneyCheckpoint]:
        s = ctx.signals
        checkpoints: list[JourneyCheckpoint] = []

        # Day 1 — First value
        d1_criteria = [
            _criterion("login", "Team login", s.get("logins_30d", 0) >= 1,
                       str(s.get("logins_30d", 0)), "≥1"),
            _criterion("orientation", "Platform orientation",
                       s.get("walkthrough_completed", False) or s.get("growth_center_viewed", False),
                       "done" if s.get("walkthrough_completed") or s.get("growth_center_viewed") else "pending",
                       "walkthrough or Growth Center"),
            _criterion("first_output", "First content or lead",
                       s.get("content_items", 0) >= 1 or s.get("leads_count", 0) >= 1,
                       f"{s.get('content_items', 0)} content / {s.get('leads_count', 0)} leads", "≥1"),
        ]
        d1_pct = int(sum(1 for c in d1_criteria if c.met) / len(d1_criteria) * 100)
        d1_at = _parse_ts(prior_achieved.get("day_1"))
        checkpoints.append(JourneyCheckpoint(
            id="day_1", day=1, label="Day 1", theme="First value",
            status=_checkpoint_status(1, ctx.journey_day, d1_pct, d1_at),  # type: ignore[arg-type]
            weight=15, achieved_at=d1_at, criteria=d1_criteria, completion_percent=d1_pct,
        ))

        # Day 3 — Channels live
        d3_criteria = [
            _criterion("publishing", "Publishing connected", s.get("publishing_accounts", 0) >= 1,
                       str(s.get("publishing_accounts", 0)), "≥1 account"),
            _criterion("content", "Content created", s.get("content_items", 0) >= 1,
                       str(s.get("content_items", 0)), "≥1"),
            _criterion("team_logins", "Team engagement", s.get("logins_30d", 0) >= 2,
                       str(s.get("logins_30d", 0)), "≥2 logins"),
        ]
        d3_pct = int(sum(1 for c in d3_criteria if c.met) / len(d3_criteria) * 100)
        d3_at = _parse_ts(prior_achieved.get("day_3"))
        checkpoints.append(JourneyCheckpoint(
            id="day_3", day=3, label="Day 3", theme="Channels live",
            status=_checkpoint_status(3, ctx.journey_day, d3_pct, d3_at),  # type: ignore[arg-type]
            weight=15, achieved_at=d3_at, criteria=d3_criteria, completion_percent=d3_pct,
        ))

        # Day 7 — Pipeline motion
        d7_criteria = [
            _criterion("leads_crm", "Lead + CRM activity",
                       s.get("leads_count", 0) >= 1 and s.get("crm_activities", 0) >= 1,
                       f"{s.get('leads_count', 0)} leads / {s.get('crm_activities', 0)} activities", "≥1 each"),
            _criterion("buyers", "Buyer profile", s.get("buyers_count", 0) >= 1,
                       str(s.get("buyers_count", 0)), "≥1"),
            _criterion("publishing_recent", "Recent publishing",
                       s.get("published_recent", 0) >= 1 or s.get("publish_attempts_7d", 0) >= 1,
                       str(s.get("published_recent", 0)), "≥1 in 7 days"),
        ]
        d7_pct = int(sum(1 for c in d7_criteria if c.met) / len(d7_criteria) * 100)
        d7_at = _parse_ts(prior_achieved.get("day_7"))
        checkpoints.append(JourneyCheckpoint(
            id="day_7", day=7, label="Day 7", theme="Pipeline motion",
            status=_checkpoint_status(7, ctx.journey_day, d7_pct, d7_at),  # type: ignore[arg-type]
            weight=20, achieved_at=d7_at, criteria=d7_criteria, completion_percent=d7_pct,
        ))

        # Day 14 — Revenue habits
        d14_criteria = [
            _criterion("pipeline", "Deal or proposal",
                       s.get("deals_count", 0) >= 1 or s.get("proposals_count", 0) >= 1,
                       f"{s.get('deals_count', 0)} deals / {s.get('proposals_count', 0)} proposals", "≥1"),
            _criterion("communication", "Buyer communication", s.get("comm_messages", 0) >= 5,
                       str(s.get("comm_messages", 0)), "≥5"),
            _criterion("engagement", "Engagement score", ctx.engagement_score >= 45,
                       str(ctx.engagement_score), "≥45"),
        ]
        d14_pct = int(sum(1 for c in d14_criteria if c.met) / len(d14_criteria) * 100)
        d14_at = _parse_ts(prior_achieved.get("day_14"))
        checkpoints.append(JourneyCheckpoint(
            id="day_14", day=14, label="Day 14", theme="Revenue habits",
            status=_checkpoint_status(14, ctx.journey_day, d14_pct, d14_at),  # type: ignore[arg-type]
            weight=25, achieved_at=d14_at, criteria=d14_criteria, completion_percent=d14_pct,
        ))

        # Day 30 — Sustained adoption
        healthy_features = sum(
            1 for m in ctx.adoption.metrics if m.score >= 60
        )
        d30_criteria = [
            _criterion("active_users", "Active team (30d)", s.get("logins_30d", 0) >= 3,
                       str(s.get("logins_30d", 0)), "≥3"),
            _criterion("feature_health", "Healthy feature areas", healthy_features >= 2,
                       str(healthy_features), "≥2"),
            _criterion("business_outcome", "Pipeline or ROI signal",
                       float(ctx.pipeline_value) > 0 or ctx.roi_measurable,
                       f"pipeline={ctx.pipeline_value}", ">0 or measurable ROI"),
        ]
        d30_pct = int(sum(1 for c in d30_criteria if c.met) / len(d30_criteria) * 100)
        d30_at = _parse_ts(prior_achieved.get("day_30"))
        checkpoints.append(JourneyCheckpoint(
            id="day_30", day=30, label="Day 30", theme="Sustained adoption",
            status=_checkpoint_status(30, ctx.journey_day, d30_pct, d30_at),  # type: ignore[arg-type]
            weight=25, achieved_at=d30_at, criteria=d30_criteria, completion_percent=d30_pct,
        ))

        return checkpoints

    @staticmethod
    def evaluate_features(ctx: JourneyRuleContext) -> list[JourneyFeatureAdoption]:
        s = ctx.signals
        features: list[JourneyFeatureAdoption] = []
        for key, label, check in FEATURE_DEFS:
            adopted = check(s)
            metric_score = next(
                (m.score for m in ctx.adoption.metrics
                 if m.key in (key, key.replace("crm_", ""), key.split("_")[0])),
                None,
            )
            score = 85 if adopted else (metric_score if metric_score is not None else 25)
            features.append(JourneyFeatureAdoption(
                key=key,
                label=label,
                adopted=adopted,
                score=min(100, score),
                summary=f"{'Adopted' if adopted else 'Not yet adopted'} — {label}",
            ))
        return features

    @staticmethod
    def build_recommendations(ctx: JourneyRuleContext) -> list[JourneyRecommendation]:
        s = ctx.signals
        goal = ctx.north_star_goal
        recs: list[JourneyRecommendation] = []
        day = ctx.journey_day

        def add(
            rec_id: str,
            title: str,
            detail: str,
            href: str,
            priority: str = "medium",
            checkpoint_day: int | None = None,
            goals: tuple[NorthStarGoalType, ...] | None = None,
        ) -> None:
            if rec_id in ctx.dismissed_ids:
                return
            if goals and goal and goal not in goals:
                return
            if checkpoint_day and day < checkpoint_day:
                return
            recs.append(JourneyRecommendation(
                id=rec_id,
                title=title,
                detail=detail,
                priority=priority,  # type: ignore[arg-type]
                href=href,
                checkpoint_day=checkpoint_day,
                north_star_goal=goal,
            ))

        if day >= 1 and s.get("logins_30d", 0) < 1:
            add("rec_login", "Invite your team to log in",
                "Collaboration starts when teammates access the platform.",
                "/onboarding/team", "high", 1)

        if day >= 3 and s.get("publishing_accounts", 0) < 1:
            add("rec_connect_facebook", "Connect Facebook to unlock cross-posting",
                "Link Meta to publish to Facebook and Instagram.",
                "/onboarding/channels/facebook", "high", 3,
                ("better_publishing", "brand_awareness"))

        if day >= 3 and s.get("content_items", 0) < 1:
            add("rec_first_content", "Create your first export-ready content",
                "Upload media and generate AI captions for your catalog.",
                "/content", "high", 3,
                ("better_publishing", "brand_awareness"))

        if day >= 7 and s.get("leads_count", 0) < 1:
            add("rec_first_lead", "Capture your first export lead",
                "Add a lead from Telegram, CRM, or manual entry.",
                "/crm-pipeline", "high", 7, ("export_leads", "better_sales_pipeline"))

        if day >= 7 and s.get("buyers_count", 0) < 1:
            add("rec_first_buyer", "Add your first buyer profile",
                "Buyer profiles track relationship history and deal context.",
                "/buyers", "medium", 7, ("more_buyers", "export_leads"))

        if day >= 7 and s.get("crm_activities", 0) < 1:
            add("rec_crm_activity", "Log CRM activity on active leads",
                "Activities keep your pipeline visible to the whole team.",
                "/crm-pipeline", "medium", 7, ("better_sales_pipeline",))

        if day >= 14 and s.get("deals_count", 0) < 1:
            add("rec_first_deal", "Create your first deal in the pipeline",
                "Deals track revenue through the 12-stage executive pipeline.",
                "/crm-pipeline", "high", 14, ("better_sales_pipeline",))

        if day >= 14 and s.get("proposals_count", 0) < 1:
            add("rec_first_proposal", "Generate a proposal from an active buyer",
                "Proposals convert interest into signed export orders.",
                "/proposals", "medium", 14, ("better_sales_pipeline", "export_leads"))

        if day >= 14 and ctx.engagement_score < 45:
            add("rec_boost_engagement", "Increase weekly platform activity",
                "Log in, update buyers, and publish content to raise your engagement score.",
                "/customer-success/adoption", "medium", 14)

        if day >= 7 and not s.get("growth_center_viewed", False):
            add("rec_growth_center", "Review Growth Center KPIs",
                "See pipeline health, buyer activity, and export trends in one place.",
                "/growth-center", "low", 7,
                ("export_leads", "better_sales_pipeline", "more_buyers"))

        if day >= 14 and s.get("published_recent", 0) < 1:
            add("rec_publish", "Publish content to a connected channel",
                "Live posts prove your export marketing workflow end-to-end.",
                "/publishing", "medium", 14,
                ("better_publishing", "brand_awareness"))

        if day >= 30 and s.get("leads_count", 0) < 5:
            add("rec_scale_leads", "Scale lead generation channels",
                "Connect more intake channels and run outreach campaigns.",
                "/export-growth", "medium", 30, ("export_leads",))

        priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        recs.sort(key=lambda r: priority_rank.get(r.priority, 4))
        return recs[:8]

    @staticmethod
    def build_weekly_wins(
        ctx: JourneyRuleContext,
        since: datetime,
    ) -> list[JourneyWeeklyWin]:
        s = ctx.signals
        wins: list[JourneyWeeklyWin] = []
        now = _utcnow()

        def win(title: str, detail: str, category: str, href: str | None = None) -> None:
            wins.append(JourneyWeeklyWin(
                id=str(uuid4()),
                title=title,
                detail=detail,
                category=category,
                occurred_at=now,
                href=href,
            ))

        if s.get("leads_period", 0) >= 1:
            win("New leads this week",
                f"{s.get('leads_period', 0)} lead(s) added — pipeline is growing.",
                "pipeline", "/crm-pipeline")
        if s.get("buyers_period", 0) >= 1:
            win("Buyer network expanded",
                f"{s.get('buyers_period', 0)} new buyer profile(s) created.",
                "buyers", "/buyers")
        if s.get("deals_period", 0) >= 1:
            win("Pipeline advanced",
                f"{s.get('deals_period', 0)} new deal(s) entered the pipeline.",
                "pipeline", "/crm-pipeline")
        if s.get("proposals_period", 0) >= 1:
            win("Proposals in motion",
                f"{s.get('proposals_period', 0)} proposal(s) created this week.",
                "proposals", "/proposals")
        if s.get("comm_period", 0) >= 5:
            win("Active buyer communication",
                f"{s.get('comm_period', 0)} messages exchanged with buyers.",
                "communication", "/communications")
        if s.get("published_recent", 0) >= 1:
            win("Content published",
                "Your factory content reached connected channels this week.",
                "publishing", "/publishing")
        if s.get("logins_period", 0) >= 2:
            win("Team engagement",
                f"{s.get('logins_period', 0)} team login(s) this week.",
                "adoption", "/customer-success/adoption")
        if float(ctx.pipeline_value) > 0 and s.get("deals_period", 0) >= 1:
            win("Pipeline value growing",
                f"Open pipeline value: ${float(ctx.pipeline_value):,.0f}.",
                "revenue", "/crm-pipeline")

        return wins

    @staticmethod
    def compute_success_score(
        checkpoints: list[JourneyCheckpoint],
        features: list[JourneyFeatureAdoption],
        signals: dict[str, Any],
    ) -> JourneySuccessScore:
        if checkpoints:
            weighted_cp = sum(
                cp.completion_percent * cp.weight for cp in checkpoints
            ) / sum(cp.weight for cp in checkpoints)
        else:
            weighted_cp = 0

        adopted = sum(1 for f in features if f.adopted)
        feature_breadth = int(adopted / len(features) * 100) if features else 0

        outcome_signals = 0
        if signals.get("leads_count", 0) >= 1:
            outcome_signals += 34
        if signals.get("deals_count", 0) >= 1 or signals.get("proposals_count", 0) >= 1:
            outcome_signals += 33
        if signals.get("published_count", 0) >= 1 or signals.get("content_items", 0) >= 3:
            outcome_signals += 33
        outcome_signals = min(100, outcome_signals)

        score = int(round(weighted_cp * 0.60 + feature_breadth * 0.25 + outcome_signals * 0.15))
        score = max(0, min(100, score))

        if score >= 75:
            label = "Strong momentum"
        elif score >= 50:
            label = "Building traction"
        elif score >= 25:
            label = "Getting started"
        else:
            label = "Early stage"

        return JourneySuccessScore(
            score=score,
            label=label,
            summary=f"Success score {score}/100 — checkpoint {int(weighted_cp)}%, "
                    f"features {feature_breadth}%, outcomes {outcome_signals}%",
            checkpoint_completion_pct=int(weighted_cp),
            feature_breadth_pct=feature_breadth,
            outcome_signals_pct=outcome_signals,
        )

    @staticmethod
    def compute_renewal_readiness(
        health_score: int | None,
        milestone_pct: int,
        days_to_renewal: int | None,
        subscription_status: str | None,
        logins_30d: int,
    ) -> RenewalReadinessScore:
        score = 0
        if health_score is not None:
            score += int(health_score * 0.35)
        score += int(milestone_pct * 0.35)
        if logins_30d >= 1:
            score += 15
        if subscription_status in ("active", "paid"):
            score += 15
        elif subscription_status == "trial" and (days_to_renewal or 99) > 7:
            score += 8
        score = max(0, min(100, score))

        if score >= 70:
            label = "Renewal ready"
        elif score >= 45:
            label = "On track"
        else:
            label = "Needs attention"

        summary_parts = [f"Renewal readiness {score}/100"]
        if days_to_renewal is not None:
            summary_parts.append(f"{days_to_renewal} days to renewal")
        return RenewalReadinessScore(
            score=score,
            label=label,
            days_to_renewal=days_to_renewal,
            subscription_status=subscription_status,
            summary=" — ".join(summary_parts),
        )

    @staticmethod
    def compute_expansion_opportunities(
        ctx: JourneyRuleContext,
        plan_usage_pct: float,
        unused_features: list[str],
    ) -> list[ExpansionOpportunity]:
        opps: list[ExpansionOpportunity] = []
        if plan_usage_pct >= 70:
            opps.append(ExpansionOpportunity(
                id="exp_plan_limit",
                title="Approaching plan limits",
                detail=f"Usage at {plan_usage_pct:.0f}% of plan capacity — consider upgrading.",
                signal_type="plan_usage",
                href="/billing",
                priority="high",
            ))
        if ctx.engagement_score >= 60 and not ctx.signals.get("meta_connected"):
            opps.append(ExpansionOpportunity(
                id="exp_meta",
                title="Unlock Meta publishing",
                detail="Connect Facebook and Instagram to expand reach.",
                signal_type="unused_feature",
                href="/onboarding/channels/facebook",
                priority="medium",
            ))
        if ctx.journey_day >= 14 and ctx.signals.get("proposals_count", 0) == 0:
            opps.append(ExpansionOpportunity(
                id="exp_proposals",
                title="Activate proposal workflow",
                detail="Proposal generation accelerates deal closure.",
                signal_type="unused_feature",
                href="/proposals",
                priority="medium",
            ))
        for feat in unused_features[:2]:
            opps.append(ExpansionOpportunity(
                id=f"exp_unused_{feat}",
                title=f"Try {feat.replace('_', ' ').title()}",
                detail="High-value module not yet adopted — quick win for ROI.",
                signal_type="unused_feature",
                priority="low",
            ))
        return opps[:5]

    @staticmethod
    def build_timeline_entries(
        checkpoints: list[JourneyCheckpoint],
        features: list[JourneyFeatureAdoption],
        weekly_wins: list[JourneyWeeklyWin],
        prior_timeline: list[dict],
    ) -> list[JourneyTimelineEntry]:
        existing_ids = {e.get("id") for e in prior_timeline}
        entries: list[JourneyTimelineEntry] = []

        for cp in checkpoints:
            if cp.status == "achieved" and cp.achieved_at:
                entry_id = f"checkpoint:{cp.id}"
                if entry_id not in existing_ids:
                    entries.append(JourneyTimelineEntry(
                        id=entry_id,
                        entry_type="checkpoint",
                        title=f"{cp.label} — {cp.theme}",
                        detail=f"Checkpoint achieved with {cp.completion_percent}% completion.",
                        occurred_at=cp.achieved_at,
                        checkpoint_id=cp.id,
                    ))

        for feat in features:
            if feat.adopted:
                entry_id = f"feature:{feat.key}"
                if entry_id not in existing_ids:
                    entries.append(JourneyTimelineEntry(
                        id=entry_id,
                        entry_type="feature",
                        title=f"Feature adopted: {feat.label}",
                        detail=feat.summary,
                        occurred_at=_utcnow(),
                        feature_key=feat.key,
                    ))

        for w in weekly_wins:
            entry_id = f"weekly_win:{w.id}"
            if entry_id not in existing_ids:
                entries.append(JourneyTimelineEntry(
                    id=entry_id,
                    entry_type="weekly_win",
                    title=w.title,
                    detail=w.detail,
                    occurred_at=w.occurred_at,
                ))

        merged = [_timeline_from_dict(e) for e in prior_timeline]
        merged.extend(entries)
        merged.sort(key=lambda e: e.occurred_at, reverse=True)
        return merged


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _timeline_from_dict(raw: dict) -> JourneyTimelineEntry:
    occurred = raw.get("occurred_at")
    if isinstance(occurred, str):
        occurred = _parse_ts(occurred) or _utcnow()
    return JourneyTimelineEntry(
        id=raw["id"],
        entry_type=raw.get("entry_type", "outcome"),  # type: ignore[arg-type]
        title=raw["title"],
        detail=raw.get("detail", ""),
        occurred_at=occurred or _utcnow(),
        checkpoint_id=raw.get("checkpoint_id"),
        feature_key=raw.get("feature_key"),
    )
