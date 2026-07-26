"""Read-only observation collectors for Business Health v2.

Uses direct selects / existing read services. Avoids methods that seed demo
data, mutate connection status, or call provider SDKs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.endpoint_guard import safe_section
from app.models.client import Client
from app.models.content import ContentItem
from app.models.crm_lead import CrmLead
from app.models.operator_task import OperatorTask
from app.models.publish_attempt import PublishAttempt
from app.models.publishing_account import PublishingAccount
from app.services.operator_task_service import TERMINAL_STATUSES

logger = logging.getLogger(__name__)
MARKER = "[BusinessHealthV2]"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _client_ids_for_tenant(db: AsyncSession, tenant_id: UUID) -> list[UUID]:
    rows = (
        await db.execute(select(Client.id).where(Client.tenant_id == tenant_id))
    ).scalars().all()
    return list(rows)


async def resolve_tenant_id(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
    client_id: UUID | None,
) -> UUID | None:
    if tenant_id:
        return tenant_id
    if not client_id:
        return None
    return await db.scalar(select(Client.tenant_id).where(Client.id == client_id))


async def collect_sales_observations(
    db: AsyncSession,
    *,
    client_id: UUID | None = None,
    preloaded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sales observations from CRM/operator tables or a preloaded executive snapshot."""
    if preloaded is not None:
        return dict(preloaded)

    now = _utc_now()

    def _filter(q, column):
        if client_id:
            return q.where(column == client_id)
        return q

    hot_q = select(func.count()).select_from(CrmLead).where(
        CrmLead.status.notin_(("won", "lost")),
        or_(
            CrmLead.priority == "hot",
            CrmLead.qualification_level.in_(("hot", "qualified_hot")),
            CrmLead.lead_score >= 70,
        ),
    )
    hot_q = _filter(hot_q, CrmLead.client_id)

    leads_q = select(func.count()).select_from(CrmLead).where(
        CrmLead.status.notin_(("won", "lost")),
    )
    leads_q = _filter(leads_q, CrmLead.client_id)

    overdue_q = select(func.count()).select_from(OperatorTask).where(
        OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
        OperatorTask.due_at.isnot(None),
        OperatorTask.due_at < now,
    )
    overdue_q = _filter(overdue_q, OperatorTask.client_id)

    unassigned_q = select(func.count()).select_from(OperatorTask).where(
        OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
        or_(OperatorTask.assigned_to.is_(None), OperatorTask.assigned_to == ""),
    )
    unassigned_q = _filter(unassigned_q, OperatorTask.client_id)

    return {
        "hot_leads": int(await db.scalar(hot_q) or 0),
        "leads_count": int(await db.scalar(leads_q) or 0),
        "overdue_tasks": int(await db.scalar(overdue_q) or 0),
        "unassigned_tasks": int(await db.scalar(unassigned_q) or 0),
        "risk_count": 0,
        "neglected_leads": 0,
        "inactive_leads": 0,
        "unanswered": 0,
        "hot_no_followup": 0,
    }


def sales_obs_from_executive_snapshot(snap: Any) -> dict[str, Any]:
    """Map ExecutiveCopilot snapshot fields into sales observation dict."""
    ov = getattr(snap, "sales_overview", None) or {}
    inbox = ov.get("inbox_activity") or {}
    workload = ov.get("operator_workload") or {}
    lead_metrics = getattr(snap, "lead_metrics", None) or {}
    opportunities = getattr(snap, "opportunities", None) or []
    hot_no_followup = sum(
        1 for o in opportunities if o.get("type") in ("hot_lead_no_followup", "hot_lead_follow_up")
    )
    return {
        "overdue_tasks": int(ov.get("overdue_tasks") or workload.get("overdue_tasks") or 0),
        "risk_count": len(getattr(snap, "risks", None) or []),
        "neglected_leads": int(lead_metrics.get("neglected_leads") or ov.get("neglected_leads") or 0),
        "inactive_leads": int(lead_metrics.get("inactive_leads") or 0),
        "unanswered": int(inbox.get("unanswered") or 0),
        "unassigned_tasks": int(workload.get("unassigned_tasks") or 0),
        "hot_leads": int(ov.get("hot_leads") or lead_metrics.get("hot_leads") or 0),
        "hot_no_followup": hot_no_followup,
        "leads_count": int(ov.get("leads_count") or 0),
    }


