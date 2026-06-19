"""AI CEO Dashboard — executive overview and briefing."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.endpoint_guard import safe_section
from app.models.client import Client
from app.models.content import ContentItem
from app.models.crm_deal import CrmDeal, CrmDealEvent
from app.models.crm_document import CrmDocument
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.crm_proposal import CrmProposal
from app.models.operator_task import OperatorTask
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.billing_service import BillingService
from app.services.operator_common import INBOX_NEW
from app.services.operator_task_engine_service import OperatorTaskEngineService
from app.services.operator_task_service import TERMINAL_STATUSES

logger = logging.getLogger(__name__)

_STALE_DAYS = 14
_PROPOSAL_STALL_DAYS = 7

_ACTIVE_DEAL_STATUSES = frozenset({
    "new", "proposal", "contract", "invoice", "waiting_payment",
})

_AI_SYSTEM = """\
You are an executive briefing assistant for a Chinese-company SMM agency in Uzbekistan.
Analyze operational metrics and return ONLY JSON:
{
  "executive_summary": "2-4 sentence overview of business health today",
  "top_priorities": ["priority 1", "priority 2", "priority 3"],
  "risks": ["risk 1", "risk 2"],
  "opportunities": ["opportunity 1", "opportunity 2"],
  "recommended_actions": ["action 1", "action 2", "action 3"]
}

