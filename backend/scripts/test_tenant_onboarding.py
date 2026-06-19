"""Validation tests for Factory Tenant Onboarding schemas and step logic."""
from datetime import datetime, timezone

from app.schemas.tenant_onboarding import (
    OnboardingDashboardResponse,
    OnboardingStepItem,
)
from app.services.tenant_onboarding_service import CHECKLIST_STEPS, TOTAL_STEPS, TenantOnboardingService


def test_checklist_has_eight_steps():
    assert TOTAL_STEPS == 8
    ids = [s[0] for s in CHECKLIST_STEPS]
    assert "company_profile" in ids
    assert "growth_center_viewed" in ids


def test_build_steps_empty():
    steps = TenantOnboardingService._build_steps({})
    assert len(steps) == 8
    assert all(not s.completed for s in steps)


def test_build_steps_partial():
    now = datetime.now(timezone.utc).isoformat()
    steps = TenantOnboardingService._build_steps({"company_profile": now, "first_lead": now})
    completed = [s for s in steps if s.completed]
    assert len(completed) == 2


def test_drop_off_step():
    assert TenantOnboardingService._drop_off_step({}) == "company_profile"
    assert TenantOnboardingService._drop_off_step({"company_profile": "2026-01-01"}) == "telegram_connected"


def test_dashboard_response_defaults():
    dash = OnboardingDashboardResponse(
        tenant_id="00000000-0000-0000-0000-000000000001",
        status="not_started",
        progress_percent=0,
        completed_steps=0,
        total_steps=8,
        remaining_steps=8,
        estimated_minutes_remaining=49,
        steps=[],
        demo_data_generated=False,
    )
    assert dash.remaining_steps == 8


def test_step_item_route():
    step = OnboardingStepItem(
        id="first_content",
        label="First content uploaded",
        completed=False,
        route="/onboarding/content",
        estimated_minutes=10,
    )
    assert step.route.startswith("/onboarding")