async def collect_publishing_observations(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
    client_id: UUID | None,
) -> dict[str, Any]:
    content_filter = []
    if client_id:
        content_filter.append(ContentItem.client_id == client_id)
    elif tenant_id:
        client_ids = await _client_ids_for_tenant(db, tenant_id)
        if not client_ids:
            return {"not_configured": True, "attempts_total": 0}
        content_filter.append(ContentItem.client_id.in_(client_ids))

    status_q = select(ContentItem.status, func.count()).select_from(ContentItem)
    if content_filter:
        status_q = status_q.where(*content_filter)
    status_q = status_q.group_by(ContentItem.status)
    status_rows = (await db.execute(status_q)).all()
    status_counts = {row[0]: int(row[1]) for row in status_rows}

    attempt_q = (
        select(PublishAttempt.status, func.count())
        .select_from(PublishAttempt)
        .join(ContentItem, ContentItem.id == PublishAttempt.content_id)
    )
    if content_filter:
        attempt_q = attempt_q.where(*content_filter)
    attempt_q = attempt_q.group_by(PublishAttempt.status)
    attempt_rows = (await db.execute(attempt_q)).all()
    attempt_counts = {row[0]: int(row[1]) for row in attempt_rows}
    success = attempt_counts.get("success", 0)
    failed_attempts = attempt_counts.get("failed", 0)
    total = success + failed_attempts
    rate = round((success / total) * 100, 1) if total else 0.0

    failed_posts = (
        status_counts.get("failed", 0)
        + status_counts.get("partial_failed", 0)
        + failed_attempts
    )
    has_any = bool(status_counts) or total > 0
    if not has_any and tenant_id is None and client_id is None:
        # Platform-wide empty still evaluable as idle publishing.
        pass

    return {
        "attempts_total": total,
        "attempts_success": success,
        "failed_posts": failed_posts,
        "success_rate": rate,
        "scheduled_posts": status_counts.get("scheduled", 0),
        "published_posts": status_counts.get("published", 0),
        "freshness": "fresh",
    }


async def collect_campaign_planning_observations(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
) -> dict[str, Any]:
    if not tenant_id:
        return {"not_configured": True, "reason": "tenant_scope_required"}

    from app.models.campaign_planner import TenantCampaignCalendarSlot, TenantMarketingCampaign

    campaigns = list(
        (
            await db.execute(
                select(TenantMarketingCampaign).where(TenantMarketingCampaign.tenant_id == tenant_id)
            )
        ).scalars().all()
    )
    if not campaigns:
        return {"not_configured": True, "campaign_count": 0}

    active = sum(1 for c in campaigns if getattr(c, "status", None) in {"active", "running", "published"})
    slot_rows = (
        await db.execute(
            select(TenantCampaignCalendarSlot.status, func.count())
            .where(TenantCampaignCalendarSlot.tenant_id == tenant_id)
            .group_by(TenantCampaignCalendarSlot.status)
        )
    ).all()
    by_status = {row[0]: int(row[1]) for row in slot_rows}
    total_slots = sum(by_status.values())
    return {
        "campaign_count": len(campaigns),
        "active_campaign_count": active,
        "total_slots": total_slots,
        "unassigned_slots": by_status.get("unassigned", 0),
        "blocked_slots": by_status.get("blocked", 0),
        "has_slots": total_slots > 0,
    }


async def collect_organic_measurement_observations(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
) -> dict[str, Any]:
    if not tenant_id:
        return {"not_configured": True, "reason": "tenant_scope_required"}

    from app.services.measurement.read_service import measurement_overview

    overview = await measurement_overview(db, tenant_id)
    return {
        "publication_count": int(overview.get("publication_count") or 0),
        "fresh_count": int(overview.get("fresh_count") or 0),
        "aging_count": int(overview.get("aging_count") or 0),
        "stale_count": int(overview.get("stale_count") or 0),
        "open_anomaly_count": int(overview.get("open_anomaly_count") or 0),
    }


