"""Validation tests for Factory Tenant Onboarding schemas and step logic."""
from datetime import datetime, timezone

from app.schemas.tenant_onboarding import (
    OnboardingDashboardResponse,
    OnboardingStepItem,
    OnboardingStepReadiness,
)
from app.services.onboarding_readiness_service import BUSINESS_STEP_DEFS, PLATFORM_STEP_DEFS
from app.services.tenant_onboarding_service import CHECKLIST_STEPS, TOTAL_STEPS, TenantOnboardingService


def test_checklist_has_platform_and_business_steps():
    assert len(PLATFORM_STEP_DEFS) == 12
    assert len(BUSINESS_STEP_DEFS) == 4
    assert TOTAL_STEPS == 16
    ids = [s[0] for s in CHECKLIST_STEPS]
    assert "company_info" in ids
    assert "executive_walkthrough" in ids
    assert "first_proposal" in ids


def test_build_steps_empty():
    steps = TenantOnboardingService._build_steps({})
    assert len(steps) == TOTAL_STEPS
    assert all(not s.completed for s in steps)


def test_build_steps_partial():
    now = datetime.now(timezone.utc).isoformat()
    steps = TenantOnboardingService._build_steps({"company_info": now, "first_lead": now})
    completed = [s for s in steps if s.completed]
    assert len(completed) == 2


def test_drop_off_step():
    assert TenantOnboardingService._drop_off_step({}) == "company_info"
    assert TenantOnboardingService._drop_off_step({"company_info": "2026-01-01"}) == "industry_selection"


def test_dashboard_response_defaults():
    dash = OnboardingDashboardResponse(
        tenant_id="00000000-0000-0000-0000-000000000001",
        status="not_started",
        progress_percent=0,
        completed_steps=0,
        total_steps=16,
        remaining_steps=16,
        estimated_minutes_remaining=49,
        steps=[],
        demo_data_generated=False,
    )
    assert dash.remaining_steps == 16


def test_step_item_route():
    step = OnboardingStepItem(
        id="first_ai_content",
        label="Generate first AI content",
        completed=False,
        route="/onboarding/content",
        estimated_minutes=10,
    )
    assert step.route.startswith("/onboarding")


def test_step_readiness_schema():
    step = OnboardingStepReadiness(
        id="telegram_connected",
        label="Connect Telegram",
        category="platform",
        status="missing",
        route="/onboarding/channels",
        estimated_minutes=5,
        why_it_matters="Required for intake.",
        next_action="Link your group.",
        business_value="Automated content intake.",
    )
    assert step.status == "missing"