Rules:
- Dashboard is read-only — recommend manual operator actions only
- Never suggest auto-send, auto-publish, or auto status changes
- Be specific using names from the data when available
- Prioritize revenue, client satisfaction, and pipeline momentum
- Max 5 items per list; concise imperative phrases
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class DashboardService:
    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        now = _utc_now()
        errors: list[str] = []

        async def _inbox_new() -> int:
            return int(await db.scalar(
                select(func.count())
                .select_from(TelegramGroupBufferMessage)
                .where(
                    TelegramGroupBufferMessage.inbox_status == INBOX_NEW,
                    TelegramGroupBufferMessage.linked_content_id.is_(None),
                )
            ) or 0)

        async def _tasks_open() -> int:
            return int(await db.scalar(
                select(func.count())
                .select_from(OperatorTask)
                .where(OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)))
            ) or 0)

        async def _content_ready() -> int:
            return int(await db.scalar(
                select(func.count()).select_from(ContentItem).where(ContentItem.status == "ready")
            ) or 0)

        async def _content_scheduled() -> int:
            return int(await db.scalar(
                select(func.count()).select_from(ContentItem).where(ContentItem.status == "scheduled")
            ) or 0)

        async def _clients_waiting() -> int:
            return int(await db.scalar(
                select(func.count(func.distinct(ContentItem.client_id)))
                .select_from(ContentItem)
                .where(ContentItem.media_request_status == "requested")
            ) or 0)

        async def _invoices_unpaid() -> int:
            return int(await db.scalar(
                select(func.count())
                .select_from(CrmDocument)
                .where(
                    CrmDocument.document_type == "invoice",
                    CrmDocument.status == "sent",
                )
            ) or 0)

        async def _active_deals() -> int:
            return int(await db.scalar(
                select(func.count())
                .select_from(CrmDeal)
                .where(CrmDeal.status.in_(tuple(_ACTIVE_DEAL_STATUSES)))
            ) or 0)

        async def _won_deals() -> int:
            return int(await db.scalar(
                select(func.count()).select_from(CrmDeal).where(CrmDeal.status == "won")
            ) or 0)

        async def _lost_deals() -> int:
            return int(await db.scalar(
                select(func.count()).select_from(CrmDeal).where(CrmDeal.status == "lost")
            ) or 0)

        async def _pipeline_value() -> Decimal:
            raw = await db.scalar(
                select(func.coalesce(func.sum(CrmDeal.expected_value), 0))
                .select_from(CrmDeal)
                .where(CrmDeal.status.in_(tuple(_ACTIVE_DEAL_STATUSES)))
            )
            return Decimal(str(raw or 0))

        async def _overdue_followups() -> int:
            return int(await db.scalar(
                select(func.count())
                .select_from(CrmLead)
                .where(
                    CrmLead.next_follow_up_at.isnot(None),
                    CrmLead.next_follow_up_at < now,
                    CrmLead.status.notin_(("won", "lost")),
                )
            ) or 0)

        async def _billing() -> tuple[float, int]:
            billing = await BillingService.overview(db)
            return (
                float(billing.get("monthly_recurring_revenue") or 0),
                len(billing.get("clients_near_limit") or []),
            )

        async def _deal_risks() -> list[dict[str, Any]]:
            return await DashboardService._detect_deal_risks(db, now)

        inbox_new = await safe_section("inbox", _inbox_new(), default=0, errors=errors, db=db)
        tasks_open = await safe_section("tasks", _tasks_open(), default=0, errors=errors, db=db)
        content_ready = await safe_section("content_ready", _content_ready(), default=0, errors=errors, db=db)
        content_scheduled = await safe_section("content_scheduled", _content_scheduled(), default=0, errors=errors, db=db)
        clients_waiting_materials = await safe_section(
            "clients_waiting", _clients_waiting(), default=0, errors=errors, db=db,
        )
        invoices_unpaid = await safe_section("invoices", _invoices_unpaid(), default=0, errors=errors, db=db)
        active_deals = await safe_section("active_deals", _active_deals(), default=0, errors=errors, db=db)
        won_deals = await safe_section("won_deals", _won_deals(), default=0, errors=errors, db=db)
        lost_deals = await safe_section("lost_deals", _lost_deals(), default=0, errors=errors, db=db)
        pipeline_value = await safe_section("pipeline", _pipeline_value(), default=Decimal("0"), errors=errors, db=db)
        overdue_followups = await safe_section("followups", _overdue_followups(), default=0, errors=errors, db=db)
        mrr, near_limit_clients = await safe_section(
            "billing", _billing(), default=(0.0, 0), errors=errors, db=db,
        )
        deal_risks = await safe_section("deal_risks", _deal_risks(), default=[], errors=errors, db=db)

        async def _operator_today() -> dict[str, Any]:
            return await OperatorTaskEngineService.today_tasks(db)

        operator_today = await safe_section(
            "operator_tasks_today", _operator_today(), default={"count": 0, "items": []}, errors=errors, db=db,
        )

        return {
            "inbox_new": inbox_new,
            "tasks_open": tasks_open,
            "operator_tasks_today": int(operator_today.get("count") or 0),
            "operator_tasks_today_items": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "priority": item["priority"],
                    "action_type": item.get("action_type"),
                    "due_at": item.get("due_at"),
                }
                for item in (operator_today.get("items") or [])
            ],
            "content_ready": content_ready,
            "content_scheduled": content_scheduled,
            "clients_waiting_materials": clients_waiting_materials,
            "invoices_unpaid": invoices_unpaid,
            "active_deals": active_deals,
            "won_deals": won_deals,
            "lost_deals": lost_deals,
            "pipeline_value": pipeline_value,
            "mrr": mrr,
            "overdue_followups": overdue_followups,
            "near_limit_clients": near_limit_clients,
            "deal_risks": deal_risks,
            "errors": errors,
        }

    @staticmethod
    async def ai_summary(db: AsyncSession) -> dict[str, Any]:
        overview = await DashboardService.overview(db)
        context = await DashboardService._build_ai_context(db, overview)

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                result = DashboardService._heuristic_summary(overview)
            else:
                _validate_api_key()
                openai = get_openai()
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": _AI_SYSTEM},
                        {"role": "user", "content": context[:12000]},
                    ],
                    temperature=0.4,
                    max_tokens=900,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                result = {
                    "executive_summary": str(parsed.get("executive_summary") or "")[:2000],
                    "top_priorities": DashboardService._as_str_list(parsed.get("top_priorities"), 5),
                    "risks": DashboardService._as_str_list(parsed.get("risks"), 5),
                    "opportunities": DashboardService._as_str_list(parsed.get("opportunities"), 5),
                    "recommended_actions": DashboardService._as_str_list(parsed.get("recommended_actions"), 5),
                    "source": "ai",
                }
        except Exception as exc:
            logger.warning("[Dashboard] AI summary fallback: %s", exc)
            result = DashboardService._heuristic_summary(overview)

        logger.info("[Dashboard] ai-summary: source=%s", result["source"])
        return result

    @staticmethod
    async def _detect_deal_risks(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
        stale_cutoff = now - timedelta(days=_STALE_DAYS)
        proposal_cutoff = now - timedelta(days=_PROPOSAL_STALL_DAYS)
        risks: list[dict[str, Any]] = []

        deals_r = await db.execute(
            select(CrmDeal)
            .options(selectinload(CrmDeal.lead))
            .where(CrmDeal.status.in_(tuple(_ACTIVE_DEAL_STATUSES)))
            .order_by(CrmDeal.updated_at.desc())
            .limit(80)
        )
        deals = list(deals_r.scalars().all())
        if not deals:
            return risks

        deal_ids = [d.id for d in deals]
        lead_ids = [d.lead_id for d in deals]

        events_r = await db.execute(
            select(CrmDealEvent)
            .where(CrmDealEvent.deal_id.in_(deal_ids))
            .order_by(CrmDealEvent.created_at.desc())
        )
        events_by_deal: dict[UUID, list[CrmDealEvent]] = {}
        for ev in events_r.scalars().all():
            events_by_deal.setdefault(ev.deal_id, []).append(ev)

        activities_r = await db.execute(
            select(CrmActivity)
            .where(CrmActivity.lead_id.in_(lead_ids))
            .order_by(CrmActivity.created_at.desc())
        )
        activities_by_lead: dict[UUID, list[CrmActivity]] = {}
        for act in activities_r.scalars().all():
            activities_by_lead.setdefault(act.lead_id, []).append(act)

        proposals_r = await db.execute(
            select(CrmProposal)
            .where(CrmProposal.lead_id.in_(lead_ids))
            .order_by(CrmProposal.updated_at.desc())
        )
        proposals_by_lead: dict[UUID, list[CrmProposal]] = {}
        for prop in proposals_r.scalars().all():
            proposals_by_lead.setdefault(prop.lead_id, []).append(prop)

        invoices_r = await db.execute(
            select(CrmDocument)
            .where(
                CrmDocument.lead_id.in_(lead_ids),
                CrmDocument.document_type == "invoice",
                CrmDocument.status == "sent",
            )
        )
        unpaid_by_lead: dict[UUID, CrmDocument] = {}
        for inv in invoices_r.scalars().all():
            unpaid_by_lead.setdefault(inv.lead_id, inv)

        seen: set[tuple[UUID, str]] = set()

        def _add(deal: CrmDeal, risk_type: str, title: str, severity: str = "medium") -> None:
            key = (deal.id, risk_type)
            if key in seen:
                return
            seen.add(key)
            lead = deal.lead
            risks.append({
                "deal_id": deal.id,
                "lead_id": deal.lead_id,
                "lead_name": lead.name if lead else None,
                "deal_title": deal.title,
                "risk_type": risk_type,
                "title": title,
                "severity": severity,
            })

        for deal in deals:
            lead = deal.lead
            if not lead:
                continue

            if lead.next_follow_up_at and _aware(lead.next_follow_up_at) < now and lead.status not in ("won", "lost"):
                _add(
                    deal,
                    "overdue_followup",
                    f"Overdue follow-up: {lead.name}",
                    "high",
                )

            last_touch: datetime | None = None
            for ev in events_by_deal.get(deal.id, [])[:1]:
                last_touch = _aware(ev.created_at)
            for act in activities_by_lead.get(deal.lead_id, [])[:1]:
                act_ts = _aware(act.created_at)
                if act_ts and (last_touch is None or act_ts > last_touch):
                    last_touch = act_ts
            if last_touch is None:
                last_touch = _aware(deal.updated_at) or _aware(deal.created_at)
            if last_touch and last_touch < stale_cutoff:
                _add(
                    deal,
                    "stale_activity",
                    f"No activity 14+ days: {lead.name}",
                    "medium",
                )

            sent_proposals = [
                p for p in proposals_by_lead.get(deal.lead_id, [])
                if p.status == "sent"
            ]
            if sent_proposals:
                latest_sent = sent_proposals[0]
                sent_at = _aware(latest_sent.updated_at) or _aware(latest_sent.created_at)
                progressed = deal.status in ("contract", "invoice", "waiting_payment", "won")
                if sent_at and sent_at < proposal_cutoff and not progressed:
                    _add(
                        deal,
                        "proposal_stalled",
                        f"Proposal sent, no progress: {lead.name}",
                        "high",
                    )

            if deal.lead_id in unpaid_by_lead:
                inv = unpaid_by_lead[deal.lead_id]
                _add(
                    deal,
                    "invoice_unpaid",
                    f"Unpaid invoice: {lead.name} ({inv.title})",
                    "high",
                )

        severity_order = {"high": 0, "medium": 1}
        risks.sort(key=lambda r: severity_order.get(r["severity"], 2))
        return risks[:20]

    @staticmethod
    async def _build_ai_context(db: AsyncSession, overview: dict[str, Any]) -> str:
        now = _utc_now()
        lines = [
            "EXECUTIVE METRICS:",
            f"- Inbox new: {overview['inbox_new']}",
            f"- Open tasks: {overview['tasks_open']}",
            f"- Content ready: {overview['content_ready']}, scheduled: {overview['content_scheduled']}",
            f"- Clients waiting materials: {overview['clients_waiting_materials']}",
            f"- Unpaid invoices: {overview['invoices_unpaid']}",
            f"- Active deals: {overview['active_deals']}, won: {overview['won_deals']}, lost: {overview['lost_deals']}",
            f"- Pipeline value: {overview['pipeline_value']} UZS",
            f"- MRR: ${overview['mrr']}",
            f"- Overdue follow-ups: {overview['overdue_followups']}",
            f"- Clients near post limit: {overview['near_limit_clients']}",
            "",
            "DEAL RISKS:",
        ]
        for risk in overview.get("deal_risks") or []:
            lines.append(f"- [{risk['risk_type']}] {risk['title']}")

        overdue_leads_r = await db.execute(
            select(CrmLead)
            .where(
                CrmLead.next_follow_up_at.isnot(None),
                CrmLead.next_follow_up_at < now,
                CrmLead.status.notin_(("won", "lost")),
            )
            .order_by(CrmLead.next_follow_up_at)
            .limit(5)
        )
        overdue = list(overdue_leads_r.scalars().all())
        if overdue:
            lines.append("")
            lines.append("OVERDUE FOLLOW-UPS:")
            for lead in overdue:
                lines.append(f"- {lead.name} ({lead.company or 'no company'})")

        waiting_r = await db.execute(
            select(ContentItem, Client)
            .join(Client, ContentItem.client_id == Client.id)
            .where(ContentItem.media_request_status == "requested")
            .limit(5)
        )
        waiting = list(waiting_r.all())
        if waiting:
            lines.append("")
            lines.append("CLIENTS WAITING MATERIALS:")
            for item, client in waiting:
                lines.append(f"- {client.company_name}")

        unpaid_r = await db.execute(
            select(CrmDocument, CrmLead)
            .join(CrmLead, CrmDocument.lead_id == CrmLead.id)
            .where(
                CrmDocument.document_type == "invoice",
                CrmDocument.status == "sent",
            )
            .limit(5)
        )
        unpaid = list(unpaid_r.all())
        if unpaid:
            lines.append("")
            lines.append("UNPAID INVOICES:")
            for doc, lead in unpaid:
                lines.append(f"- {lead.name}: {doc.title} ({doc.amount or 'TBD'} {doc.currency})")

        high_tasks_r = await db.execute(
            select(OperatorTask, Client)
            .join(Client, OperatorTask.client_id == Client.id)
            .where(
                OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
                OperatorTask.priority == "high",
            )
            .order_by(OperatorTask.due_at.nulls_last(), OperatorTask.created_at.desc())
            .limit(5)
        )
        high_tasks = list(high_tasks_r.all())
        if high_tasks:
            lines.append("")
            lines.append("HIGH PRIORITY TASKS:")
            for task, client in high_tasks:
                lines.append(f"- {task.title} ({client.company_name})")

        return "\n".join(lines)

    @staticmethod
    def _as_str_list(raw: Any, limit: int) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            text = str(item).strip()
            if text:
                out.append(text[:300])
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _heuristic_summary(overview: dict[str, Any]) -> dict[str, Any]:
        priorities: list[str] = []
        risks: list[str] = []
        opportunities: list[str] = []
        actions: list[str] = []

        if overview["inbox_new"] > 0:
            priorities.append(f"Review {overview['inbox_new']} new inbox item(s)")
            actions.append("Go to Inbox and triage new client materials")
        if overview["overdue_followups"] > 0:
            priorities.append(f"Follow up on {overview['overdue_followups']} overdue CRM lead(s)")
            actions.append("Open CRM and complete overdue follow-ups")
        if overview["clients_waiting_materials"] > 0:
            priorities.append(
                f"Request or collect materials from {overview['clients_waiting_materials']} client(s)",
            )
        if overview["invoices_unpaid"] > 0:
            priorities.append(f"Chase {overview['invoices_unpaid']} unpaid invoice(s)")
            risks.append(f"{overview['invoices_unpaid']} invoice(s) awaiting payment")
        if overview["tasks_open"] > 5:
            risks.append(f"{overview['tasks_open']} open tasks may need triage")

        for dr in (overview.get("deal_risks") or [])[:3]:
            risks.append(dr["title"])

        if overview["active_deals"] > 0:
            opportunities.append(
                f"Pipeline has {overview['active_deals']} active deal(s) "
                f"worth {overview['pipeline_value']} UZS",
            )
        if overview["content_ready"] > 0:
            opportunities.append(f"{overview['content_ready']} content item(s) ready to schedule")
        if overview["near_limit_clients"] > 0:
            risks.append(f"{overview['near_limit_clients']} client(s) near monthly post limit")

        if not priorities:
            priorities = ["Review inbox and CRM pipeline for today's work"]
        if not actions:
            actions = ["Check Inbox", "Review CRM deals", "Review Billing"]
        if not risks:
            risks = ["No critical risks flagged — stay on top of follow-ups"]
        if not opportunities:
            opportunities = ["Maintain content pipeline and nurture active deals"]

        summary = (
            f"Operations snapshot: {overview['inbox_new']} inbox, "
            f"{overview['tasks_open']} tasks, {overview['active_deals']} active deals. "
            f"MRR ${overview['mrr']:,.0f}, pipeline {overview['pipeline_value']} UZS."
        )

        return {
            "executive_summary": summary,
            "top_priorities": priorities[:5],
            "risks": risks[:5],
            "opportunities": opportunities[:5],
            "recommended_actions": actions[:5],
            "source": "fallback",
        }