async def collect_advertising_observations(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
) -> dict[str, Any]:
    if not tenant_id:
        return {"not_configured": True, "reason": "tenant_scope_required"}

    from app.services.advertising_intelligence import read_service

    overview = await read_service.advertising_overview(db, tenant_id)
    freshness = overview.get("freshness") or {}
    attr = overview.get("attribution_coverage") or {}
    connected = int(overview.get("connected_account_count") or 0)
    accounts = int(overview.get("account_count") or 0)
    return {
        "account_count": accounts,
        "campaign_count": int(overview.get("campaign_count") or 0),
        "stale_campaigns": int(freshness.get("stale") or 0),
        "pacing_warning_count": len(overview.get("pacing_warnings") or []),
        "open_anomaly_count": int(overview.get("open_anomaly_count") or 0),
        "fatigue_warning_count": int(overview.get("fatigue_warning_count") or 0),
        "disconnected_accounts": max(0, accounts - connected),
        "attribution_coverage_ratio": attr.get("coverage_ratio"),
        "read_only": True,
    }


async def collect_integration_observations(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
) -> dict[str, Any]:
    if not tenant_id:
        return {"not_configured": True, "reason": "tenant_scope_required"}

    rows = list(
        (
            await db.execute(
                select(PublishingAccount.status, func.count())
                .where(PublishingAccount.tenant_id == tenant_id)
                .group_by(PublishingAccount.status)
            )
        ).all()
    )
    by_status = {row[0]: int(row[1]) for row in rows}
    total = sum(by_status.values())
    if total == 0:
        return {"not_configured": True, "account_count": 0}

    disconnected = by_status.get("disconnected", 0) + by_status.get("blocked", 0)
    expired = (
        by_status.get("expired", 0)
        + by_status.get("invalid", 0)
        + by_status.get("missing_permissions", 0)
    )
    connected = by_status.get("connected", 0) + by_status.get("mock", 0)
    return {
        "account_count": total,
        "connected": connected,
        "disconnected": disconnected,
        "expired": expired,
    }


async def collect_automation_observations(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
) -> dict[str, Any]:
    """Direct SQL — avoids AutomationService KPI helpers that seed system flows."""
    if not tenant_id:
        return {"not_configured": True, "reason": "tenant_scope_required"}

    from app.models.automation import TenantAutomationExecution, TenantAutomationFlow

    flows = list(
        (
            await db.execute(
                select(TenantAutomationFlow).where(TenantAutomationFlow.tenant_id == tenant_id)
            )
        ).scalars().all()
    )
    if not flows:
        return {"not_configured": True, "flow_count": 0}

    enabled = sum(1 for f in flows if getattr(f, "status", None) == "enabled")
    failed_flows = sum(
        1
        for f in flows
        if getattr(f, "status", None) == "enabled"
        and getattr(f, "last_execution_status", None) == "failed"
    )
    since = _utc_now() - timedelta(hours=24)
    exec_failures = int(
        await db.scalar(
            select(func.count())
            .select_from(TenantAutomationExecution)
            .where(
                TenantAutomationExecution.tenant_id == tenant_id,
                TenantAutomationExecution.status == "failed",
                TenantAutomationExecution.created_at >= since,
            )
        )
        or 0
    )
    return {
        "flow_count": len(flows),
        "enabled_count": enabled,
        "failed_flow_count": failed_flows,
        "execution_failures_24h": exec_failures,
    }


async def collect_customer_success_observations(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
) -> dict[str, Any]:
    if not tenant_id:
        return {"not_configured": True, "reason": "tenant_scope_required"}

    from app.services.customer_success_service import CustomerSuccessService

    summary = await CustomerSuccessService.summary(db, tenant_id)
    # summary may be a pydantic model
    data = summary.model_dump() if hasattr(summary, "model_dump") else dict(summary)
    if data.get("is_demo"):
        return {"not_configured": True, "is_demo": True}
    health = data.get("customer_health_score")
    score = None
    if isinstance(health, dict):
        score = health.get("score")
    elif health is not None and hasattr(health, "score"):
        score = health.score
    elif isinstance(health, (int, float)):
        score = health
    if score is None:
        return {"not_configured": True}
    return {
        "health_score": int(score),
        "churn_risk": data.get("churn_risk"),
        "adoption_score": data.get("adoption_score"),
        "confidence": 0.7,
    }


