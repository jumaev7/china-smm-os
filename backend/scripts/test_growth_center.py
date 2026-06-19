"""Manual validation tests for Factory Growth Center schemas."""
from decimal import Decimal

from app.schemas.growth_center import (
    GrowthCenterDashboardResponse,
    GrowthCenterHealthIndicator,
    GrowthCenterHealthScores,
    GrowthCenterMarketInsights,
    GrowthCenterOverviewKpis,
    GrowthCenterRecommendation,
)


def test_overview_kpis_defaults():
    kpis = GrowthCenterOverviewKpis()
    assert kpis.total_leads == 0
    assert kpis.pipeline_value == Decimal("0")


def test_health_status_values():
    healthy = GrowthCenterHealthIndicator(
        score=85,
        status="healthy",
        label="Lead Health",
        summary="10 active of 12 leads",
    )
    assert healthy.status == "healthy"


def test_health_scores_structure():
    indicator = GrowthCenterHealthIndicator(
        score=50,
        status="warning",
        label="Deal Health",
        summary="2 won, 5 in pipeline",
    )
    scores = GrowthCenterHealthScores(
        lead_health=indicator,
        buyer_health=indicator,
        deal_health=indicator,
        communication_health=indicator,
    )
    assert scores.deal_health.score == 50


def test_recommendation_priority():
    rec = GrowthCenterRecommendation(
        id="test-1",
        priority="urgent",
        title="Contact Buyer X",
        expected_impact="High",
        reason="Stale",
        recommended_action="Call today",
    )
    assert rec.priority == "urgent"


def test_dashboard_response_minimal():
    from datetime import datetime, timezone

    kpis = GrowthCenterOverviewKpis(total_leads=5, total_buyers=3)
    indicator = GrowthCenterHealthIndicator(
        score=70,
        status="healthy",
        label="Lead Health",
        summary="ok",
    )
    dashboard = GrowthCenterDashboardResponse(
        kpis=kpis,
        market_insights=GrowthCenterMarketInsights(),
        health_scores=GrowthCenterHealthScores(
            lead_health=indicator,
            buyer_health=indicator,
            deal_health=indicator,
            communication_health=indicator,
        ),
        recommendations=[],
        opportunities=[],
        timeline=[],
        export_formats=[],
        generated_at=datetime.now(timezone.utc),
    )
    assert dashboard.kpis.total_leads == 5


if __name__ == "__main__":
    test_overview_kpis_defaults()
    test_health_status_values()
    test_health_scores_structure()
    test_recommendation_priority()
    test_dashboard_response_minimal()
    print("All growth center tests passed.")
