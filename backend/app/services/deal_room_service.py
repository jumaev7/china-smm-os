"""AI Deal Room v1 — central workspace aggregating CRM, inbox, proposals, tasks, AI recommendations."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.client import Client
from app.models.communication import CommunicationThread
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.deal_room import DealRoom
from app.models.operator_task import OperatorTask
from app.models.proposal_document import ProposalDocument
from app.models.sales_assistant_recommendation import SalesAssistantRecommendation
from app.models.whatsapp import WhatsAppContact, WhatsAppThread
from app.schemas.deal_room import DealRoomCreateRequest, DealRoomUpdateStageRequest
from app.services.client_service import ClientService
from app.services.communication_intelligence_service import CommunicationIntelligenceService
from app.services.deal_event_service import DEFAULT_PROBABILITY
from app.services.executive_copilot_service import ExecutiveCopilotService
from app.services.buyer_intelligence_service import BuyerIntelligenceService
from app.services.deal_risk_service import DealRiskService
from app.services.revenue_attribution_service import RevenueAttributionService

logger = logging.getLogger(__name__)

MARKER = "[Deal Room]"

DEAL_ROOM_STAGES = frozenset({
    "new", "qualification", "proposal", "negotiation", "contract", "closing", "won", "lost",
})
DEAL_ROOM_STATUSES = frozenset({"active", "on_hold", "closed"})

_STAGE_DEFAULT_PROBABILITY: dict[str, int] = {
    "new": 10,
    "qualification": 20,
    "proposal": 35,
    "negotiation": 50,
    "contract": 65,
    "closing": 80,
    "won": 100,
    "lost": 0,
    **DEFAULT_PROBABILITY,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def _serialize_room(room: DealRoom) -> dict[str, Any]:
    return {
        "id": room.id,
        "crm_client_id": room.crm_client_id,
        "client_name": room.client.company_name if room.client else None,
        "deal_name": room.deal_name,
        "stage": room.stage,
        "status": room.status,
        "probability": room.probability,
        "expected_value": room.expected_value,
        "created_at": room.created_at,
        "updated_at": room.updated_at,
    }


def _days_since(dt: datetime | None) -> int:
    if not dt:
        return 999
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (_utc_now() - dt).days


class DealRoomService:
    @staticmethod
    async def list_rooms(
        db: AsyncSession,
        *,
        crm_client_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        query = (
            select(DealRoom)
            .options(selectinload(DealRoom.client))
            .order_by(DealRoom.updated_at.desc())
        )
        if crm_client_id:
            query = query.where(DealRoom.crm_client_id == crm_client_id)
        if status:
            query = query.where(DealRoom.status == status)

        count_q = select(func.count()).select_from(DealRoom)
        if crm_client_id:
            count_q = count_q.where(DealRoom.crm_client_id == crm_client_id)
        if status:
            count_q = count_q.where(DealRoom.status == status)
        total = (await db.execute(count_q)).scalar_one()

        result = await db.execute(query.offset(skip).limit(limit))
        items = [_serialize_room(r) for r in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def create_room(db: AsyncSession, data: DealRoomCreateRequest) -> dict[str, Any]:
        await ClientService.get(db, data.crm_client_id)

        stage = data.stage or "new"
        if stage not in DEAL_ROOM_STAGES:
            raise HTTPException(status_code=400, detail="Invalid deal room stage")
        status = data.status or "active"
        if status not in DEAL_ROOM_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid deal room status")

        deal_name = data.deal_name.strip()
        if not deal_name:
            raise HTTPException(status_code=400, detail="deal_name is required")

        if data.crm_lead_id:
            lead = await DealRoomService._load_lead(db, data.crm_lead_id)
            if lead.client_id != data.crm_client_id:
                raise HTTPException(status_code=400, detail="Lead does not belong to client")

        probability = _STAGE_DEFAULT_PROBABILITY.get(stage, 10)
        expected_value = data.expected_value
        if expected_value is None and data.crm_lead_id:
            lead = await DealRoomService._load_lead(db, data.crm_lead_id)
            expected_value = lead.estimated_value

        room = DealRoom(
            crm_client_id=data.crm_client_id,
            deal_name=deal_name,
            stage=stage,
            status=status,
            probability=probability,
            expected_value=expected_value,
        )
        db.add(room)
        await db.commit()
        await db.refresh(room, attribute_names=["client"])
        logger.info("%s created room=%s name=%s", MARKER, room.id, room.deal_name)
        return _serialize_room(room)

    @staticmethod
    async def update_stage(db: AsyncSession, data: DealRoomUpdateStageRequest) -> dict[str, Any]:
        room = await DealRoomService._load_room(db, data.deal_room_id)
        stage = data.stage
        if stage not in DEAL_ROOM_STAGES:
            raise HTTPException(status_code=400, detail="Invalid deal room stage")

        room.stage = stage
        if data.probability is not None:
            room.probability = _clamp(data.probability)
        else:
            room.probability = _STAGE_DEFAULT_PROBABILITY.get(stage, room.probability)
        room.updated_at = _utc_now()
        await db.commit()
        await db.refresh(room, attribute_names=["client"])
        logger.info("%s stage updated room=%s stage=%s", MARKER, room.id, stage)
        return _serialize_room(room)

    @staticmethod
    async def get_detail(db: AsyncSession, room_id: UUID) -> dict[str, Any]:
        room = await DealRoomService._load_room(db, room_id)
        lead = await DealRoomService._find_lead(db, room)
        errors: list[str] = []

        client_data = await safe_section(
            "client",
            DealRoomService._build_client(db, room, lead),
            default={},
            errors=errors,
        )
        conversations = await safe_section(
            "conversations",
            DealRoomService._load_conversations(db, room, lead),
            default=[],
            errors=errors,
        )
        proposals = await safe_section(
            "proposals",
            DealRoomService._load_proposals(db, room, lead),
            default=[],
            errors=errors,
        )
        tasks = await safe_section(
            "tasks",
            DealRoomService._load_tasks(db, room, lead),
            default=[],
            errors=errors,
        )
        sales_recs = await safe_section(
            "sales_assistant_recommendations",
            DealRoomService._load_sales_recommendations(db, room, lead),
            default=[],
            errors=errors,
        )
        exec_recs = await safe_section(
            "executive_copilot_recommendations",
            DealRoomService._load_executive_recommendations(db, room),
            default=[],
            errors=errors,
        )
        communication_analysis = await safe_section(
            "communication_analysis",
            DealRoomService._load_communication_analysis(db, conversations or []),
            default=[],
            errors=errors,
        )
        recommendations = (sales_recs or []) + (exec_recs or [])

        signals = DealRoomService._collect_signals(
            lead=lead,
            conversations=conversations or [],
            proposals=proposals or [],
            tasks=tasks or [],
        )
        probability = DealRoomService._compute_probability(room, lead, signals)
        risks = DealRoomService._detect_risks(room, lead, signals, tasks or [])

        revenue_attribution = await safe_section(
            "revenue_attribution",
            RevenueAttributionService.deal_room_attribution(db, lead),
            default=None,
            errors=errors,
        )

        buyer_intelligence = None
        if lead:
            buyer_intelligence = await safe_section(
                "buyer_intelligence",
                BuyerIntelligenceService.evaluate_buyer(db, lead),
                default=None,
                errors=errors,
            )

        deal_risk = None
        crm_deal = await safe_section(
            "crm_deal_for_risk",
            DealRoomService._find_crm_deal(db, room, lead),
            default=None,
            errors=errors,
        )
        if crm_deal:
            deal_risk = await safe_section(
                "deal_risk",
                DealRiskService.evaluate_deal(db, crm_deal),
                default=None,
                errors=errors,
            )
        elif lead:
            deal_risk = await safe_section(
                "deal_risk_lead_proxy",
                DealRoomService._evaluate_lead_deal_risk(db, lead),
                default=None,
                errors=errors,
            )

        return {
            "id": room.id,
            "crm_client_id": room.crm_client_id,
            "deal_name": room.deal_name,
            "stage": room.stage,
            "status": room.status,
            "expected_value": room.expected_value,
            "created_at": room.created_at,
            "updated_at": room.updated_at,
            "client": client_data,
            "conversations": conversations or [],
            "proposals": proposals or [],
            "tasks": tasks or [],
            "recommendations": recommendations,
            "communication_analysis": communication_analysis or [],
            "risks": risks,
            "probability": probability,
            "revenue_attribution": revenue_attribution,
            "buyer_intelligence": buyer_intelligence,
            "deal_risk": deal_risk,
            "errors": errors,
        }

    @staticmethod
    async def _load_room(db: AsyncSession, room_id: UUID) -> DealRoom:
        result = await db.execute(
            select(DealRoom)
            .options(selectinload(DealRoom.client))
            .where(DealRoom.id == room_id),
        )
        room = result.scalar_one_or_none()
        if not room:
            raise HTTPException(status_code=404, detail="Deal room not found")
        return room

    @staticmethod
    async def _load_lead(db: AsyncSession, lead_id: UUID) -> CrmLead:
        result = await db.execute(select(CrmLead).where(CrmLead.id == lead_id))
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        return lead

    @staticmethod
    async def _find_lead(db: AsyncSession, room: DealRoom) -> CrmLead | None:
        result = await db.execute(
            select(CrmLead)
            .where(
                CrmLead.client_id == room.crm_client_id,
                or_(
                    CrmLead.name.ilike(room.deal_name),
                    CrmLead.company.ilike(room.deal_name),
                ),
            )
            .order_by(CrmLead.updated_at.desc())
            .limit(1),
        )
        lead = result.scalar_one_or_none()
        if lead:
            return lead
        result = await db.execute(
            select(CrmLead)
            .where(CrmLead.client_id == room.crm_client_id)
            .order_by(CrmLead.updated_at.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _build_client(
        db: AsyncSession,
        room: DealRoom,
        lead: CrmLead | None,
    ) -> dict[str, Any]:
        client = room.client
        if not client:
            cr = await db.execute(select(Client).where(Client.id == room.crm_client_id))
            client = cr.scalar_one_or_none()
        if not client:
            return {}

        lead_intel: dict[str, Any] | None = None
        if lead:
            lead_intel = {
                "lead_id": lead.id,
                "lead_name": lead.name,
                "lead_score": lead.lead_score,
                "qualification_level": lead.qualification_level,
                "status": lead.status,
                "priority": lead.priority,
                "ai_summary": lead.ai_summary,
                "recommended_action": lead.recommended_action,
                "estimated_value": lead.estimated_value,
            }

        return {
            "id": client.id,
            "company_name": client.company_name,
            "contact_name": lead.name if lead else None,
            "email": lead.email if lead else None,
            "phone": lead.phone if lead else None,
            "lead_intelligence": lead_intel,
        }

    @staticmethod
    async def _load_conversations(
        db: AsyncSession,
        room: DealRoom,
        lead: CrmLead | None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        thread_q = select(CommunicationThread).order_by(
            CommunicationThread.last_message_at.desc().nullslast(),
        )
        if lead:
            thread_q = thread_q.where(
                or_(
                    CommunicationThread.lead_id == lead.id,
                    CommunicationThread.client_id == room.crm_client_id,
                ),
            )
        else:
            thread_q = thread_q.where(CommunicationThread.client_id == room.crm_client_id)
        thread_q = thread_q.limit(20)
        threads = (await db.execute(thread_q)).scalars().all()
        for t in threads:
            channel = t.channel or "communication"
            if channel in ("wechat", "wecom"):
                items.append({
                    "id": str(t.id),
                    "channel": "wechat",
                    "title": t.title,
                    "status": t.status,
                    "last_message_at": t.last_message_at,
                    "lead_id": t.lead_id,
                    "unread_count": 0,
                })

        wa_q = (
            select(WhatsAppThread)
            .join(WhatsAppContact, WhatsAppThread.contact_id == WhatsAppContact.id)
            .options(selectinload(WhatsAppThread.contact))
            .where(WhatsAppContact.crm_client_id == room.crm_client_id)
            .order_by(WhatsAppThread.last_message_at.desc().nullslast())
            .limit(10)
        )
        wa_threads = (await db.execute(wa_q)).scalars().all()
        for wt in wa_threads:
            items.append({
                "id": str(wt.id),
                "channel": "whatsapp",
                "title": wt.contact.display_name if wt.contact else "WhatsApp",
                "status": "open",
                "last_message_at": wt.last_message_at,
                "lead_id": lead.id if lead else None,
                "unread_count": wt.unread_count or 0,
            })

        seen = set()
        deduped: list[dict[str, Any]] = []
        for item in items:
            key = (item["channel"], item["id"])
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped[:25]

    @staticmethod
    async def _load_communication_analysis(
        db: AsyncSession,
        conversations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for conv in conversations[:10]:
            channel = conv.get("channel") or "communication"
            conv_id = conv.get("id")
            if not conv_id:
                continue
            raw_id = f"thread:{conv_id}" if channel != "whatsapp" else f"whatsapp:{conv_id}"
            try:
                detail = await CommunicationIntelligenceService.analyze_conversation(db, raw_id)
                intel = detail.get("intelligence") or {}
                items.append({
                    "conversation_id": detail.get("conversation_id"),
                    "channel": channel,
                    "title": conv.get("title"),
                    "health_score": intel.get("health_score"),
                    "classification": intel.get("classification"),
                    "urgency": intel.get("urgency"),
                    "insights": intel.get("insights") or [],
                    "recommended_actions": intel.get("recommended_actions") or [],
                })
            except Exception as exc:
                logger.debug("%s comm analysis skip %s: %s", MARKER, raw_id, exc)
        return items

    @staticmethod
    async def _load_proposals(
        db: AsyncSession,
        room: DealRoom,
        lead: CrmLead | None,
    ) -> list[dict[str, Any]]:
        q = select(ProposalDocument).order_by(ProposalDocument.updated_at.desc())
        if lead:
            q = q.where(
                or_(
                    ProposalDocument.lead_id == lead.id,
                    ProposalDocument.client_id == room.crm_client_id,
                ),
            )
        else:
            q = q.where(ProposalDocument.client_id == room.crm_client_id)
        q = q.limit(15)
        docs = (await db.execute(q)).scalars().all()
        return [
            {
                "id": d.id,
                "title": d.title,
                "status": d.status,
                "language": d.language,
                "sent_at": d.sent_at,
                "created_at": d.created_at,
            }
            for d in docs
        ]

    @staticmethod
    async def _load_tasks(
        db: AsyncSession,
        room: DealRoom,
        lead: CrmLead | None,
    ) -> list[dict[str, Any]]:
        q = (
            select(OperatorTask)
            .where(OperatorTask.client_id == room.crm_client_id)
            .order_by(OperatorTask.updated_at.desc())
            .limit(20)
        )
        if lead:
            q = q.where(
                or_(
                    OperatorTask.lead_id == lead.id,
                    OperatorTask.client_id == room.crm_client_id,
                ),
            )
        tasks = (await db.execute(q)).scalars().all()
        return [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "due_at": t.due_at,
                "action_type": t.action_type,
            }
            for t in tasks
        ]

    @staticmethod
    async def _load_sales_recommendations(
        db: AsyncSession,
        room: DealRoom,
        lead: CrmLead | None,
    ) -> list[dict[str, Any]]:
        q = (
            select(SalesAssistantRecommendation)
            .where(SalesAssistantRecommendation.status == "open")
            .order_by(SalesAssistantRecommendation.created_at.desc())
            .limit(10)
        )
        if lead:
            q = q.where(
                or_(
                    SalesAssistantRecommendation.lead_id == lead.id,
                    SalesAssistantRecommendation.client_id == room.crm_client_id,
                ),
            )
        else:
            q = q.where(SalesAssistantRecommendation.client_id == room.crm_client_id)
        recs = (await db.execute(q)).scalars().all()
        return [
            {
                "id": str(r.id),
                "source": "sales_assistant",
                "title": r.title,
                "description": r.summary,
                "priority": r.priority,
                "recommended_action": r.recommended_action,
            }
            for r in recs
        ]

    @staticmethod
    async def _load_executive_recommendations(
        db: AsyncSession,
        room: DealRoom,
    ) -> list[dict[str, Any]]:
        result = await ExecutiveCopilotService.recommendations(
            db, client_id=room.crm_client_id, limit=8,
        )
        items = result.get("items") or []
        return [
            {
                "id": f"exec-{i}",
                "source": "executive_copilot",
                "title": r.get("title", "Executive recommendation"),
                "description": r.get("description", ""),
                "priority": r.get("priority", "medium"),
                "recommended_action": r.get("description"),
            }
            for i, r in enumerate(items)
        ]

    @staticmethod
    def _collect_signals(
        *,
        lead: CrmLead | None,
        conversations: list[dict[str, Any]],
        proposals: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        open_tasks = [t for t in tasks if t.get("status") not in ("done", "completed", "dismissed")]
        completed_tasks = [t for t in tasks if t.get("status") in ("done", "completed")]
        sent_proposals = [p for p in proposals if p.get("status") in ("sent", "accepted", "rejected")]
        recent_conv = any(
            _days_since(c.get("last_message_at")) <= 7 for c in conversations
        )
        return {
            "lead_score": lead.lead_score if lead else None,
            "activity_recent": lead and _days_since(lead.updated_at) <= 7,
            "conversation_recent": recent_conv,
            "conversation_count": len(conversations),
            "proposal_sent": len(sent_proposals) > 0,
            "proposal_count": len(proposals),
            "open_tasks": len(open_tasks),
            "completed_tasks": len(completed_tasks),
            "task_completion_rate": (
                len(completed_tasks) / max(1, len(tasks)) if tasks else 0.0
            ),
            "lead_status": lead.status if lead else None,
            "lead_priority": lead.priority if lead else None,
        }

    @staticmethod
    def _compute_probability(
        room: DealRoom,
        lead: CrmLead | None,
        signals: dict[str, Any],
    ) -> dict[str, Any]:
        factors: list[str] = []
        base = room.probability or _STAGE_DEFAULT_PROBABILITY.get(room.stage, 10)
        score = base
        factors.append(f"Stage baseline ({room.stage}): {base}")

        lead_score = signals.get("lead_score")
        if lead_score is not None:
            boost = int(lead_score * 0.15)
            score += boost
            factors.append(f"Lead score ({lead_score}): +{boost}")

        if signals.get("activity_recent"):
            score += 8
            factors.append("Recent lead activity: +8")
        elif lead and _days_since(lead.updated_at) > 14:
            score -= 15
            factors.append("Stale lead (>14 days): -15")

        if signals.get("conversation_recent"):
            score += 10
            factors.append("Recent conversation: +10")
        elif signals.get("conversation_count", 0) == 0:
            score -= 8
            factors.append("No conversations: -8")

        if signals.get("proposal_sent"):
            score += 12
            factors.append("Proposal sent: +12")
        elif signals.get("proposal_count", 0) > 0:
            score += 5
            factors.append("Draft proposal exists: +5")

        completion = signals.get("task_completion_rate", 0.0)
        if completion >= 0.5:
            score += 8
            factors.append(f"Task completion ({completion:.0%}): +8")
        elif signals.get("open_tasks", 0) > 3:
            score -= 10
            factors.append("Many open tasks: -10")

        if signals.get("lead_priority") == "high":
            score += 5
            factors.append("High priority lead: +5")

        if room.stage == "lost" or signals.get("lead_status") == "lost":
            score = 0
            factors.append("Deal lost: 0")

        final = _clamp(score)
        return {
            "score": final,
            "factors": factors,
            "stored_probability": room.probability,
        }

    @staticmethod
    def _detect_risks(
        room: DealRoom,
        lead: CrmLead | None,
        signals: dict[str, Any],
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []

        if lead and _days_since(lead.updated_at) > 14:
            risks.append({
                "type": "stale_lead",
                "severity": "high",
                "issue": "No recent lead activity in 14+ days",
                "recommendation": "Schedule a manual follow-up call or message",
            })

        if not signals.get("conversation_recent") and signals.get("conversation_count", 0) > 0:
            risks.append({
                "type": "conversation_stalled",
                "severity": "medium",
                "issue": "Conversations exist but no activity in 7+ days",
                "recommendation": "Review inbox and respond manually",
            })

        if signals.get("proposal_sent") and room.stage in ("proposal", "negotiation"):
            overdue = [t for t in tasks if t.get("status") == "todo" and t.get("due_at")]
            if overdue:
                risks.append({
                    "type": "proposal_follow_up",
                    "severity": "medium",
                    "issue": "Proposal sent — follow-up tasks pending",
                    "recommendation": "Complete pending follow-up tasks manually",
                })

        if signals.get("open_tasks", 0) > 5:
            risks.append({
                "type": "task_backlog",
                "severity": "medium",
                "issue": f"{signals['open_tasks']} open operator tasks",
                "recommendation": "Review and complete or dismiss stale tasks",
            })

        if lead and lead.lead_score is not None and lead.lead_score < 30:
            risks.append({
                "type": "low_lead_score",
                "severity": "low",
                "issue": f"Lead score is low ({lead.lead_score})",
                "recommendation": "Re-qualify lead or adjust deal strategy",
            })

        if room.status == "on_hold":
            risks.append({
                "type": "deal_on_hold",
                "severity": "low",
                "issue": "Deal room is on hold",
                "recommendation": "Review hold reason and reactivate when ready",
            })

        return risks

    @staticmethod
    async def _find_crm_deal(
        db: AsyncSession,
        room: DealRoom,
        lead: CrmLead | None,
    ) -> CrmDeal | None:
        if lead:
            result = await db.execute(
                select(CrmDeal)
                .options(selectinload(CrmDeal.lead))
                .where(
                    CrmDeal.lead_id == lead.id,
                    CrmDeal.status.notin_(("won", "lost")),
                )
                .order_by(CrmDeal.updated_at.desc())
                .limit(1),
            )
            deal = result.scalar_one_or_none()
            if deal:
                return deal
        result = await db.execute(
            select(CrmDeal)
            .options(selectinload(CrmDeal.lead))
            .where(
                CrmDeal.client_id == room.crm_client_id,
                CrmDeal.status.notin_(("won", "lost")),
                or_(
                    CrmDeal.title.ilike(room.deal_name),
                ),
            )
            .order_by(CrmDeal.updated_at.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _evaluate_lead_deal_risk(db: AsyncSession, lead: CrmLead) -> dict[str, Any] | None:
        result = await db.execute(
            select(CrmDeal)
            .options(selectinload(CrmDeal.lead))
            .where(CrmDeal.lead_id == lead.id, CrmDeal.status.notin_(("won", "lost")))
            .order_by(CrmDeal.updated_at.desc())
            .limit(1),
        )
        deal = result.scalar_one_or_none()
        if not deal:
            return None
        return await DealRiskService.evaluate_deal(db, deal)

    @staticmethod
    async def find_or_create_for_lead(
        db: AsyncSession,
        *,
        crm_lead_id: UUID,
        crm_client_id: UUID | None = None,
        deal_name: str | None = None,
    ) -> dict[str, Any]:
        """Find existing deal room or create one for a CRM lead (manual trigger only)."""
        lead = await DealRoomService._load_lead(db, crm_lead_id)
        client_id = crm_client_id or lead.client_id
        name = (deal_name or lead.name).strip()
        result = await db.execute(
            select(DealRoom)
            .options(selectinload(DealRoom.client))
            .where(
                DealRoom.crm_client_id == client_id,
                DealRoom.deal_name.ilike(name),
            )
            .limit(1),
        )
        existing = result.scalar_one_or_none()
        if existing:
            return _serialize_room(existing)

        return await DealRoomService.create_room(
            db,
            DealRoomCreateRequest(
                crm_client_id=client_id,
                deal_name=name,
                crm_lead_id=crm_lead_id,
                expected_value=lead.estimated_value,
            ),
        )