async def collect_revenue_billing_observations(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
) -> dict[str, Any]:
    if not tenant_id:
        return {"not_configured": True, "reason": "tenant_scope_required"}

    from app.services.business_health.policy import BILLING_NEAR_LIMIT_RATIO
    from app.services.subscription_service import SubscriptionService

    summary = await SubscriptionService.summary(db, tenant_id)
    status = summary.get("status")
    usage = (summary.get("usage_summary") or {})
    near = 0
    for key in ("users", "leads", "buyers", "deals"):
        metric = usage.get(key) or {}
        used = float(metric.get("current") or metric.get("used") or metric.get("count") or 0)
        util = metric.get("utilization_pct")
        if util is not None:
            try:
                if float(util) >= BILLING_NEAR_LIMIT_RATIO * 100:
                    near += 1
                continue
            except (TypeError, ValueError):
                pass
        limit = metric.get("limit")
        if limit is None:
            continue
        try:
            limit_f = float(limit)
        except (TypeError, ValueError):
            continue
        if limit_f > 0 and (used / limit_f) >= BILLING_NEAR_LIMIT_RATIO:
            near += 1

    if not status and near == 0:
        # Free/default plan with no active subscription row — still evaluable via usage.
        return {
            "subscription_status": "free" if summary.get("plan") else None,
            "monthly_price": summary.get("monthly_price"),
            "near_limit_count": near,
            "has_usage": True,
            "mrr": summary.get("monthly_price") or 0,
        }

    return {
        "subscription_status": status or "free",
        "monthly_price": summary.get("monthly_price"),
        "near_limit_count": near,
        "has_usage": True,
        "mrr": summary.get("monthly_price") or 0,
    }


async def collect_all_observations(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
    client_id: UUID | None,
    sales_preloaded: dict[str, Any] | None = None,
    errors: list[str] | None = None,
) -> dict[str, dict[str, Any] | None]:
    """Collect domain observations with per-domain isolation."""
    err = errors if errors is not None else []

    async def _safe(name: str, coro, default: dict[str, Any]) -> dict[str, Any]:
        return await safe_section(name, coro, default=default, errors=err, db=db, timeout=8.0)

    sales = await _safe(
        "bh.sales",
        collect_sales_observations(db, client_id=client_id, preloaded=sales_preloaded),
        {"error": True},
    )
    publishing = await _safe(
        "bh.publishing",
        collect_publishing_observations(db, tenant_id=tenant_id, client_id=client_id),
        {"error": True},
    )
    campaign = await _safe(
        "bh.campaign_planning",
        collect_campaign_planning_observations(db, tenant_id=tenant_id),
        {"error": True},
    )
    measurement = await _safe(
        "bh.organic_measurement",
        collect_organic_measurement_observations(db, tenant_id=tenant_id),
        {"error": True},
    )
    advertising = await _safe(
        "bh.advertising",
        collect_advertising_observations(db, tenant_id=tenant_id),
        {"error": True},
    )
    integration = await _safe(
        "bh.integration",
        collect_integration_observations(db, tenant_id=tenant_id),
        {"error": True},
    )
    automation = await _safe(
        "bh.automation",
        collect_automation_observations(db, tenant_id=tenant_id),
        {"error": True},
    )
    cs = await _safe(
        "bh.customer_success",
        collect_customer_success_observations(db, tenant_id=tenant_id),
        {"error": True},
    )
    billing = await _safe(
        "bh.revenue_billing",
        collect_revenue_billing_observations(db, tenant_id=tenant_id),
        {"error": True},
    )

    return {
        "sales": sales,
        "publishing": publishing,
        "campaign_planning": campaign,
        "organic_measurement": measurement,
        "advertising": advertising,
        "integration": integration,
        "automation": automation,
        "customer_success": cs,
        "revenue_billing": billing,
    }
