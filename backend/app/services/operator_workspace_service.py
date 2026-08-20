"""Operator Workspace — attention projection over canonical state (+ Phase 1 actions)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_auth_context import apply_tenant_direct_scope, get_auth_context
from app.core.client_scope_guard import scope_select
from app.models.automation import TenantAutomationJob
from app.models.client import Client
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.models.publish_operator_alert import PublishOperatorAlert
from app.models.publishing_account import PublishingAccount
from app.models.telegram_ingestion import TelegramWebhookEvent
from app.schemas.operator_workspace import (
    AttentionCategory,
    AttentionPriority,
    OperatorAttentionItem,
    OperatorWorkspaceItemsResponse,
    OperatorWorkspaceSummary,
    OperatorWorkspaceSummaryResponse,
    ResponsibleParty,
)
from app.services.automation_domain_events import INTEGRATION_ATTENTION_STATUSES
from app.services.content_review_service import (
    CLIENT_REVIEW_CHANGES,
    CLIENT_REVIEW_PENDING,
    client_review_required,
)
from app.services.publish_resilience import (
    OPS_LIST_STATUSES,
    PublishResilienceService,
    STATUS_EXHAUSTED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    sanitize_error_message,
)
from app.services.scheduled_publish_diagnostics_service import ScheduledPublishDiagnosticsService

logger = logging.getLogger(__name__)

INTERNAL_REVIEW_STATUSES = frozenset({
    "new",
    "needs_review",
    "needs_caption",
    "ready",
    "ready_for_approval",
})

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Recent operational windows — not historical archives.
# Dead letters older than this are excluded so July noise does not pollute "today".
AUTOMATION_ACTIONABLE_DAYS = 7
TELEGRAM_ACTIONABLE_DAYS = 7
OVERDUE_GRACE_MINUTES = 15

# Pathological safety only. Status filters already bound actionable sets for
# 200–300 clients; if this ceiling is hit we log loudly (never silent truncate).
PATHOLOGICAL_ROW_WARN = 5000

_PROVIDER_FAILURE_CODES = frozenset({
    "auth_or_permission",
    "rate_limited",
    "provider_unavailable",
    "provider_transient",
})

_REASON_CODES = {
    "internal_review": "internal_review",
    "client_pending": "client_pending",
    "client_changes": "client_changes",
    "publish_operator_review": "publish_operator_review",
    "publish_failed": "publish_failed",
    "publish_exhausted": "publish_exhausted",
    "publish_stuck": "publish_stuck",
    "publish_retrying": "publish_retrying",
    "schedule_overdue": "schedule_overdue",
    "integration_attention": "integration_attention",
    "telegram_failed": "telegram_failed",
    "automation_failed": "automation_failed",
    "automation_dead_letter": "automation_dead_letter",
    "publish_alert": "publish_alert",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _content_title(item: ContentItem) -> str:
    for field in ("caption_short_en", "caption_short_ru", "caption_short_uz", "internal_notes"):
        val = getattr(item, field, None)
        if val and str(val).strip():
            text = str(val).strip()
            return text[:80] + ("…" if len(text) > 80 else "")
    return "Untitled content"


def _priority_for_publish_status(status: str) -> AttentionPriority:
    if status == STATUS_OPERATOR_REVIEW:
        return "critical"
    if status in (STATUS_FAILED, STATUS_EXHAUSTED):
        return "high"
    if status == STATUS_IN_PROGRESS:
        return "critical"
    if status == STATUS_RETRYING:
        return "medium"
    return "high"


def _responsible_for_publish(
    status: str,
    *,
    failure_code: str | None = None,
) -> ResponsibleParty:
    if status == STATUS_RETRYING:
        return "system"
    if status == STATUS_IN_PROGRESS:
        return "system"
    if failure_code in _PROVIDER_FAILURE_CODES:
        return "provider"
    if status in (STATUS_OPERATOR_REVIEW, STATUS_FAILED, STATUS_EXHAUSTED):
        return "operator"
    return "operator"


def _sort_key(item: OperatorAttentionItem) -> tuple:
    due = item.due_at or datetime.max.replace(tzinfo=timezone.utc)
    created = item.created_at or datetime.min.replace(tzinfo=timezone.utc)
    return (
        PRIORITY_ORDER.get(item.priority, 9),
        0 if item.overdue else 1,
        due,
        -created.timestamp() if created else 0,
    )


def _warn_if_pathological(source: str, count: int) -> None:
    if count >= PATHOLOGICAL_ROW_WARN:
        logger.warning(
            "[OperatorWorkspace] pathological row volume source=%s count=%s "
            "(actionable status filters should keep this rare for 200–300 clients)",
            source,
            count,
        )


class OperatorWorkspaceService:
    @staticmethod
    def _tenant_filter(tenant_id_column):
        return apply_tenant_direct_scope(tenant_id_column=tenant_id_column)

    @classmethod
    async def get_summary(
        cls,
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> OperatorWorkspaceSummaryResponse:
        items = await cls._collect_items(db, client_id=client_id)
        return OperatorWorkspaceSummaryResponse(summary=cls._build_summary(items))

    @classmethod
    async def list_items(
        cls,
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        category: AttentionCategory | None = None,
        priority: AttentionPriority | None = None,
        responsible_party: ResponsibleParty | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> OperatorWorkspaceItemsResponse:
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        all_items = await cls._collect_items(db, client_id=client_id)
        # Summary always reflects the full client-scoped attention set so filter
        # chips cannot silently change unrelated card totals.
        summary = cls._build_summary(all_items)

        items = all_items
        if category:
            items = [i for i in items if i.attention_type == category]
        if priority:
            items = [i for i in items if i.priority == priority]
        if responsible_party:
            items = [i for i in items if i.responsible_party == responsible_party]

        items.sort(key=_sort_key)
        total = len(items)
        start = (page - 1) * page_size
        page_items = items[start : start + page_size]

        # Actions are derived (not persisted) from current projection state.
        from app.services.operator_workspace_actions import OperatorWorkspaceActionService

        OperatorWorkspaceActionService.attach_actions(page_items)

        return OperatorWorkspaceItemsResponse(
            items=page_items,
            total=total,
            page=page,
            page_size=page_size,
            summary=summary,
        )

    @classmethod
    def _build_summary(cls, items: list[OperatorAttentionItem]) -> OperatorWorkspaceSummary:
        needs_action = sum(
            1 for i in items
            if i.responsible_party == "operator" and i.attention_type != "waiting_for_client"
        )
        waiting_client = sum(1 for i in items if i.attention_type == "waiting_for_client")
        publishing = sum(1 for i in items if i.attention_type == "publishing_issue")
        due_today = sum(
            1 for i in items
            if i.attention_type == "scheduling_issue"
            or (i.due_at is not None and i.due_at.date() == _utc_now().date())
        )
        integration = sum(1 for i in items if i.attention_type == "integration_issue")
        scheduling = sum(1 for i in items if i.attention_type == "scheduling_issue")
        telegram = sum(1 for i in items if i.attention_type == "telegram_ingestion_issue")
        automation = sum(1 for i in items if i.attention_type == "automation_failure")
        return OperatorWorkspaceSummary(
            needs_action_now=needs_action,
            waiting_for_client=waiting_client,
            publishing_issues=publishing,
            due_today=due_today,
            integration_issues=integration,
            scheduling_issues=scheduling,
            telegram_issues=telegram,
            automation_failures=automation,
            total=len(items),
        )

    @classmethod
    async def _collect_items(
        cls,
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> list[OperatorAttentionItem]:
        now = _utc_now()
        ctx = get_auth_context()
        tenant_id = ctx.tenant_id if ctx and ctx.is_tenant else None

        items: list[OperatorAttentionItem] = []
        seen_ids: set[str] = set()

        def _add(item: OperatorAttentionItem) -> None:
            if item.id in seen_ids:
                return
            seen_ids.add(item.id)
            items.append(item)

        await cls._collect_content_review(db, client_id, _add)
        await cls._collect_waiting_client(db, client_id, _add)
        await cls._collect_publishing_issues(db, client_id, now, _add)
        await cls._collect_scheduling_issues(db, client_id, now, _add)
        await cls._collect_integration_issues(db, tenant_id, _add)
        await cls._collect_telegram_issues(db, now, _add)
        await cls._collect_automation_failures(db, tenant_id, now, _add)
        await cls._collect_publish_alerts(db, client_id, _add)

        return items

    @classmethod
    async def _collect_content_review(
        cls,
        db: AsyncSession,
        client_id: UUID | None,
        add,
    ) -> None:
        # No row-cap: only actionable internal-review statuses are queried.
        query = (
            select(ContentItem, Client)
            .join(Client, Client.id == ContentItem.client_id)
            .where(
                ContentItem.status.in_(tuple(INTERNAL_REVIEW_STATUSES)),
                or_(
                    ContentItem.client_review_status.is_(None),
                    ContentItem.client_review_status.notin_(
                        (CLIENT_REVIEW_PENDING, CLIENT_REVIEW_CHANGES),
                    ),
                ),
            )
            .order_by(ContentItem.updated_at.desc())
        )
        query, _ = scope_select(query, None, ContentItem.client_id, client_id=client_id)
        rows = (await db.execute(query)).all()
        _warn_if_pathological("content_review", len(rows))
        for item, client in rows:
            add(OperatorAttentionItem(
                id=f"content-review:{item.id}",
                attention_type="content_internal_review",
                priority="medium",
                client_id=item.client_id,
                company_name=client.company_name if client else "Unknown",
                content_id=item.id,
                title=_content_title(item),
                reason="Content awaiting internal review",
                current_state=item.status,
                responsible_party="operator",
                suggested_action="Review content",
                action_path=f"/content/{item.id}",
                created_at=_aware(item.updated_at) or _aware(item.created_at),
                source_domain="content",
                metadata={"reason_code": _REASON_CODES["internal_review"], "status": item.status},
            ))

    @classmethod
    async def _collect_waiting_client(
        cls,
        db: AsyncSession,
        client_id: UUID | None,
        add,
    ) -> None:
        # Aggregate in SQL so large pending volumes cannot drop whole clients.
        # PostgreSQL has no min(uuid)/max(uuid); pick a deterministic representative
        # via window ranking (most recently updated, then id desc as tie-break).
        waiting_filter = or_(
            ContentItem.client_review_status == CLIENT_REVIEW_PENDING,
            ContentItem.client_review_status == CLIENT_REVIEW_CHANGES,
            ContentItem.status == "changes_requested",
        )
        changes_expr = case(
            (
                or_(
                    ContentItem.client_review_status == CLIENT_REVIEW_CHANGES,
                    ContentItem.status == "changes_requested",
                ),
                1,
            ),
            else_=0,
        )
        ranked = (
            select(
                ContentItem.client_id.label("client_id"),
                Client.company_name.label("company_name"),
                ContentItem.id.label("representative_id"),
                func.count(ContentItem.id)
                .over(partition_by=ContentItem.client_id)
                .label("cnt"),
                func.min(ContentItem.updated_at)
                .over(partition_by=ContentItem.client_id)
                .label("oldest"),
                func.max(changes_expr)
                .over(partition_by=ContentItem.client_id)
                .label("has_changes"),
                func.row_number()
                .over(
                    partition_by=ContentItem.client_id,
                    order_by=(ContentItem.updated_at.desc(), ContentItem.id.desc()),
                )
                .label("rn"),
            )
            .join(Client, Client.id == ContentItem.client_id)
            .where(waiting_filter)
        )
        ranked, _ = scope_select(ranked, None, ContentItem.client_id, client_id=client_id)
        ranked_subq = ranked.subquery("waiting_client_ranked")
        query = (
            select(
                ranked_subq.c.client_id,
                ranked_subq.c.company_name,
                ranked_subq.c.cnt,
                ranked_subq.c.oldest,
                ranked_subq.c.representative_id,
                ranked_subq.c.has_changes,
            )
            .where(ranked_subq.c.rn == 1)
            .order_by(ranked_subq.c.oldest.asc())
        )
        rows = (await db.execute(query)).all()
        _warn_if_pathological("waiting_client_groups", len(rows))

        for row in rows:
            cid = row.client_id
            count = int(row.cnt or 0)
            is_changes = bool(row.has_changes)
            reason_code = (
                _REASON_CODES["client_changes"] if is_changes else _REASON_CODES["client_pending"]
            )
            reason = (
                f"Client requested changes on {count} post{'s' if count != 1 else ''}"
                if is_changes
                else f"Client approval pending for {count} post{'s' if count != 1 else ''}"
            )
            representative_id = row.representative_id
            add(OperatorAttentionItem(
                id=f"waiting-client:{cid}",
                attention_type="waiting_for_client",
                priority="low",
                client_id=cid,
                company_name=row.company_name or "Unknown",
                content_id=representative_id if count == 1 else None,
                title=reason,
                reason=reason,
                current_state="changes_requested" if is_changes else "pending",
                responsible_party="client",
                suggested_action="Open client review status",
                action_path=(
                    f"/content/{representative_id}"
                    if count == 1
                    else f"/content?client_id={cid}"
                ),
                created_at=_aware(row.oldest),
                source_domain="content",
                metadata={"reason_code": reason_code, "count": count},
            ))

    @classmethod
    async def _collect_publishing_issues(
        cls,
        db: AsyncSession,
        client_id: UUID | None,
        now: datetime,
        add,
    ) -> None:
        # Actionable publish statuses only — no historical success archive.
        # in_progress: only stale/expired leases (healthy in-flight work is system, not queue noise).
        # retrying: only when next_retry_at is due or unset.
        stale_cutoff = now - timedelta(minutes=PublishResilienceService.stale_minutes())
        statuses = tuple(s for s in OPS_LIST_STATUSES if s != STATUS_IN_PROGRESS)
        query = (
            select(PublishAttempt, ContentItem, Client)
            .join(ContentItem, ContentItem.id == PublishAttempt.content_id)
            .join(Client, Client.id == ContentItem.client_id)
            .where(
                or_(
                    and_(
                        PublishAttempt.status.in_(statuses),
                        or_(
                            PublishAttempt.status != STATUS_RETRYING,
                            PublishAttempt.next_retry_at.is_(None),
                            PublishAttempt.next_retry_at <= now,
                        ),
                    ),
                    and_(
                        PublishAttempt.status == STATUS_IN_PROGRESS,
                        or_(
                            and_(
                                PublishAttempt.lease_expires_at.isnot(None),
                                PublishAttempt.lease_expires_at < now,
                            ),
                            and_(
                                PublishAttempt.started_at.isnot(None),
                                PublishAttempt.started_at <= stale_cutoff,
                            ),
                            and_(
                                PublishAttempt.started_at.is_(None),
                                PublishAttempt.created_at <= stale_cutoff,
                            ),
                        ),
                    ),
                ),
            )
            .order_by(PublishAttempt.created_at.desc())
        )
        query, _ = scope_select(query, None, ContentItem.client_id, client_id=client_id)
        rows = (await db.execute(query)).all()
        _warn_if_pathological("publish_attempts", len(rows))

        for attempt, content, client in rows:
            status = attempt.status
            priority = _priority_for_publish_status(status)
            responsible = _responsible_for_publish(status, failure_code=attempt.failure_code)
            reason_code = {
                STATUS_OPERATOR_REVIEW: _REASON_CODES["publish_operator_review"],
                STATUS_EXHAUSTED: _REASON_CODES["publish_exhausted"],
                STATUS_IN_PROGRESS: _REASON_CODES["publish_stuck"],
                STATUS_RETRYING: _REASON_CODES["publish_retrying"],
            }.get(status, _REASON_CODES["publish_failed"])

            error_msg = sanitize_error_message(attempt.error) if attempt.error else None
            platform = attempt.platform or "unknown"
            reason = error_msg or "Publish attempt requires attention"

            add(OperatorAttentionItem(
                id=f"publish-attempt:{attempt.id}",
                attention_type="publishing_issue",
                priority=priority,
                client_id=content.client_id,
                company_name=client.company_name if client else "Unknown",
                content_id=content.id,
                resource_id=str(attempt.id),
                title=f"{platform.title()} publish issue",
                reason=reason,
                current_state=status,
                responsible_party=responsible,
                suggested_action="Review publish attempt",
                action_path=f"/content/{content.id}",
                created_at=_aware(attempt.created_at),
                source_domain="publishing",
                metadata={
                    "reason_code": reason_code,
                    "platform": platform,
                    "attempt_id": str(attempt.id),
                    "failure_code": attempt.failure_code,
                },
            ))

        stuck_query = (
            select(ContentItem, Client)
            .join(Client, Client.id == ContentItem.client_id)
            .where(ContentItem.status == "publishing")
            .order_by(ContentItem.updated_at.desc())
        )
        stuck_query, _ = scope_select(stuck_query, None, ContentItem.client_id, client_id=client_id)
        stuck_rows = (await db.execute(stuck_query)).all()
        _warn_if_pathological("stuck_publishing", len(stuck_rows))
        for item, client in stuck_rows:
            add(OperatorAttentionItem(
                id=f"stuck-publishing:{item.id}",
                attention_type="publishing_issue",
                priority="critical",
                client_id=item.client_id,
                company_name=client.company_name if client else "Unknown",
                content_id=item.id,
                title=_content_title(item),
                reason="Content stuck in publishing state",
                current_state="publishing",
                responsible_party="operator",
                suggested_action="Review publishing queue",
                action_path=f"/content/{item.id}",
                created_at=_aware(item.scheduled_for) or _aware(item.updated_at),
                due_at=_aware(item.scheduled_for),
                overdue=True,
                source_domain="publishing",
                metadata={"reason_code": _REASON_CODES["publish_stuck"]},
            ))

    @classmethod
    async def _collect_scheduling_issues(
        cls,
        db: AsyncSession,
        client_id: UUID | None,
        now: datetime,
        add,
    ) -> None:
        grace = now - timedelta(minutes=OVERDUE_GRACE_MINUTES)
        query = (
            select(ContentItem, Client)
            .join(Client, Client.id == ContentItem.client_id)
            .where(
                ContentItem.status == "scheduled",
                ContentItem.scheduled_for.isnot(None),
                ContentItem.scheduled_for <= grace,
                ContentItem.approved_at.isnot(None),
            )
            .order_by(ContentItem.scheduled_for.asc())
        )
        query, _ = scope_select(query, None, ContentItem.client_id, client_id=client_id)
        rows = (await db.execute(query)).all()
        _warn_if_pathological("scheduling", len(rows))

        for item, client in rows:
            if client_review_required(item):
                continue
            scheduled_for = _aware(item.scheduled_for)
            is_due = ScheduledPublishDiagnosticsService.compute_is_due(
                item, now=now, platforms=list(item.platforms or []),
            )
            if not is_due:
                continue

            add(OperatorAttentionItem(
                id=f"schedule-overdue:{item.id}",
                attention_type="scheduling_issue",
                priority="critical",
                client_id=item.client_id,
                company_name=client.company_name if client else "Unknown",
                content_id=item.id,
                title=_content_title(item),
                reason="Scheduled publish time passed but content not published",
                current_state="scheduled",
                responsible_party="operator",
                suggested_action="Review publishing queue",
                action_path=f"/content/{item.id}",
                created_at=scheduled_for,
                due_at=scheduled_for,
                overdue=True,
                source_domain="calendar",
                metadata={"reason_code": _REASON_CODES["schedule_overdue"]},
            ))

    @classmethod
    async def _collect_integration_issues(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        add,
    ) -> None:
        query = (
            select(PublishingAccount)
            .where(PublishingAccount.status.in_(tuple(INTEGRATION_ATTENTION_STATUSES)))
            .order_by(PublishingAccount.updated_at.desc())
        )
        tenant_filt = cls._tenant_filter(PublishingAccount.tenant_id)
        if tenant_filt is not None:
            query = query.where(tenant_filt)
        elif tenant_id is not None:
            query = query.where(PublishingAccount.tenant_id == tenant_id)

        accounts = list((await db.scalars(query)).all())
        _warn_if_pathological("integrations", len(accounts))
        for account in accounts:
            priority: AttentionPriority = (
                "critical" if account.status in ("blocked", "missing_permissions") else "high"
            )
            responsible: ResponsibleParty = (
                "provider"
                if account.status in ("expired", "missing_permissions", "invalid")
                else "operator"
            )
            add(OperatorAttentionItem(
                id=f"integration:{account.id}",
                attention_type="integration_issue",
                priority=priority,
                client_id=None,
                company_name=account.account_name,
                resource_id=str(account.id),
                title=f"{account.platform.title()} connection issue",
                reason="Integration connection needs attention",
                current_state=account.status,
                responsible_party=responsible,
                suggested_action="Open integrations",
                action_path=f"/integrations?platform={account.platform}",
                created_at=_aware(account.updated_at) or _aware(account.created_at),
                source_domain="integration",
                metadata={
                    "reason_code": _REASON_CODES["integration_attention"],
                    "platform": account.platform,
                    "account_id": str(account.id),
                    "status": account.status,
                },
            ))

    @classmethod
    async def _collect_telegram_issues(
        cls,
        db: AsyncSession,
        now: datetime,
        add,
    ) -> None:
        # TelegramWebhookEvent is platform-global (no tenant_id). Only surface to
        # platform admins; tenant operators resolve client issues via content/integrations.
        ctx = get_auth_context()
        if not ctx or not ctx.is_admin:
            return

        cutoff = now - timedelta(days=TELEGRAM_ACTIONABLE_DAYS)
        query = (
            select(TelegramWebhookEvent)
            .where(
                TelegramWebhookEvent.status == "failed",
                TelegramWebhookEvent.updated_at >= cutoff,
            )
            .order_by(TelegramWebhookEvent.updated_at.desc())
        )
        events = list((await db.scalars(query)).all())
        _warn_if_pathological("telegram", len(events))
        for event in events:
            add(OperatorAttentionItem(
                id=f"telegram:{event.id}",
                attention_type="telegram_ingestion_issue",
                priority="medium",
                client_id=None,
                company_name="Telegram ingestion",
                resource_id=str(event.id),
                title="Telegram webhook processing failed",
                reason=event.last_error or "Webhook event failed after retries",
                current_state="failed",
                responsible_party="operator",
                suggested_action="Review Telegram settings",
                action_path="/integrations?category=messaging",
                created_at=_aware(event.created_at),
                source_domain="telegram",
                metadata={
                    "reason_code": _REASON_CODES["telegram_failed"],
                    "update_id": event.update_id,
                    "attempts": event.attempts,
                },
            ))

    @classmethod
    async def _collect_automation_failures(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        now: datetime,
        add,
    ) -> None:
        # Conservative derived recency: only jobs touched within the recent
        # actionable window appear as "today" work. Historical dead letters are
        # not mutated; they simply age out of the daily attention projection.
        cutoff = now - timedelta(days=AUTOMATION_ACTIONABLE_DAYS)
        query = (
            select(TenantAutomationJob)
            .where(
                TenantAutomationJob.status.in_(("failed", "dead_letter")),
                TenantAutomationJob.updated_at >= cutoff,
            )
            .order_by(TenantAutomationJob.updated_at.desc())
        )
        tenant_filt = cls._tenant_filter(TenantAutomationJob.tenant_id)
        if tenant_filt is not None:
            query = query.where(tenant_filt)
        elif tenant_id is not None:
            query = query.where(TenantAutomationJob.tenant_id == tenant_id)

        jobs = list((await db.scalars(query)).all())
        _warn_if_pathological("automation", len(jobs))
        for job in jobs:
            is_dead = job.status == "dead_letter"
            flow_q = f"job={job.id}"
            if job.automation_flow_id:
                flow_q = f"flow={job.automation_flow_id}&job={job.id}"
            add(OperatorAttentionItem(
                id=f"automation:{job.id}",
                attention_type="automation_failure",
                priority="high" if is_dead else "medium",
                client_id=None,
                company_name="Automation",
                resource_id=str(job.id),
                title=(
                    "Automation job requires attention"
                    if is_dead
                    else "Automation job failed"
                ),
                reason=job.error_message or "Automation job requires attention",
                current_state=job.status,
                responsible_party="operator",
                suggested_action="Open automation center",
                action_path=f"/automation?{flow_q}",
                created_at=_aware(job.updated_at) or _aware(job.created_at),
                source_domain="automation",
                metadata={
                    "reason_code": (
                        _REASON_CODES["automation_dead_letter"]
                        if is_dead
                        else _REASON_CODES["automation_failed"]
                    ),
                    "job_id": str(job.id),
                    "flow_id": str(job.automation_flow_id) if job.automation_flow_id else None,
                    "error_code": job.error_code,
                },
            ))

    @classmethod
    async def _collect_publish_alerts(
        cls,
        db: AsyncSession,
        client_id: UUID | None,
        add,
    ) -> None:
        query = (
            select(PublishOperatorAlert, ContentItem, Client)
            .join(ContentItem, ContentItem.id == PublishOperatorAlert.content_id)
            .join(Client, Client.id == ContentItem.client_id)
            .where(PublishOperatorAlert.state.in_(("open", "acknowledged")))
            .order_by(PublishOperatorAlert.created_at.desc())
        )
        query, _ = scope_select(query, None, ContentItem.client_id, client_id=client_id)
        rows = (await db.execute(query)).all()
        _warn_if_pathological("publish_alerts", len(rows))

        for alert, content, client in rows:
            severity = alert.severity or "warning"
            priority: AttentionPriority = "critical" if severity == "critical" else "high"
            add(OperatorAttentionItem(
                id=f"publish-alert:{alert.id}",
                attention_type="publishing_issue",
                priority=priority,
                client_id=content.client_id,
                company_name=client.company_name if client else "Unknown",
                content_id=content.id,
                resource_id=str(alert.id),
                title=alert.title or "Publishing alert",
                reason=alert.body or "Publishing alert requires review",
                current_state=alert.state,
                responsible_party="operator",
                suggested_action="Review publishing alert",
                action_path=f"/publishing/alerts?alert_id={alert.id}",
                created_at=_aware(alert.created_at),
                source_domain="publishing",
                metadata={
                    "reason_code": _REASON_CODES["publish_alert"],
                    "alert_id": str(alert.id),
                    "alert_type": alert.alert_type,
                },
            ))
