"""Validation tests for Customer Success Journey engine (Phase 1)."""
from datetime import datetime, timezone
from decimal import Decimal

from app.schemas.customer_success import AdoptionDashboard, AdoptionMetric
from app.services.customer_success_journey_rule_engine import (
    CHECKPOINT_DAYS,
    CustomerSuccessJourneyRuleEngine,
    JourneyRuleContext,
    NORTH_STAR_OPTIONS,
)


def _adoption(engagement: int = 50) -> AdoptionDashboard:
    metrics = [
        AdoptionMetric(key="logins", label="User Logins", count=2, score=60),
        AdoptionMetric(key="content", label="Content", count=3, score=55),
        AdoptionMetric(key="crm", label="CRM", count=1, score=40),
        AdoptionMetric(key="buyers", label="Buyers", count=1, score=50),
        AdoptionMetric(key="communication", label="Comms", count=10, score=70),
        AdoptionMetric(key="proposals", label="Proposals", count=0, score=20),
    ]
    return AdoptionDashboard(metrics=metrics, engagement_score=engagement)


def test_north_star_options_count():
    assert len(NORTH_STAR_OPTIONS) == 5


def test_checkpoint_days_mapping():
    assert CHECKPOINT_DAYS["day_1"] == 1
    assert CHECKPOINT_DAYS["day_30"] == 30


def test_success_score_independent_components():
    ctx = JourneyRuleContext(
        journey_day=7,
        north_star_goal="export_leads",
        signals={"leads_count": 2, "deals_count": 0, "proposals_count": 0, "content_items": 2},
        adoption=_adoption(),
        engagement_score=50,
        pipeline_value=Decimal("0"),
        roi_measurable=False,
    )
    checkpoints = CustomerSuccessJourneyRuleEngine.evaluate_checkpoints(ctx, {})
    features = CustomerSuccessJourneyRuleEngine.evaluate_features(ctx)
    score = CustomerSuccessJourneyRuleEngine.compute_success_score(checkpoints, features, ctx.signals)
    assert 0 <= score.score <= 100
    assert score.checkpoint_completion_pct >= 0
    assert score.feature_breadth_pct >= 0
    assert score.outcome_signals_pct >= 0


def test_recommendations_adapt_to_north_star():
    base_signals = {
        "logins_30d": 1,
        "publishing_accounts": 0,
        "content_items": 0,
        "leads_count": 0,
        "buyers_count": 0,
        "deals_count": 0,
        "proposals_count": 0,
        "crm_activities": 0,
        "growth_center_viewed": False,
        "published_recent": 0,
    }
    ctx_leads = JourneyRuleContext(
        journey_day=7,
        north_star_goal="export_leads",
        signals=base_signals,
        adoption=_adoption(),
        engagement_score=50,
        pipeline_value=Decimal("0"),
        roi_measurable=False,
    )
    recs = CustomerSuccessJourneyRuleEngine.build_recommendations(ctx_leads)
    assert any("lead" in r.title.lower() for r in recs)

    ctx_publish = JourneyRuleContext(
        journey_day=3,
        north_star_goal="better_publishing",
        signals=base_signals,
        adoption=_adoption(),
        engagement_score=50,
        pipeline_value=Decimal("0"),
        roi_measurable=False,
    )
    pub_recs = CustomerSuccessJourneyRuleEngine.build_recommendations(ctx_publish)
    assert any("facebook" in r.title.lower() or "content" in r.title.lower() for r in pub_recs)


def test_weekly_wins_positive_only():
    ctx = JourneyRuleContext(
        journey_day=10,
        north_star_goal="more_buyers",
        signals={
            "leads_period": 2,
            "buyers_period": 1,
            "deals_period": 0,
            "proposals_period": 0,
            "comm_period": 0,
            "published_recent": 0,
            "logins_period": 0,
        },
        adoption=_adoption(),
        engagement_score=60,
        pipeline_value=Decimal("5000"),
        roi_measurable=True,
    )
    wins = CustomerSuccessJourneyRuleEngine.build_weekly_wins(
        ctx, datetime.now(timezone.utc),
    )
    assert len(wins) >= 2
    assert all(w.title for w in wins)


def test_timeline_chronological_order():
    ctx = JourneyRuleContext(
        journey_day=1,
        north_star_goal=None,
        signals={
            "logins_30d": 1,
            "walkthrough_completed": True,
            "growth_center_viewed": False,
            "content_items": 1,
            "leads_count": 0,
            "publishing_accounts": 0,
            "team_count": 1,
            "deals_count": 0,
            "buyers_count": 0,
            "proposals_count": 0,
            "comm_messages": 0,
            "meta_connected": False,
            "published_count": 0,
        },
        adoption=_adoption(),
        engagement_score=50,
        pipeline_value=Decimal("0"),
        roi_measurable=False,
    )
    checkpoints = CustomerSuccessJourneyRuleEngine.evaluate_checkpoints(ctx, {})
    features = CustomerSuccessJourneyRuleEngine.evaluate_features(ctx)
    wins = CustomerSuccessJourneyRuleEngine.build_weekly_wins(
        ctx, datetime.now(timezone.utc),
    )
    timeline = CustomerSuccessJourneyRuleEngine.build_timeline_entries(
        checkpoints, features, wins, [],
    )
    if len(timeline) >= 2:
        for i in range(len(timeline) - 1):
            assert timeline[i].occurred_at >= timeline[i + 1].occurred_at


def test_renewal_readiness_score_bounds():
    renewal = CustomerSuccessJourneyRuleEngine.compute_renewal_readiness(
        health_score=70,
        milestone_pct=50,
        days_to_renewal=30,
        subscription_status="active",
        logins_30d=3,
    )
    assert 0 <= renewal.score <= 100
    assert renewal.label
