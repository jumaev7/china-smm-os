"""Scheduling and publish-state readiness checks (reuse existing validation concepts)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.publishing_intelligence.checks._helpers import check
from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext

_PUBLISHABLE = frozenset({"approved", "scheduled", "failed", "partial_failed", "ready", "ready_for_approval"})


def run_scheduling_checks(
    ctx: ReviewContext,
    *,
    account_status_by_platform: dict[str, str] | None = None,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    account_status_by_platform = account_status_by_platform or {}
    now = datetime.now(timezone.utc)

    # scheduled_time_present — advisory unless status is scheduled
    if ctx.status == "scheduled" and ctx.scheduled_for is None:
        results.append(
            check(
                "scheduled_time_present",
                "scheduling_readiness",
                "failed",
                score=0,
                weight=3,
                severity="error",
                evidence={"status": ctx.status},
                recommendation_key="set_scheduled_time",
            )
        )
    elif ctx.scheduled_for is None:
        results.append(
            check(
                "scheduled_time_present",
                "scheduling_readiness",
                "not_applicable",
                evidence={"reason": "not_scheduled"},
            )
        )
    else:
        results.append(
            check(
                "scheduled_time_present",
                "scheduling_readiness",
                "passed",
                score=100,
                weight=2,
                evidence={"scheduled_for": ctx.scheduled_for.isoformat()},
            )
        )

    if ctx.scheduled_for is None:
        results.append(
            check("scheduled_time_in_future", "scheduling_readiness", "not_applicable", evidence={"reason": "no_schedule"})
        )
    else:
        when = ctx.scheduled_for
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        future = when > now
        results.append(
            check(
                "scheduled_time_in_future",
                "scheduling_readiness",
                "passed" if future else "failed",
                score=100 if future else 0,
                weight=3,
                severity="error" if not future else "info",
                evidence={"scheduled_for": when.isoformat(), "now": now.isoformat()},
                recommendation_key="reschedule_publish_time" if not future else None,
            )
        )

    if not ctx.platforms:
        results.append(
            check(
                "publishing_accounts_selected",
                "scheduling_readiness",
                "failed",
                score=0,
                weight=3,
                severity="error",
                evidence={"platforms": []},
                recommendation_key="select_platforms",
            )
        )
        results.append(
            check("platform_account_available", "scheduling_readiness", "not_applicable", evidence={"reason": "no_platforms"})
        )
        results.append(
            check("integration_connected", "scheduling_readiness", "not_applicable", evidence={"reason": "no_platforms"})
        )
    else:
        results.append(
            check(
                "publishing_accounts_selected",
                "scheduling_readiness",
                "passed",
                score=100,
                weight=2,
                evidence={"platforms": sorted(ctx.platforms)},
            )
        )
        missing = [p for p in ctx.platforms if p not in account_status_by_platform]
        bad = [
            p for p, st in account_status_by_platform.items()
            if p in ctx.platforms and st not in {"connected", "mock"}
        ]
        available_ok = not missing and not bad
        results.append(
            check(
                "platform_account_available",
                "scheduling_readiness",
                "passed" if available_ok else "warning",
                score=100 if available_ok else 45,
                weight=3,
                severity="warning" if not available_ok else "info",
                evidence={"missing": missing, "unavailable": bad, "statuses": account_status_by_platform},
                recommendation_key="reconnect_publishing_account" if not available_ok else None,
            )
        )
        disconnected = [
            p for p, st in account_status_by_platform.items()
            if p in ctx.platforms and st in {"disconnected", "expired", "invalid", "blocked"}
        ]
        results.append(
            check(
                "integration_connected",
                "scheduling_readiness",
                "failed" if disconnected else "passed",
                score=0 if disconnected else 100,
                weight=3,
                severity="error" if disconnected else "info",
                evidence={"disconnected": disconnected},
                recommendation_key="reconnect_publishing_account" if disconnected else None,
                recommendation_params={"platforms": disconnected} if disconnected else None,
            )
        )

    status_ok = ctx.status in _PUBLISHABLE or ctx.status in {"draft", "needs_review", "needs_caption", "new"}
    # Draft is allowed for quality review; publish itself still needs hard safety
    publish_status_ok = ctx.status in _PUBLISHABLE
    results.append(
        check(
            "content_status_allows_publish",
            "scheduling_readiness",
            "passed" if publish_status_ok else "warning",
            score=100 if publish_status_ok else 55,
            weight=2,
            evidence={"status": ctx.status, "publishable_statuses": sorted(_PUBLISHABLE)},
            recommendation_key="advance_content_status" if not publish_status_ok else None,
        )
    )

    approved = ctx.approved_at is not None
    client_blocked = ctx.client_review_status == "changes_requested"
    if client_blocked:
        results.append(
            check(
                "approval_status_allows_publish",
                "scheduling_readiness",
                "failed",
                score=0,
                weight=3,
                severity="error",
                evidence={"approved": approved, "client_review_status": ctx.client_review_status},
                recommendation_key="resolve_client_changes",
            )
        )
    elif not approved:
        results.append(
            check(
                "approval_status_allows_publish",
                "scheduling_readiness",
                "warning",
                score=50,
                weight=2,
                severity="warning",
                evidence={"approved": False, "client_review_status": ctx.client_review_status},
                recommendation_key="approve_content_before_publish",
            )
        )
    else:
        results.append(
            check(
                "approval_status_allows_publish",
                "scheduling_readiness",
                "passed",
                score=100,
                weight=2,
                evidence={"approved": True, "client_review_status": ctx.client_review_status},
            )
        )

    # Silence unused for lint if draft path referenced
    _ = status_ok
    return results
