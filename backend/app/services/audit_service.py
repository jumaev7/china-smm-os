"""Audit & QA Center — read-only workflow and data integrity checks."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client import Client
from app.models.content import ContentItem
from app.models.crm_deal import CrmDeal
from app.models.crm_document import CrmDocument
from app.models.crm_lead import CrmLead
from app.models.operator_task import OperatorTask
from app.models.partner import Partner
from app.models.publish_attempt import PublishAttempt
from app.models.publishing_account import PublishingAccount
from app.services.content_review_service import client_review_required, is_client_approved
from app.services.operator_task_service import TERMINAL_STATUSES
from app.services.publishing_account_service import ACTIVE_STATUSES
from app.services.audit_fix_service import AUDIT_REVIEWED_MARKER, CHECK_FIX_ACTIONS, build_issue_id
from app.services.schema_guard import SchemaGuard
from app.services.system_health_service import DEMO_NOTES_MARKER
from app.utils.telegram_publish_destination import validate_telegram_publish_chat_id

logger = logging.getLogger(__name__)

_MAX_ISSUES_PER_CHECK = 50


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _issue(
    *,
    check_key: str,
    severity: str,
    category: str,
    title: str,
    description: str,
    entity_type: str,
    entity_id: UUID | str | None,
    suggested_fix: str,
) -> dict[str, Any]:
    issue_id = build_issue_id(check_key, entity_type, entity_id)
    fix_type, fix_label = CHECK_FIX_ACTIONS.get(check_key, (None, None))
    fix_endpoint = (
        f"/api/v1/audit/fixes/{issue_id}/apply"
        if fix_type and fix_type != "open_billing"
        else None
    )
    fix_method = "POST" if fix_endpoint else None
    return {
        "id": issue_id,
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "suggested_fix": suggested_fix,
        "fix_action_type": fix_type,
        "fix_action_label": fix_label,
        "fix_action_endpoint": fix_endpoint,
        "fix_action_method": fix_method,
    }


class AuditService:
    @staticmethod
    async def _run_check(
        db: AsyncSession,
        label: str,
        checker,
        issues: list[dict[str, Any]],
        *,
        errors: list[str],
    ) -> None:
        try:
            result = checker(db, issues)
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            logger.warning("[Audit] check failed: %s — %s", label, exc, exc_info=True)
            try:
                await db.rollback()
            except Exception as rollback_exc:
                logger.warning("[Audit] rollback after failed check %s: %s", label, rollback_exc)
            errors.append(f"{label}: {exc}")
            issues.append(_issue(
                check_key=f"{label}.failed",
                severity="warning",
                category="system",
                title=f"Audit check unavailable: {label}",
                description=str(exc)[:500],
                entity_type="system",
                entity_id=None,
                suggested_fix="Review server logs and run database migrations (alembic upgrade head).",
            ))

    @staticmethod
    async def run(db: AsyncSession) -> dict[str, Any]:
        now = _utc_now()
        issues: list[dict[str, Any]] = []
        errors: list[str] = []

        checks = [
            ("clients.telegram_intake", AuditService._check_clients_telegram_intake),
            ("clients.telegram_publish", AuditService._check_clients_telegram_publish),
            ("content.scheduled_not_admin", AuditService._check_scheduled_not_admin_approved),
            ("content.scheduled_not_client", AuditService._check_scheduled_not_client_approved),
            ("publishing.missing_account", AuditService._check_content_missing_publish_account),
            ("publishing.failed_attempts", AuditService._check_failed_publish_attempts),
            ("revenue.missing_commission", AuditService._check_won_deals_missing_commission),
            ("billing.unpaid_invoices", lambda db, iss: AuditService._check_unpaid_invoices(db, iss, now)),
            ("billing.overdue_documents", lambda db, iss: AuditService._check_overdue_documents(db, iss, now)),
            ("crm.overdue_followups", lambda db, iss: AuditService._check_overdue_lead_followups(db, iss, now)),
            ("tasks.overdue", lambda db, iss: AuditService._check_overdue_tasks(db, iss, now)),
            ("billing.missing_plan", AuditService._check_missing_billing_plan),
            ("system.demo_data", AuditService._check_demo_data_count),
        ]
        for label, checker in checks:
            await AuditService._run_check(db, label, checker, issues, errors=errors)

        summary = {
            "critical": sum(1 for i in issues if i["severity"] == "critical"),
            "warning": sum(1 for i in issues if i["severity"] == "warning"),
            "info": sum(1 for i in issues if i["severity"] == "info"),
            "total": len(issues),
        }
        categories = sorted({i["category"] for i in issues})

        logger.info(
            "[Audit] run complete: critical=%s warning=%s info=%s total=%s errors=%s",
            summary["critical"],
            summary["warning"],
            summary["info"],
            summary["total"],
            len(errors),
        )

        return {
            "issues": issues,
            "summary": summary,
            "categories": categories,
            "ran_at": now,
            "errors": errors,
        }

    @staticmethod
    async def _check_clients_telegram_intake(db: AsyncSession, issues: list[dict]) -> None:
        result = await db.execute(
            select(Client)
            .where(
                Client.status == "active",
                or_(Client.telegram_group_id.is_(None), Client.telegram_group_id == ""),
            )
            .order_by(Client.company_name)
            .limit(_MAX_ISSUES_PER_CHECK)
        )
        for client in result.scalars().all():
            issues.append(_issue(
                check_key="clients.telegram_intake",
                severity="warning",
                category="clients",
                title=f"No Telegram intake group — {client.company_name}",
                description="Active client has no linked Telegram intake group for media and instructions.",
                entity_type="client",
                entity_id=client.id,
                suggested_fix="Open client settings and link the Telegram intake group.",
            ))

    @staticmethod
    async def _check_clients_telegram_publish(db: AsyncSession, issues: list[dict]) -> None:
        result = await db.execute(
            select(Client)
            .where(
                Client.status == "active",
                or_(
                    Client.telegram_publish_chat_id.is_(None),
                    Client.telegram_publish_chat_id == "",
                ),
            )
            .order_by(Client.company_name)
            .limit(_MAX_ISSUES_PER_CHECK)
        )
        for client in result.scalars().all():
            issues.append(_issue(
                check_key="clients.telegram_publish",
                severity="warning",
                category="clients",
                title=f"No Telegram publish destination — {client.company_name}",
                description="Active client has no Telegram channel or group configured for publishing.",
                entity_type="client",
                entity_id=client.id,
                suggested_fix="Set the Telegram publish destination on the client profile.",
            ))

    @staticmethod
    async def _check_scheduled_not_admin_approved(db: AsyncSession, issues: list[dict]) -> None:
        result = await db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.client))
            .where(
                ContentItem.status == "scheduled",
                ContentItem.approved_at.is_(None),
            )
            .order_by(ContentItem.scheduled_for)
            .limit(_MAX_ISSUES_PER_CHECK)
        )
        for item in result.scalars().all():
            client_name = item.client.company_name if item.client else "Unknown"
            issues.append(_issue(
                check_key="content.scheduled_not_admin",
                severity="critical",
                category="content",
                title=f"Scheduled without admin approval — {client_name}",
                description="Content is scheduled to publish but has not been admin-approved.",
                entity_type="content",
                entity_id=item.id,
                suggested_fix="Admin-approve the content before its scheduled publish time.",
            ))

    @staticmethod
    async def _check_scheduled_not_client_approved(db: AsyncSession, issues: list[dict]) -> None:
        result = await db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.client))
            .where(ContentItem.status == "scheduled")
            .order_by(ContentItem.scheduled_for)
            .limit(_MAX_ISSUES_PER_CHECK * 2)
        )
        count = 0
        for item in result.scalars().all():
            if count >= _MAX_ISSUES_PER_CHECK:
                break
            needs_client = client_review_required(item) or (
                item.client_review_status and not is_client_approved(item)
            )
            if not needs_client:
                continue
            count += 1
            client_name = item.client.company_name if item.client else "Unknown"
            issues.append(_issue(
                check_key="content.scheduled_not_client",
                severity="critical",
                category="content",
                title=f"Scheduled without client approval — {client_name}",
                description=(
                    f"Content is scheduled but client review status is "
                    f"{item.client_review_status or 'pending'}."
                ),
                entity_type="content",
                entity_id=item.id,
                suggested_fix="Send client review preview and wait for client approval before publishing.",
            ))

    @staticmethod
    def _platform_account_available(
        platform: str,
        *,
        by_platform: dict[str, list[PublishingAccount]],
        telegram_by_chat: dict[str, PublishingAccount],
        client_publish_chat_id: str | None,
    ) -> bool:
        if platform == "telegram" and client_publish_chat_id:
            try:
                normalized = validate_telegram_publish_chat_id(client_publish_chat_id)
            except ValueError:
                normalized = None
            if normalized and normalized in telegram_by_chat:
                return True
        return bool(by_platform.get(platform))

    @staticmethod
    def _tenant_account_indexes(
        accounts: list[PublishingAccount],
    ) -> dict:
        by_tenant: dict = {}
        for acc in accounts:
            tenant_entry = by_tenant.setdefault(
                acc.tenant_id,
                {"by_platform": defaultdict(list), "telegram_by_chat": {}},
            )
            tenant_entry["by_platform"][acc.platform].append(acc)
            if acc.platform == "telegram":
                tenant_entry["telegram_by_chat"][acc.account_id] = acc
        return by_tenant

    @staticmethod
    async def _check_content_missing_publish_account(db: AsyncSession, issues: list[dict]) -> None:
        accounts_r = await db.execute(
            select(PublishingAccount).where(
                PublishingAccount.status.in_(tuple(ACTIVE_STATUSES)),
            )
        )
        accounts = list(accounts_r.scalars().all())
        by_tenant = AuditService._tenant_account_indexes(accounts)

        result = await db.execute(
            select(
                ContentItem,
                Client.telegram_publish_chat_id,
                Client.company_name,
                Client.tenant_id,
            )
            .join(Client, Client.id == ContentItem.client_id)
            .where(
                ContentItem.status.in_(("scheduled", "approved", "publishing", "failed", "partial_failed")),
                func.coalesce(func.cardinality(ContentItem.platforms), 0) > 0,
            )
            .order_by(ContentItem.updated_at.desc())
            .limit(_MAX_ISSUES_PER_CHECK * 3)
        )
        count = 0
        for item, publish_chat_id, company_name, tenant_id in result.all():
            if count >= _MAX_ISSUES_PER_CHECK:
                break
            if tenant_id is None:
                continue
            tenant_accounts = by_tenant.get(tenant_id, {})
            by_platform = tenant_accounts.get("by_platform", {})
            telegram_by_chat = tenant_accounts.get("telegram_by_chat", {})
            missing = [
                p for p in (item.platforms or [])
                if not AuditService._platform_account_available(
                    p,
                    by_platform=by_platform,
                    telegram_by_chat=telegram_by_chat,
                    client_publish_chat_id=publish_chat_id,
                )
            ]
            if not missing:
                continue
            count += 1
            issues.append(_issue(
                check_key="publishing.missing_account",
                severity="warning",
                category="publishing",
                title=f"Missing publishing account — {company_name}",
                description=f"Content targets {', '.join(missing)} but no connected account is available.",
                entity_type="content",
                entity_id=item.id,
                suggested_fix="Add or connect publishing accounts for the missing platforms.",
            ))

    @staticmethod
    async def _check_failed_publish_attempts(db: AsyncSession, issues: list[dict]) -> None:
        result = await db.execute(
            select(PublishAttempt, ContentItem.client_id)
            .join(ContentItem, ContentItem.id == PublishAttempt.content_id)
            .where(PublishAttempt.status == "failed")
            .order_by(PublishAttempt.created_at.desc())
            .limit(_MAX_ISSUES_PER_CHECK)
        )
        for attempt, _client_id in result.all():
            if attempt.response and AUDIT_REVIEWED_MARKER in attempt.response:
                continue
            err = (attempt.error or attempt.response or "Unknown error")[:200]
            issues.append(_issue(
                check_key="publishing.failed_attempts",
                severity="critical",
                category="publishing",
                title=f"Failed publish on {attempt.platform}",
                description=f"Publish attempt failed: {err}",
                entity_type="publish_attempt",
                entity_id=attempt.id,
                suggested_fix="Review the content, fix the issue, and retry publishing from the queue.",
            ))

    @staticmethod
    async def _check_won_deals_missing_commission(db: AsyncSession, issues: list[dict]) -> None:
        result = await db.execute(
            select(CrmDeal)
            .where(
                CrmDeal.status == "won",
                CrmDeal.commission_amount.is_(None),
            )
            .order_by(CrmDeal.updated_at.desc())
            .limit(_MAX_ISSUES_PER_CHECK)
        )
        for deal in result.scalars().all():
            issues.append(_issue(
                check_key="revenue.missing_commission",
                severity="warning",
                category="revenue",
                title=f"Won deal missing commission — {deal.title}",
                description="Deal is marked won but commission amount has not been calculated.",
                entity_type="deal",
                entity_id=deal.id,
                suggested_fix="Open the deal in Revenue and set commission percent or amount.",
            ))

    @staticmethod
    async def _check_unpaid_invoices(db: AsyncSession, issues: list[dict], now: datetime) -> None:
        result = await db.execute(
            select(CrmDocument)
            .where(
                CrmDocument.document_type == "invoice",
                CrmDocument.status == "sent",
            )
            .order_by(CrmDocument.created_at.desc())
            .limit(_MAX_ISSUES_PER_CHECK)
        )
        for doc in result.scalars().all():
            due = _aware(doc.due_date)
            overdue = due is not None and due < now
            issues.append(_issue(
                check_key="billing.unpaid_invoice",
                severity="critical" if overdue else "warning",
                category="billing",
                title=f"Unpaid invoice — {doc.title}",
                description=(
                    f"Invoice status is sent"
                    + (f" and overdue since {due.date().isoformat()}" if overdue else "")
                    + "."
                ),
                entity_type="document",
                entity_id=doc.id,
                suggested_fix="Follow up with the client and mark the invoice paid when received.",
            ))

    @staticmethod
    async def _check_overdue_documents(db: AsyncSession, issues: list[dict], now: datetime) -> None:
        result = await db.execute(
            select(CrmDocument)
            .where(
                CrmDocument.due_date.isnot(None),
                CrmDocument.due_date < now,
                CrmDocument.status.notin_(("paid", "canceled")),
                CrmDocument.document_type != "invoice",
            )
            .order_by(CrmDocument.due_date)
            .limit(_MAX_ISSUES_PER_CHECK)
        )
        for doc in result.scalars().all():
            due = _aware(doc.due_date)
            issues.append(_issue(
                check_key="billing.overdue_document",
                severity="warning",
                category="billing",
                title=f"Overdue {doc.document_type} — {doc.title}",
                description=f"{doc.document_type.title()} was due {due.date().isoformat() if due else 'unknown'}.",
                entity_type="document",
                entity_id=doc.id,
                suggested_fix="Review the document status and follow up with the client.",
            ))

    @staticmethod
    async def _check_overdue_lead_followups(db: AsyncSession, issues: list[dict], now: datetime) -> None:
        available = await SchemaGuard.table_columns(db, "crm_leads")
        if "next_follow_up_at" not in available:
            issues.append(_issue(
                check_key="crm.overdue_followups_unavailable",
                severity="warning",
                category="crm",
                title="Overdue follow-ups check unavailable",
                description="crm_leads.next_follow_up_at column is missing from database.",
                entity_type="system",
                entity_id=None,
                suggested_fix="Run alembic upgrade head or restart backend in development.",
            ))
            return
        try:
            query = (
                select(CrmLead)
                .where(
                    CrmLead.next_follow_up_at.isnot(None),
                    CrmLead.next_follow_up_at < now,
                    CrmLead.status.notin_(("won", "lost")),
                )
                .order_by(CrmLead.next_follow_up_at)
                .limit(_MAX_ISSUES_PER_CHECK)
            )
            query = await SchemaGuard.apply_crm_lead_query_options(db, query)
            result = await db.execute(query)
        except Exception as exc:
            logger.warning("[Audit] crm.overdue_followups query failed: %s", exc)
            await db.rollback()
            issues.append(_issue(
                check_key="crm.overdue_followups_unavailable",
                severity="warning",
                category="crm",
                title="Overdue follow-ups check unavailable",
                description=str(exc)[:500],
                entity_type="system",
                entity_id=None,
                suggested_fix="Run database migrations to sync crm_leads schema.",
            ))
            return

        for lead in result.scalars().all():
            due = _aware(lead.next_follow_up_at)
            issues.append(_issue(
                check_key="crm.overdue_followup",
                severity="warning",
                category="crm",
                title=f"Overdue follow-up — {lead.name}",
                description=f"Follow-up was due {due.date().isoformat() if due else 'unknown'} (status: {lead.status}).",
                entity_type="lead",
                entity_id=lead.id,
                suggested_fix="Contact the lead and schedule the next follow-up in CRM.",
            ))

    @staticmethod
    async def _check_overdue_tasks(db: AsyncSession, issues: list[dict], now: datetime) -> None:
        try:
            result = await db.execute(
                select(OperatorTask)
                .where(
                    OperatorTask.due_at.isnot(None),
                    OperatorTask.due_at < now,
                    OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
                )
                .order_by(OperatorTask.due_at)
                .limit(_MAX_ISSUES_PER_CHECK)
            )
        except Exception as exc:
            logger.warning("[Audit] tasks.overdue query failed: %s", exc)
            await db.rollback()
            issues.append(_issue(
                check_key="tasks.overdue_unavailable",
                severity="warning",
                category="tasks",
                title="Overdue tasks check unavailable",
                description=(
                    "Could not query operator tasks — database schema may be out of date "
                    f"({exc})."
                ),
                entity_type="system",
                entity_id=None,
                suggested_fix="Run alembic upgrade head to add operator_tasks execution columns.",
            ))
            return

        for task in result.scalars().all():
            due = _aware(task.due_at)
            issues.append(_issue(
                check_key="tasks.overdue",
                severity="warning",
                category="tasks",
                title=f"Overdue task — {task.title}",
                description=f"Task was due {due.date().isoformat() if due else 'unknown'} (status: {task.status}).",
                entity_type="task",
                entity_id=task.id,
                suggested_fix="Complete or reschedule the task on the Tasks board.",
            ))

    @staticmethod
    async def _check_missing_billing_plan(db: AsyncSession, issues: list[dict]) -> None:
        result = await db.execute(
            select(Client)
            .where(
                Client.status == "active",
                or_(Client.plan_name.is_(None), Client.plan_name == ""),
            )
            .order_by(Client.company_name)
            .limit(_MAX_ISSUES_PER_CHECK)
        )
        for client in result.scalars().all():
            issues.append(_issue(
                check_key="billing.missing_plan",
                severity="warning",
                category="billing",
                title=f"Missing billing plan — {client.company_name}",
                description="Active client has no subscription plan configured.",
                entity_type="client",
                entity_id=client.id,
                suggested_fix="Assign a billing plan and monthly fee on the client billing settings.",
            ))

    @staticmethod
    async def _check_demo_data_count(db: AsyncSession, issues: list[dict]) -> None:
        demo_clients = int(await db.scalar(
            select(func.count()).select_from(Client).where(Client.notes.contains(DEMO_NOTES_MARKER))
        ) or 0)
        demo_partners = int(await db.scalar(
            select(func.count()).select_from(Partner).where(Partner.notes.contains(DEMO_NOTES_MARKER))
        ) or 0)
        demo_leads = int(await db.scalar(
            select(func.count()).select_from(CrmLead).where(CrmLead.notes.contains(DEMO_NOTES_MARKER))
        ) or 0)
        total = demo_clients + demo_partners + demo_leads

        if total == 0:
            issues.append(_issue(
                check_key="system.demo_data",
                severity="info",
                category="system",
                title="No demo data loaded",
                description="System demo seed has not been run or was reset.",
                entity_type="system",
                entity_id=None,
                suggested_fix="Use System → Seed Demo Data before a demo session.",
            ))
        else:
            issues.append(_issue(
                check_key="system.demo_data_present",
                severity="info",
                category="system",
                title=f"Demo data present ({total} tagged records)",
                description=(
                    f"{demo_clients} demo client(s), {demo_leads} demo lead(s), "
                    f"{demo_partners} demo partner(s) tagged with {DEMO_NOTES_MARKER}."
                ),
                entity_type="system",
                entity_id=None,
                suggested_fix="Reset demo data from System after demos to avoid mixing with real clients.",
            ))
