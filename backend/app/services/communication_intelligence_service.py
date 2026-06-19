"""Communication Intelligence v1 — heuristic conversation analysis (read-only, no auto-actions)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.communication import (
    CommunicationContact,
    CommunicationMessage,
    CommunicationThread,
)
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.deal_room import DealRoom
from app.models.proposal_document import ProposalDocument
from app.models.whatsapp import WhatsAppContact, WhatsAppMessage, WhatsAppThread

logger = logging.getLogger(__name__)

MARKER = "[Communication Intelligence]"

CLASSIFICATIONS = frozenset({"inquiry", "qualification", "negotiation", "proposal", "closing", "inactive"})
RECENT_DAYS = 7
STALE_DAYS = 14
INACTIVE_DAYS = 21

_PROPOSAL_RE = re.compile(
    r"proposal|quote|quotation|offer|предложени|коммерческ|报价|询价",
    re.I,
)
_PRICING_RE = re.compile(
    r"price|pricing|cost|discount|rate|moq|цена|стоимость|скидк|价格|单价",
    re.I,
)
_NEGOTIATION_RE = re.compile(
    r"negotiat|terms|counter|discount|deal|contract|переговор|услови|合同|条款",
    re.I,
)
_PURCHASE_RE = re.compile(
    r"buy|order|purchase|sample|ship|payment|заказ|купить|采购|下单|付款",
    re.I,
)
_PROPOSAL_REQUEST_RE = re.compile(
    r"send (?:me )?(?:a )?(?:proposal|quote)|need (?:a )?(?:quote|proposal)|"
    r"request (?:a )?quote|please quote|пришлите (?:коммерческ|предложени)|"
    r"需要报价|请报价",
    re.I,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _clamp_score(score: int) -> int:
    return max(0, min(100, int(score)))


def _days_since(ref: datetime | None, now: datetime) -> int | None:
    ref = _aware(ref)
    if ref is None:
        return None
    return (now - ref).days


def format_conversation_id(source: str, source_id: UUID) -> str:
    return f"{source}:{source_id}"


def parse_conversation_id(raw_id: str) -> tuple[str, UUID]:
    if ":" in raw_id:
        source, uid = raw_id.split(":", 1)
        if source not in ("thread", "whatsapp"):
            raise HTTPException(status_code=400, detail="Invalid conversation id prefix")
        try:
            return source, UUID(uid)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid conversation id") from exc
    try:
        return "thread", UUID(raw_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation id") from exc


class _MessageView:
    __slots__ = ("direction", "text", "created_at")

    def __init__(self, direction: str, text: str, created_at: datetime) -> None:
        self.direction = direction
        self.text = text or ""
        self.created_at = created_at


class CommunicationIntelligenceService:
    @staticmethod
    def _normalize_messages(
        messages: list[Any],
        *,
        source: str,
    ) -> list[_MessageView]:
        views: list[_MessageView] = []
        for msg in messages:
            if source == "whatsapp":
                direction = "inbound" if msg.direction == "incoming" else "outbound"
                if msg.status == "draft":
                    direction = "draft"
                views.append(_MessageView(direction, msg.content, msg.created_at))
            else:
                views.append(_MessageView(msg.direction, msg.message_text, msg.created_at))
        return views

    @staticmethod
    def _collect_message_signals(
        messages: list[_MessageView],
        *,
        now: datetime,
        lead_status: str | None = None,
        proposal_count: int = 0,
        proposal_sent: int = 0,
        thread_status: str = "open",
    ) -> dict[str, Any]:
        inbound = [m for m in messages if m.direction == "inbound"]
        outbound = [m for m in messages if m.direction == "outbound"]
        text_blob = " ".join(m.text for m in messages if m.text).lower()

        outbound_times = [_aware(m.created_at) for m in outbound]
        outbound_times = [t for t in outbound_times if t]
        last_out = max(outbound_times) if outbound_times else None

        unanswered = [
            m for m in inbound
            if last_out is None or (_aware(m.created_at) or now) > last_out
        ]

        touch_times = [_aware(m.created_at) for m in messages]
        touch_times = [t for t in touch_times if t]
        last_message_at = max(touch_times) if touch_times else None
        days_since = _days_since(last_message_at, now)

        week_ago = now - timedelta(days=RECENT_DAYS)
        recent_msgs = [m for m in messages if _aware(m.created_at) and _aware(m.created_at) >= week_ago]
        recent_inbound = sum(1 for m in recent_msgs if m.direction == "inbound")
        recent_outbound = sum(1 for m in recent_msgs if m.direction == "outbound")

        last_inbound_at = max(
            (_aware(m.created_at) for m in inbound if _aware(m.created_at)),
            default=None,
        )
        last_outbound_at = last_out

        return {
            "message_count": len(messages),
            "inbound_count": len(inbound),
            "outbound_count": len(outbound),
            "unanswered_count": len(unanswered),
            "unanswered": len(unanswered) > 0,
            "days_since_last": days_since,
            "last_message_at": last_message_at,
            "last_inbound_at": last_inbound_at,
            "last_outbound_at": last_outbound_at,
            "recent_message_count": len(recent_msgs),
            "recent_inbound": recent_inbound,
            "recent_outbound": recent_outbound,
            "text_blob": text_blob,
            "proposal_requested": bool(_PROPOSAL_REQUEST_RE.search(text_blob)),
            "pricing_discussion": bool(_PRICING_RE.search(text_blob)),
            "negotiation_signals": bool(_NEGOTIATION_RE.search(text_blob)),
            "purchase_intent": bool(_PURCHASE_RE.search(text_blob)),
            "proposal_keywords": bool(_PROPOSAL_RE.search(text_blob)),
            "lead_status": lead_status or "",
            "proposal_count": proposal_count,
            "proposal_sent": proposal_sent,
            "thread_status": thread_status,
        }

    @staticmethod
    def _detect_insights(signals: dict[str, Any]) -> list[str]:
        insights: list[str] = []
        days = signals.get("days_since_last")

        if days is not None and days <= RECENT_DAYS and signals["recent_inbound"] > 0:
            insights.append("active buyer")
        if days is not None and days >= INACTIVE_DAYS:
            insights.append("inactive buyer")
        if signals["purchase_intent"] and (
            signals["recent_inbound"] >= 2 or signals["health_precursor"] >= 65
        ):
            insights.append("hot buyer")
        if signals.get("proposal_requested"):
            insights.append("proposal requested")
        if signals.get("pricing_discussion"):
            insights.append("pricing discussion")
        if signals.get("negotiation_signals") or signals["lead_status"] == "negotiation":
            insights.append("negotiation stage")
        if signals.get("purchase_intent"):
            insights.append("purchase intent")
        if signals.get("unanswered"):
            insights.append("unanswered conversation")
        if signals.get("follow_up_required"):
            insights.append("follow-up required")
        return insights[:10]

    @staticmethod
    def _compute_health_score(signals: dict[str, Any]) -> tuple[int, list[str]]:
        score = 0
        factors: list[str] = []

        # Response activity (max 25)
        if signals["recent_outbound"] > 0 and signals["unanswered_count"] == 0:
            score += 25
            factors.append("operator responded recently")
        elif signals["recent_outbound"] > 0:
            score += 18
            factors.append("recent operator activity")
        elif signals["outbound_count"] > 0:
            score += 10
        elif signals["inbound_count"] > 0:
            score += 4

        # Conversation frequency (max 20)
        freq = signals["recent_message_count"]
        if freq >= 8:
            score += 20
            factors.append("high conversation frequency")
        elif freq >= 4:
            score += 14
        elif freq >= 2:
            score += 8
        elif freq >= 1:
            score += 4

        # Proposal engagement (max 20)
        if signals["proposal_sent"] > 0:
            score += 20
            factors.append("proposal engagement")
        elif signals["proposal_count"] > 0:
            score += 12
        elif signals.get("proposal_requested"):
            score += 10
            factors.append("buyer requested proposal")

        # Operator engagement (max 20)
        if signals["outbound_count"] >= 3 and signals["inbound_count"] >= 2:
            score += 20
            factors.append("two-way operator engagement")
        elif signals["outbound_count"] >= 1:
            score += 12
        elif signals["inbound_count"] > 0 and signals["outbound_count"] == 0:
            score += 2

        # Recent interactions (max 15)
        days = signals.get("days_since_last")
        if days is not None:
            if days <= 2:
                score += 15
                factors.append("very recent interaction")
            elif days <= RECENT_DAYS:
                score += 10
            elif days <= STALE_DAYS:
                score += 5

        if signals["unanswered_count"] > 0:
            penalty = min(20, 8 + signals["unanswered_count"] * 3)
            score -= penalty
            factors.append("unanswered inbound messages")

        if days is not None and days >= INACTIVE_DAYS:
            score -= 15

        if signals["thread_status"] in ("closed", "archived"):
            score -= 10

        return _clamp_score(score), factors[:8]

    @staticmethod
    def _classification_from_signals(signals: dict[str, Any], health: int) -> str:
        days = signals.get("days_since_last")
        status = signals.get("lead_status") or ""

        if days is not None and days >= INACTIVE_DAYS and health < 35:
            return "inactive"
        if signals.get("thread_status") in ("closed", "archived") and health < 40:
            return "inactive"

        if signals.get("purchase_intent") and (
            signals.get("negotiation_signals") or status == "negotiation"
        ):
            return "closing"
        if signals.get("negotiation_signals") or status == "negotiation":
            return "negotiation"
        if (
            signals.get("proposal_keywords")
            or signals.get("proposal_requested")
            or status in ("proposal_sent",)
            or signals["proposal_sent"] > 0
        ):
            return "proposal"
        if signals["inbound_count"] >= 2 and signals["outbound_count"] >= 1:
            return "qualification"
        if signals["message_count"] <= 2 and not signals.get("purchase_intent"):
            return "inquiry"
        if health < 30 and days is not None and days >= STALE_DAYS:
            return "inactive"
        return "qualification"

    @staticmethod
    def _urgency_from_signals(
        signals: dict[str, Any],
        health: int,
        classification: str,
        insights: list[str],
    ) -> str:
        if signals.get("unanswered") and ("hot buyer" in insights or health >= 70):
            return "urgent"
        if signals.get("unanswered") or "follow-up required" in insights:
            return "high" if signals["unanswered_count"] > 1 else "high"
        if "hot buyer" in insights or classification in ("closing", "negotiation"):
            return "high"
        if classification == "proposal" and signals.get("proposal_requested"):
            return "high"
        if classification == "inactive":
            return "low"
        if health >= 60:
            return "medium"
        return "low"

    @staticmethod
    def _recommended_actions(
        classification: str,
        signals: dict[str, Any],
        insights: list[str],
        urgency: str,
    ) -> list[str]:
        actions: list[str] = []

        if signals.get("unanswered"):
            actions.append("Reply manually — draft a response for operator review (no auto-send).")
        if "proposal requested" in insights and signals["proposal_sent"] == 0:
            actions.append("Prepare commercial proposal draft for manual review and send.")
        if "pricing discussion" in insights:
            actions.append("Review pricing with sales team before responding manually.")
        if classification == "negotiation" or "negotiation stage" in insights:
            actions.append("Log negotiation notes in CRM after each manual touchpoint.")
        if "purchase intent" in insights:
            actions.append("Confirm order details manually and update deal room stage if appropriate.")
        if "inactive buyer" in insights:
            actions.append("Plan a one-time re-engagement message — operator sends when ready.")
        if "follow-up required" in insights and not signals.get("unanswered"):
            actions.append("Schedule follow-up task or set CRM next follow-up date manually.")
        if classification == "inquiry":
            actions.append("Qualify buyer needs through manual conversation — no automated outreach.")
        if not actions:
            actions.append("Monitor conversation and log CRM activity after manual interactions.")

        if urgency == "urgent":
            actions.insert(0, "Priority review — conversation needs immediate operator attention.")

        return actions[:6]

    @staticmethod
    def analyze_signals(signals: dict[str, Any]) -> dict[str, Any]:
        """Pure heuristic analysis from pre-collected message signals."""
        health, factors = CommunicationIntelligenceService._compute_health_score(signals)
        signals = {**signals, "health_precursor": health}
        classification = CommunicationIntelligenceService._classification_from_signals(signals, health)

        follow_up = (
            signals.get("unanswered")
            or (signals.get("days_since_last") is not None and signals["days_since_last"] >= STALE_DAYS
                and signals["thread_status"] in ("open", "waiting"))
            or (signals.get("days_since_last") is not None and signals["days_since_last"] >= RECENT_DAYS
                and signals["recent_outbound"] == 0 and signals["inbound_count"] > 0)
        )
        signals = {**signals, "follow_up_required": follow_up}

        insights = CommunicationIntelligenceService._detect_insights(signals)
        for factor in factors[:3]:
            if factor not in insights:
                insights.append(factor)

        urgency = CommunicationIntelligenceService._urgency_from_signals(
            signals, health, classification, insights,
        )
        actions = CommunicationIntelligenceService._recommended_actions(
            classification, signals, insights, urgency,
        )

        return {
            "health_score": health,
            "classification": classification if classification in CLASSIFICATIONS else "inquiry",
            "urgency": urgency,
            "insights": insights,
            "recommended_actions": actions,
        }

    @staticmethod
    async def _proposal_stats(db: AsyncSession, lead_id: UUID | None) -> tuple[int, int]:
        if not lead_id:
            return 0, 0
        r = await db.execute(
            select(
                func.count(ProposalDocument.id),
                func.coalesce(func.sum(case(
                    (ProposalDocument.status.in_(("sent", "accepted", "reviewed")), 1),
                    else_=0,
                )), 0),
            ).where(ProposalDocument.lead_id == lead_id),
        )
        total, sent = r.one()
        return int(total or 0), int(sent or 0)

    @staticmethod
    async def _analyze_thread(
        db: AsyncSession,
        thread: CommunicationThread,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or _now()
        contact = thread.contact
        lead_status = None
        if thread.lead_id:
            lr = await db.execute(select(CrmLead.status).where(CrmLead.id == thread.lead_id))
            lead_status = lr.scalar_one_or_none()

        prop_total, prop_sent = await CommunicationIntelligenceService._proposal_stats(
            db, thread.lead_id,
        )
        messages = CommunicationIntelligenceService._normalize_messages(
            list(thread.messages or []), source="thread",
        )
        signals = CommunicationIntelligenceService._collect_message_signals(
            messages,
            now=now,
            lead_status=lead_status,
            proposal_count=prop_total,
            proposal_sent=prop_sent,
            thread_status=thread.status or "open",
        )
        intelligence = CommunicationIntelligenceService.analyze_signals(signals)

        contact_name = contact.name if contact else thread.title
        channel = thread.channel or "manual"
        conv_id = format_conversation_id("thread", thread.id)

        return {
            "conversation_id": conv_id,
            "source": "thread",
            "source_id": thread.id,
            "contact_name": contact_name,
            "channel": channel,
            "status": thread.status or "open",
            "intelligence": intelligence,
            "last_message_at": signals["last_message_at"] or thread.last_message_at,
            "message_count": signals["message_count"],
            "lead_id": thread.lead_id,
            "deal_id": thread.deal_id,
            "client_id": thread.client_id,
            "_signals": signals,
        }

    @staticmethod
    async def _analyze_whatsapp(
        db: AsyncSession,
        wa_thread: WhatsAppThread,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or _now()
        contact = wa_thread.contact
        messages = CommunicationIntelligenceService._normalize_messages(
            list(wa_thread.messages or []), source="whatsapp",
        )
        signals = CommunicationIntelligenceService._collect_message_signals(
            messages,
            now=now,
            thread_status="open",
        )
        intelligence = CommunicationIntelligenceService.analyze_signals(signals)
        contact_name = contact.display_name if contact else "WhatsApp contact"

        return {
            "conversation_id": format_conversation_id("whatsapp", wa_thread.id),
            "source": "whatsapp",
            "source_id": wa_thread.id,
            "contact_name": contact_name,
            "channel": "whatsapp",
            "status": "open",
            "intelligence": intelligence,
            "last_message_at": signals["last_message_at"] or wa_thread.last_message_at,
            "message_count": signals["message_count"],
            "lead_id": None,
            "deal_id": None,
            "client_id": contact.crm_client_id if contact else None,
            "_signals": signals,
        }

    @staticmethod
    async def _load_thread(db: AsyncSession, thread_id: UUID) -> CommunicationThread:
        r = await db.execute(
            select(CommunicationThread)
            .options(
                selectinload(CommunicationThread.messages),
                selectinload(CommunicationThread.contact),
            )
            .where(CommunicationThread.id == thread_id),
        )
        thread = r.scalar_one_or_none()
        if not thread:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return thread

    @staticmethod
    async def _load_whatsapp(db: AsyncSession, thread_id: UUID) -> WhatsAppThread:
        r = await db.execute(
            select(WhatsAppThread)
            .options(
                selectinload(WhatsAppThread.messages),
                selectinload(WhatsAppThread.contact),
            )
            .where(WhatsAppThread.id == thread_id),
        )
        thread = r.scalar_one_or_none()
        if not thread:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return thread

    @staticmethod
    async def analyze_conversation(
        db: AsyncSession,
        raw_id: str,
    ) -> dict[str, Any]:
        source, source_id = parse_conversation_id(raw_id)
        if source == "thread":
            thread = await CommunicationIntelligenceService._load_thread(db, source_id)
            item = await CommunicationIntelligenceService._analyze_thread(db, thread)
        else:
            wa = await CommunicationIntelligenceService._load_whatsapp(db, source_id)
            item = await CommunicationIntelligenceService._analyze_whatsapp(db, wa)
        detail = await CommunicationIntelligenceService._enrich_detail(db, item)
        detail.pop("_signals", None)
        return detail

    @staticmethod
    async def _enrich_detail(db: AsyncSession, item: dict[str, Any]) -> dict[str, Any]:
        lead_id = item.get("lead_id")
        deal_id = item.get("deal_id")
        client_id = item.get("client_id")

        linked_crm: dict[str, Any] = {
            "lead_id": lead_id,
            "lead_name": None,
            "lead_status": None,
            "deal_id": deal_id,
            "deal_title": None,
            "client_id": client_id,
        }
        if lead_id:
            lr = await db.execute(
                select(CrmLead.name, CrmLead.status).where(CrmLead.id == lead_id),
            )
            row = lr.one_or_none()
            if row:
                linked_crm["lead_name"] = row[0]
                linked_crm["lead_status"] = row[1]

        if deal_id:
            dr = await db.execute(select(CrmDeal.title).where(CrmDeal.id == deal_id))
            linked_crm["deal_title"] = dr.scalar_one_or_none()

        linked_deal_room = None
        if client_id:
            rr = await db.execute(
                select(DealRoom.id, DealRoom.deal_name)
                .where(DealRoom.crm_client_id == client_id, DealRoom.status == "active")
                .order_by(DealRoom.updated_at.desc())
                .limit(1),
            )
            row = rr.one_or_none()
            if row:
                linked_deal_room = {"deal_room_id": row[0], "deal_name": row[1]}

        proposals: list[dict[str, Any]] = []
        if lead_id:
            pr = await db.execute(
                select(ProposalDocument)
                .where(ProposalDocument.lead_id == lead_id)
                .order_by(ProposalDocument.updated_at.desc())
                .limit(10),
            )
            for prop in pr.scalars().all():
                proposals.append({
                    "proposal_id": prop.id,
                    "title": prop.title,
                    "status": prop.status,
                    "updated_at": prop.updated_at,
                })

        intelligence = item.pop("intelligence", {})
        result = {
            **item,
            "intelligence": intelligence,
            "linked_crm": linked_crm,
            "linked_deal_room": linked_deal_room,
            "linked_proposals": proposals,
        }
        return result

    @staticmethod
    async def _iter_conversations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        now = _now()
        items: list[dict[str, Any]] = []

        tq = (
            select(CommunicationThread)
            .options(
                selectinload(CommunicationThread.messages),
                selectinload(CommunicationThread.contact),
            )
            .order_by(CommunicationThread.last_message_at.desc().nullslast())
        )
        if client_id:
            tq = tq.where(CommunicationThread.client_id == client_id)
        threads = (await db.execute(tq)).scalars().all()
        for thread in threads:
            try:
                items.append(await CommunicationIntelligenceService._analyze_thread(db, thread, now=now))
            except Exception as exc:
                logger.info("%s thread skip: %s err=%s", MARKER, thread.id, exc)

        wq = (
            select(WhatsAppThread)
            .options(
                selectinload(WhatsAppThread.messages),
                selectinload(WhatsAppThread.contact),
            )
            .join(WhatsAppContact, WhatsAppThread.contact_id == WhatsAppContact.id)
            .order_by(WhatsAppThread.last_message_at.desc().nullslast())
        )
        if client_id:
            wq = wq.where(WhatsAppContact.crm_client_id == client_id)
        wa_threads = (await db.execute(wq)).scalars().all()
        for wa in wa_threads:
            try:
                items.append(await CommunicationIntelligenceService._analyze_whatsapp(db, wa, now=now))
            except Exception as exc:
                logger.info("%s whatsapp skip: %s err=%s", MARKER, wa.id, exc)

        return items

    @staticmethod
    def _overview_counts(items: list[dict[str, Any]]) -> dict[str, int]:
        counts = {
            "active_buyers": 0,
            "hot_buyers": 0,
            "negotiations": 0,
            "follow_ups_required": 0,
            "inactive_conversations": 0,
        }
        for item in items:
            intel = item.get("intelligence") or {}
            insights = intel.get("insights") or []
            classification = intel.get("classification") or ""
            if "active buyer" in insights:
                counts["active_buyers"] += 1
            if "hot buyer" in insights:
                counts["hot_buyers"] += 1
            if classification == "negotiation" or "negotiation stage" in insights:
                counts["negotiations"] += 1
            if "follow-up required" in insights or "unanswered conversation" in insights:
                counts["follow_ups_required"] += 1
            if classification == "inactive" or "inactive buyer" in insights:
                counts["inactive_conversations"] += 1
        return counts

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []

        async def _run() -> dict[str, Any]:
            items = await CommunicationIntelligenceService._iter_conversations(
                db, client_id=client_id,
            )
            counts = CommunicationIntelligenceService._overview_counts(items)
            return {
                **counts,
                "total_analyzed": len(items),
            }

        result = await safe_section(
            "communication_intelligence_overview",
            _run(),
            default={
                "active_buyers": 0,
                "hot_buyers": 0,
                "negotiations": 0,
                "follow_ups_required": 0,
                "inactive_conversations": 0,
                "total_analyzed": 0,
            },
            errors=errors,
            db=db,
        )
        result["errors"] = errors
        return result

    @staticmethod
    async def list_conversations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        channel: str | None = None,
        classification: str | None = None,
        urgency: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        items = await CommunicationIntelligenceService._iter_conversations(db, client_id=client_id)

        if channel:
            items = [i for i in items if (i.get("channel") or "").lower() == channel.lower()]
        if classification and classification in CLASSIFICATIONS:
            items = [
                i for i in items
                if (i.get("intelligence") or {}).get("classification") == classification
            ]
        if urgency:
            items = [
                i for i in items
                if (i.get("intelligence") or {}).get("urgency") == urgency
            ]

        total = len(items)
        page = items[skip: skip + limit]

        list_items: list[dict[str, Any]] = []
        for item in page:
            intel = item.get("intelligence") or {}
            actions = intel.get("recommended_actions") or []
            list_items.append({
                "conversation_id": item["conversation_id"],
                "source": item["source"],
                "source_id": item["source_id"],
                "contact_name": item["contact_name"],
                "channel": item["channel"],
                "health_score": intel.get("health_score", 0),
                "classification": intel.get("classification", "inquiry"),
                "urgency": intel.get("urgency", "medium"),
                "recommended_action": actions[0] if actions else "",
                "last_message_at": item.get("last_message_at"),
                "lead_id": item.get("lead_id"),
                "deal_id": item.get("deal_id"),
                "client_id": item.get("client_id"),
                "status": item.get("status", "open"),
            })

        return {"items": list_items, "total": total}

    @staticmethod
    async def recalculate(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        limit = min(max(1, limit), 500)
        items = await CommunicationIntelligenceService._iter_conversations(db, client_id=client_id)
        analyzed = min(len(items), limit)
        overview = await CommunicationIntelligenceService.overview(db, client_id=client_id)
        logger.info("%s recalculate client=%s analyzed=%s", MARKER, client_id, analyzed)
        return {
            "analyzed": analyzed,
            "overview": overview,
            "message": "Communication intelligence recalculated — no messages sent or CRM changes made.",
        }

    @staticmethod
    async def analyze_batch(
        db: AsyncSession,
        *,
        conversation_ids: list[str] | None = None,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        details: list[dict[str, Any]] = []
        if conversation_ids:
            for raw_id in conversation_ids[:100]:
                try:
                    details.append(await CommunicationIntelligenceService.analyze_conversation(db, raw_id))
                except HTTPException:
                    raise
                except Exception as exc:
                    logger.info("%s analyze skip: %s err=%s", MARKER, raw_id, exc)
        else:
            items = await CommunicationIntelligenceService._iter_conversations(db, client_id=client_id)
            for item in items[:100]:
                enriched = await CommunicationIntelligenceService._enrich_detail(db, dict(item))
                enriched.pop("_signals", None)
                details.append(enriched)

        return {"items": details, "analyzed": len(details)}

    @staticmethod
    async def get_lead_communication_score(
        db: AsyncSession,
        lead_id: UUID,
    ) -> dict[str, Any] | None:
        """Best conversation health score for a lead — used by Lead Intelligence."""
        r = await db.execute(
            select(CommunicationThread)
            .options(selectinload(CommunicationThread.messages), selectinload(CommunicationThread.contact))
            .where(CommunicationThread.lead_id == lead_id),
        )
        threads = list(r.scalars().all())
        if not threads:
            return None

        best: dict[str, Any] | None = None
        for thread in threads:
            item = await CommunicationIntelligenceService._analyze_thread(db, thread)
            intel = item.get("intelligence") or {}
            score = intel.get("health_score", 0)
            if best is None or score > best.get("health_score", 0):
                best = {
                    "health_score": score,
                    "classification": intel.get("classification"),
                    "urgency": intel.get("urgency"),
                    "insights": intel.get("insights") or [],
                    "conversation_id": item["conversation_id"],
                }
        return best

    @staticmethod
    async def communication_risks_and_opportunities(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 15,
    ) -> dict[str, Any]:
        """Summaries for Sales Manager and Executive Copilot."""
        items = await CommunicationIntelligenceService._iter_conversations(db, client_id=client_id)
        risks: list[dict[str, Any]] = []
        opportunities: list[dict[str, Any]] = []

        for item in items:
            intel = item.get("intelligence") or {}
            insights = intel.get("insights") or []
            conv_id = item["conversation_id"]
            name = item.get("contact_name") or "Contact"

            if "unanswered conversation" in insights:
                risks.append({
                    "type": "unanswered_conversation",
                    "severity": "high" if intel.get("urgency") == "urgent" else "medium",
                    "issue": f"Unanswered conversation: {name}",
                    "recommendation": "Reply manually — no auto-send",
                    "source": "communication_intelligence",
                    "conversation_id": conv_id,
                    "lead_id": item.get("lead_id"),
                    "health_score": intel.get("health_score"),
                    "classification": intel.get("classification"),
                })
            elif intel.get("classification") == "inactive":
                risks.append({
                    "type": "inactive_conversation",
                    "severity": "medium",
                    "issue": f"Inactive conversation: {name}",
                    "recommendation": "Review for re-engagement or archive manually",
                    "source": "communication_intelligence",
                    "conversation_id": conv_id,
                    "lead_id": item.get("lead_id"),
                    "health_score": intel.get("health_score"),
                    "classification": intel.get("classification"),
                })

            if "hot buyer" in insights or intel.get("classification") == "closing":
                opportunities.append({
                    "type": "hot_buyer_conversation",
                    "priority": intel.get("urgency") or "high",
                    "title": f"Hot buyer conversation: {name}",
                    "action": (intel.get("recommended_actions") or ["Review manually"])[0],
                    "summary": f"Health {intel.get('health_score')}/100, {intel.get('classification')}",
                    "source": "communication_intelligence",
                    "conversation_id": conv_id,
                    "lead_id": item.get("lead_id"),
                    "health_score": intel.get("health_score"),
                    "classification": intel.get("classification"),
                })
            elif "proposal requested" in insights:
                opportunities.append({
                    "type": "proposal_requested_conversation",
                    "priority": "high",
                    "title": f"Proposal requested: {name}",
                    "action": "Prepare proposal draft for manual review",
                    "summary": "Buyer requested proposal in conversation",
                    "source": "communication_intelligence",
                    "conversation_id": conv_id,
                    "lead_id": item.get("lead_id"),
                    "health_score": intel.get("health_score"),
                    "classification": intel.get("classification"),
                })

        return {
            "risks": risks[:limit],
            "opportunities": opportunities[:limit],
            "follow_ups_required": sum(
                1 for i in items
                if "follow-up required" in (i.get("intelligence") or {}).get("insights", [])
                or "unanswered conversation" in (i.get("intelligence") or {}).get("insights", [])
            ),
            "avg_health_score": (
                sum((i.get("intelligence") or {}).get("health_score", 0) for i in items) // len(items)
                if items else 0
            ),
        }
