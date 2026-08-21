"""Operator Workspace metrics — observation layer over canonical state + action audits.

No autonomous remediation. No provider API calls. No new durable attention table.
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_auth_context import get_auth_context
from app.core.client_scope_guard import scope_select
from app.models.content import ContentItem
from app.models.platform_ops import PlatformAuditLog
from app.models.publish_operator_alert import PublishOperatorAlert
from app.schemas.operator_workspace import (
    AttentionCategory,
    OperatorWorkspaceMetricsResponse,
)
from app.services.automation_domain_events import scrub_payload
from app.services.operator_workspace_automation import (
    WORKSPACE_ACTION_CANDIDATE_KEYS,
    list_candidates,
    rank_candidates,
)
from app.services.operator_workspace_service import OperatorWorkspaceService
from app.services.platform_audit_service import PlatformAuditService

logger = logging.getLogger(__name__)

# Durable evidence of Workspace mutation actions (not navigation `open`).
WORKSPACE_ACTION_EVENT = "operator_workspace.action"

MetricsWindow = Literal["24h", "7d", "30d"]

WINDOW_SECONDS: dict[str, int] = {
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
    "30d": 30 * 24 * 3600,
}

AGE_BUCKETS = (
    ("lt_15m", 0, 15 * 60),
    ("m15_60", 15 * 60, 60 * 60),
    ("h1_4", 60 * 60, 4 * 3600),
    ("h4_24", 4 * 3600, 24 * 3600),
    ("d1_3", 24 * 3600, 3 * 24 * 3600),
    ("gt_3d", 3 * 24 * 3600, None),
)

# Documented actionable_since approximations (never fabricate missing stamps).
AGE_SEMANTICS = {
    "content_internal_review": "ContentItem.updated_at or created_at (domain stamp, not first-seen-in-queue)",
    "waiting_for_client": "MIN(ContentItem.updated_at) per client aggregation",
    "publishing_issue": "PublishAttempt.created_at / stuck scheduled_for|updated_at / alert.created_at",
    "scheduling_issue": "ContentItem.scheduled_for (due_at); age from due time",
    "integration_issue": "PublishingAccount.updated_at or created_at",
    "telegram_ingestion_issue": "TelegramWebhookEvent.created_at",
    "automation_failure": "TenantAutomationJob.updated_at or created_at within 7-day actionable window",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def age_bucket(age_seconds: int | None) -> str | None:
    if age_seconds is None or age_seconds < 0:
        return None
    for key, lo, hi in AGE_BUCKETS:
        if hi is None:
            if age_seconds >= lo:
                return key
        elif lo <= age_seconds < hi:
            return key
    return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


class OperatorWorkspaceMetricsService:
    """Read-only metrics for Operator Workspace observability."""

    @classmethod
    async def record_action(
        cls,
        db: AsyncSession,
        *,
        action_id: str,
        outcome: Literal["success", "rejected", "failed", "stale"],
        actor_id: UUID | None,
        tenant_id: UUID | None,
        attention_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        client_id: UUID | None = None,
        category: str | None = None,
        reason_code: str | None = None,
        message: str | None = None,
        commit: bool = True,
    ) -> None:
        """Minimal durable instrumentation via existing PlatformAuditLog.

        Never logs secrets. Never raises into the action path.
        Navigation `open` must not be recorded.
        """
        if action_id == "open":
            return
        try:
            ctx = get_auth_context()
            actor_type = "admin" if ctx and ctx.is_admin else "tenant_user"
            details = scrub_payload({
                "action_id": action_id,
                "attention_id": attention_id,
                "outcome": outcome,
                "client_id": str(client_id) if client_id else None,
                "category": category,
                "reason_code": reason_code,
                "message": (message or "")[:500] or None,
            })
            await PlatformAuditService.record(
                db,
                actor_type=actor_type,
                actor_id=actor_id,
                tenant_id=tenant_id,
                event_type=WORKSPACE_ACTION_EVENT,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else None,
                details=details,
                commit=commit,
            )
        except Exception:
            logger.exception(
                "Failed to record operator workspace action audit action_id=%s outcome=%s",
                action_id,
                outcome,
            )

    @classmethod
    async def get_metrics(
        cls,
        db: AsyncSession,
        *,
        window: MetricsWindow = "7d",
        client_id: UUID | None = None,
        category: AttentionCategory | None = None,
    ) -> OperatorWorkspaceMetricsResponse:
        if window not in WINDOW_SECONDS:
            raise HTTPException(status_code=400, detail="Invalid metrics window")

        now = _utc_now()
        since = now - timedelta(seconds=WINDOW_SECONDS[window])

        # Point-in-time attention (same collectors as daily queue).
        items = await OperatorWorkspaceService._collect_items(db, client_id=client_id)
        if category:
            items = [i for i in items if i.attention_type == category]

        attention = cls._build_attention_metrics(items, now=now)

        # Windowed action frequency from PlatformAuditLog.
        action_rows = await cls._load_action_audits(db, since=since, client_id=client_id)
        actions = cls._build_action_metrics(action_rows)

        # Alert resolution from canonical PublishOperatorAlert fields.
        resolution = await cls._build_resolution_metrics(
            db, since=since, client_id=client_id, now=now,
        )

        # Advisory candidates — never enable auto.
        stats_for_rank: dict[str, dict] = {}
        by_action = actions.get("by_action") or {}
        for action_id, counts in by_action.items():
            total = int(counts.get("total") or 0)
            success = int(counts.get("success") or 0)
            stats_for_rank[action_id] = {
                "total": total,
                "success_rate": (success / total) if total else None,
            }
            mapped = WORKSPACE_ACTION_CANDIDATE_KEYS.get(action_id)
            if mapped:
                stats_for_rank[mapped] = stats_for_rank[action_id]

        candidates = rank_candidates(stats_for_rank)

        top_issue = None
        if attention["by_category"]:
            top_issue = max(attention["by_category"].items(), key=lambda kv: kv[1])[0]

        oldest_age = attention.get("oldest_age_seconds")

        return OperatorWorkspaceMetricsResponse(
            window=window,
            generated_at=now,
            attention=attention,
            actions=actions,
            resolution=resolution,
            automation_candidates=candidates,
            top_recurring_issue=top_issue,
            oldest_unresolved_age_seconds=oldest_age,
            age_semantics=AGE_SEMANTICS,
            notes={
                "attention": (
                    "Point-in-time open attention from canonical projection; "
                    "not a historical timeseries."
                ),
                "actions": (
                    f"Counts Workspace mutation audits ({WORKSPACE_ACTION_EVENT}) "
                    "within the selected window. Navigation `open` is excluded. "
                    "History starts when instrumentation was deployed."
                ),
                "resolution": (
                    "Alert TTR uses PublishOperatorAlert.first_occurred_at → "
                    "resolved_at for alerts resolved in-window. "
                    "Non-alert attention clearance is not durably timed."
                ),
                "automation": (
                    "Candidate levels and scores are advisory only; "
                    "auto-execution is disabled."
                ),
            },
            candidate_catalog=[
                {
                    "action_key": c.action_key,
                    "level": c.level,
                    "rationale": c.rationale,
                    "prerequisites": list(c.prerequisites),
                }
                for c in list_candidates()
            ],
        )

    @classmethod
    def _build_attention_metrics(
        cls,
        items: list,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        by_category: Counter[str] = Counter()
        by_priority: Counter[str] = Counter()
        by_responsibility: Counter[str] = Counter()
        by_client: Counter[str] = Counter()
        age_buckets: Counter[str] = Counter({k: 0 for k, _, _ in AGE_BUCKETS})
        ages: list[int] = []
        missing_ts = 0

        for item in items:
            by_category[item.attention_type] += 1
            by_priority[item.priority] += 1
            by_responsibility[item.responsible_party] += 1
            if item.client_id is not None:
                by_client[str(item.client_id)] += 1

            # Prefer due_at for scheduling overdue age; else created_at proxy.
            stamp = _aware(item.due_at) if item.attention_type == "scheduling_issue" and item.due_at else _aware(item.created_at)
            if stamp is None:
                missing_ts += 1
                continue
            age_sec = int((now - stamp).total_seconds())
            if age_sec < 0:
                age_sec = 0
            ages.append(age_sec)
            bucket = age_bucket(age_sec)
            if bucket:
                age_buckets[bucket] += 1

        return {
            "total": len(items),
            "by_category": dict(by_category),
            "by_priority": dict(by_priority),
            "by_responsibility": dict(by_responsibility),
            "by_client_count": len(by_client),
            "age_buckets": dict(age_buckets),
            "median_age_seconds": _median([float(a) for a in ages]),
            "oldest_age_seconds": max(ages) if ages else None,
            "missing_timestamp_count": missing_ts,
        }

    @classmethod
    async def _load_action_audits(
        cls,
        db: AsyncSession,
        *,
        since: datetime,
        client_id: UUID | None,
    ) -> list[PlatformAuditLog]:
        ctx = get_auth_context()
        query = select(PlatformAuditLog).where(
            PlatformAuditLog.event_type == WORKSPACE_ACTION_EVENT,
            PlatformAuditLog.created_at >= since,
        )
        if ctx and ctx.is_tenant:
            if ctx.tenant_id is None:
                return []
            query = query.where(PlatformAuditLog.tenant_id == ctx.tenant_id)
        # Admin: all tenants unless we later add tenant_id filter param.

        rows = list((await db.scalars(query.order_by(PlatformAuditLog.created_at.desc()))).all())

        if client_id is None:
            return rows

        # Filter by scrubbed details.client_id when present; drop rows without client scope
        # when a client filter is active (avoid leaking cross-client aggregates).
        filtered: list[PlatformAuditLog] = []
        target = str(client_id)
        for row in rows:
            details = row.details or {}
            row_client = details.get("client_id")
            if row_client == target:
                filtered.append(row)
        return filtered

    @classmethod
    def _build_action_metrics(cls, rows: list[PlatformAuditLog]) -> dict[str, Any]:
        by_action: dict[str, dict[str, int]] = {}
        success = rejected = failed = stale = 0
        total = 0

        for row in rows:
            details = row.details or {}
            action_id = details.get("action_id")
            if not action_id or action_id == "open":
                continue
            outcome = details.get("outcome") or "success"
            total += 1
            bucket = by_action.setdefault(
                action_id,
                {"total": 0, "success": 0, "rejected": 0, "failed": 0, "stale": 0},
            )
            bucket["total"] += 1
            if outcome in bucket:
                bucket[outcome] += 1
            else:
                bucket["failed"] += 1

            if outcome == "success":
                success += 1
            elif outcome == "rejected":
                rejected += 1
            elif outcome == "stale":
                stale += 1
            else:
                failed += 1

        return {
            "total": total,
            "by_action": by_action,
            "success": success,
            "rejected": rejected,
            "failed": failed,
            "stale": stale,
            "available": True,
        }

    @classmethod
    async def _build_resolution_metrics(
        cls,
        db: AsyncSession,
        *,
        since: datetime,
        client_id: UUID | None,
        now: datetime,
    ) -> dict[str, Any]:
        """Alert-centric resolution metrics from canonical PublishOperatorAlert."""
        query = (
            select(PublishOperatorAlert, ContentItem)
            .join(ContentItem, ContentItem.id == PublishOperatorAlert.content_id)
            .where(
                PublishOperatorAlert.resolved_at.is_not(None),
                PublishOperatorAlert.resolved_at >= since,
            )
        )
        query, _ = scope_select(query, None, ContentItem.client_id, client_id=client_id)
        rows = (await db.execute(query)).all()

        resolution_seconds: list[float] = []
        ack_seconds: list[float] = []
        resolved = 0
        acknowledged_in_window = 0
        system_resolved = 0

        for alert, _content in rows:
            resolved += 1
            if alert.resolved_by_system:
                system_resolved += 1
            start = _aware(alert.first_occurred_at) or _aware(alert.created_at)
            end = _aware(alert.resolved_at)
            if start and end and end >= start:
                resolution_seconds.append((end - start).total_seconds())

        # Acks in window (may still be open).
        ack_q = (
            select(PublishOperatorAlert, ContentItem)
            .join(ContentItem, ContentItem.id == PublishOperatorAlert.content_id)
            .where(
                PublishOperatorAlert.acknowledged_at.is_not(None),
                PublishOperatorAlert.acknowledged_at >= since,
            )
        )
        ack_q, _ = scope_select(ack_q, None, ContentItem.client_id, client_id=client_id)
        ack_rows = (await db.execute(ack_q)).all()
        for alert, _content in ack_rows:
            acknowledged_in_window += 1
            start = _aware(alert.first_occurred_at) or _aware(alert.created_at)
            ack_at = _aware(alert.acknowledged_at)
            if start and ack_at and ack_at >= start:
                ack_seconds.append((ack_at - start).total_seconds())

        return {
            "resolved": resolved,
            "system_resolved": system_resolved,
            "manual_resolved": max(0, resolved - system_resolved),
            "acknowledged": acknowledged_in_window,
            "median_resolution_seconds": _median(resolution_seconds),
            "median_ack_seconds": _median(ack_seconds),
            "available": True,
            "scope": "publish_operator_alerts",
            "non_alert_resolution_available": False,
        }
