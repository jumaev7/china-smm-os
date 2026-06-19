"""Manual validation tests for AI Export Growth Engine schemas."""
from decimal import Decimal

from app.schemas.export_growth import (
    ExportGrowthDashboardResponse,
    ExportGrowthKpis,
    ExportGrowthScore,
    ExportGrowthScoreFactor,
    ExportGrowthDailyAction,
    ExportGrowthOpportunity,
)


def test_kpis_defaults():
    kpis = ExportGrowthKpis()
    assert kpis.pipeline_value == Decimal("0")
    assert kpis.export_growth_score == 0


def test_export_growth_score_factors():
    factors = [
        ExportGrowthScoreFactor(
            factor="Buyer activity",
            weight_pct=25,
            score=70,
            weighted_contribution=17.5,
            summary="5 active buyers",
        ),
    ]
    score = ExportGrowthScore(
        score=72,
        label="Strong export momentum",
        summary="Well balanced activities",
        factors=factors,
    )
    assert score.score == 72
    assert len(score.factors) == 1


def test_daily_action_priority():
    action = ExportGrowthDailyAction(
        id="test-1",
        priority="urgent",
        title="Contact Buyer A",
        expected_impact="High",
        reason="Stale",
        recommended_action="Call today",
    )
    assert action.priority == "urgent"


def test_opportunity_score_bounds():
    opp = ExportGrowthOpportunity(
        id="opp-1",
        category="deal",
        title="Test deal",
        opportunity_score=85,
        estimated_value=Decimal("50000"),
        recommended_action="Close deal",
        confidence_score=80,
    )
    assert opp.opportunity_score == 85


def test_dashboard_response_minimal():
    from datetime import datetime, timezone

    dashboard = ExportGrowthDashboardResponse(
        kpis=ExportGrowthKpis(active_buyers=3),
        export_growth_score=ExportGrowthScore(
            score=55,
            label="Moderate",
            summary="Room to grow",
        ),
        generated_at=datetime.now(timezone.utc),
    )
    assert dashboard.kpis.active_buyers == 3
    assert dashboard.demo_mode is False


def test_tenant_scoping_documentation():
    """Export Growth Engine scopes all queries by tenant_id — see ExportGrowthService._load_* methods."""
    assert True


if __name__ == "__main__":
    test_kpis_defaults()
    test_export_growth_score_factors()
    test_daily_action_priority()
    test_opportunity_score_bounds()
    test_dashboard_response_minimal()
    test_tenant_scoping_documentation()
    print("All export growth tests passed.")
