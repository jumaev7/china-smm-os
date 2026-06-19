"""Deal Room v2 — commercial workspace connecting Buyer Acquisition, Revenue Engine, Factory Platform, CRM (read-only)."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.client import Client
from app.models.crm_deal import CrmDeal, CrmDealEvent
from app.models.crm_document import CrmDocument
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.deal_room import DealRoom
from app.models.factory_profile import FactoryCertificate
from app.models.proposal_document import ProposalDocument
from app.models.revenue_event import RevenueEvent
from app.services.buyer_acquisition_engine_service import BuyerAcquisitionEngineService
from app.services.buyer_intelligence_service import BuyerIntelligenceService
from app.services.deal_risk_service import DealRiskService
from app.services.deal_room_service import DealRoomService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Deal Room v2]"

V2_PIPELINE_STAGES: tuple[str, ...] = (
    "inquiry",
    "qualification",
    "quotation",
    "negotiation",
    "sample",
    "contract",
    "payment",
    "closed_won",
    "closed_lost",
)

_PIPELINE_LABELS: dict[str, str] = {
    "inquiry": "Inquiry",
    "qualification": "Qualification",
    "quotation": "Quotation",
    "negotiation": "Negotiation",
    "sample": "Sample",
    "contract": "Contract",
    "payment": "Payment",
    "closed_won": "Closed Won",
    "closed_lost": "Closed Lost",
}

_ROOM_STAGE_TO_V2: dict[str, str] = {
    "new": "inquiry",
    "qualification": "qualification",
    "proposal": "quotation",
    "negotiation": "negotiation",
    "contract": "contract",
    "closing": "payment",
    "won": "closed_won",
    "lost": "closed_lost",
}

_DEAL_STATUS_TO_V2: dict[str, str] = {
    "new": "inquiry",
    "proposal": "quotation",
    "contract": "contract",
    "invoice": "contract",
    "waiting_payment": "payment",
    "won": "closed_won",
    "lost": "closed_lost",
}

_LEAD_STATUS_TO_V2: dict[str, str] = {
    "new": "inquiry",
    "contacted": "inquiry",
    "qualified": "qualification",
    "proposal": "quotation",
    "proposal_sent": "quotation",
    "negotiation": "negotiation",
    "sample_sent": "sample",
    "won": "closed_won",
    "lost": "closed_lost",
}

_STAGE_PROBABILITY: dict[str, int] = {
    "inquiry": 5,
    "qualification": 15,
    "quotation": 35,
    "negotiation": 50,
    "sample": 55,
    "contract": 70,
    "payment": 85,
    "closed_won": 100,
    "closed_lost": 0,
}

_ACTION_SPECS: tuple[tuple[str, str, str, str], ...] = (
    (
        "open_buyer_acquisition_engine",
        "Open Buyer Acquisition Engine",
        "Review buyer profile, match score, and acquisition source.",
        "/buyer-acquisition-engine",
    ),
    (
        "open_revenue_engine",
        "Open Revenue Engine",
        "Review pipeline value, forecast, and revenue impact.",
        "/revenue-engine",
    ),
    (
        "open_factory_platform",
        "Open Factory Platform",
        "Review factory profile, catalog, and certificates.",
        "/factory-platform",
    ),
    (
        "open_crm",
        "Open CRM",
        "Review deal and lead records — manual actions only.",
        "/crm",
    ),
    (
        "open_deal_risk",
        "Open Deal Risk",
        "Review deal health score and risk classification.",
        "/deal-risk",
    ),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(score)))


def _close_probability(crm_deal: CrmDeal | None, room: DealRoom) -> int:
    if crm_deal is not None and crm_deal.probability is not None:
        return int(crm_deal.probability)
    if room.probability is not None:
        return int(room.probability)
    return 10


def _empty_summary_widget() -> dict[str, Any]:
    return {
        "readiness_score": 0,
        "total_deal_rooms": 0,
        "active_deal_rooms": 0,
        "total_pipeline_value": 0.0,
        "weighted_pipeline_value": 0.0,
        "average_health_score": 0,
        "high_risk_deals": 0,
        "top_deal": None,
        "currency": "UZS",
        "safety_notice": _safety_notice(),
    }


def _decimal_float(val: Decimal | None) -> float:
    if val is None:
        return 0.0
    return float(val)


def _safety_notice() -> str:
    return (
        "Read-only commercial workspace — no automatic emails, messaging, CRM writes, "
        "or external integrations."
    )


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _days_since(dt: datetime | None) -> int:
    dt = _aware(dt)
    if not dt:
        return 999
    return (_utc_now() - dt).days


class DealRoomV2Service:
    @staticmethod
    def _resolve_pipeline_stage(
        room: DealRoom,
        crm_deal: CrmDeal | None,
        lead: CrmLead | None,
    ) -> str:
        if room.stage in ("won",) or (crm_deal and crm_deal.status == "won"):
            return "closed_won"
        if room.stage in ("lost",) or (crm_deal and crm_deal.status == "lost"):
            return "closed_lost"
        if crm_deal:
            mapped = _DEAL_STATUS_TO_V2.get((crm_deal.status or "new").lower())
            if mapped:
                return mapped
        if lead:
            lead_status = (lead.status or "new").lower()
            if lead_status == "sample_sent":
                return "sample"
            mapped = _LEAD_STATUS_TO_V2.get(lead_status)
            if mapped and mapped not in ("closed_won", "closed_lost"):
                return mapped
        return _ROOM_STAGE_TO_V2.get(room.stage, "inquiry")

    @staticmethod
    def _deal_value(
        room: DealRoom,
        crm_deal: CrmDeal | None,
        lead: CrmLead | None,
    ) -> float:
        if crm_deal:
            val = crm_deal.deal_amount or crm_deal.expected_value
            if val:
                return _decimal_float(val)
        if room.expected_value:
            return _decimal_float(room.expected_value)
        if lead and lead.estimated_value:
            return _decimal_float(lead.estimated_value)
        return 0.0

    @staticmethod
    async def _resolve_client_ids(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> list[UUID] | None:
        if client_id:
            return [client_id]
        if tenant_id:
            return await TenantService.get_client_ids_for_tenant(db, tenant_id)
        return None

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        client_ids = await DealRoomV2Service._resolve_client_ids(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        q = select(func.count()).select_from(DealRoom)
        if client_ids is not None:
            q = q.where(DealRoom.crm_client_id.in_(client_ids))
        total_rooms = (await db.execute(q)).scalar_one() or 0

        active_q = select(func.count()).select_from(DealRoom).where(DealRoom.status == "active")
        if client_ids is not None:
            active_q = active_q.where(DealRoom.crm_client_id.in_(client_ids))
        active_rooms = (await db.execute(active_q)).scalar_one() or 0

        snap = await DealRoomV2Service._platform_snapshot(db, client_id=client_id, tenant_id=tenant_id)

        return {
            "total_deal_rooms": total_rooms,
            "active_deal_rooms": active_rooms,
            "readiness_score": snap["readiness_score"],
            "average_health_score": snap["average_health_score"],
            "total_pipeline_value": snap["total_pipeline_value"],
            "weighted_pipeline_value": snap["weighted_pipeline_value"],
            "high_risk_deals": snap["high_risk_count"],
            "integrations": snap["integrations"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def workspace(
        db: AsyncSession,
        room_id: UUID,
    ) -> dict[str, Any]:
        room = await DealRoomService._load_room(db, room_id)
        # Cache ORM scalars before partial sections — avoids lazy-load after rollback.
        room_meta = {
            "id": room.id,
            "deal_name": room.deal_name,
            "crm_client_id": room.crm_client_id,
            "client_name": room.client.company_name if room.client else None,
            "status": room.status,
            "created_at": room.created_at,
            "updated_at": room.updated_at,
        }
        lead = await DealRoomService._find_lead(db, room)
        crm_deal = await DealRoomService._find_crm_deal(db, room, lead)
        errors: list[str] = []

        risk = await safe_section(
            "risk_assessment",
            DealRoomV2Service._build_risk_assessment(db, room, crm_deal, lead),
            default={},
            errors=errors,
            db=db,
        )
        health = int((risk or {}).get("deal_health_score") or 50)
        try:
            deal_overview = DealRoomV2Service._build_deal_overview(
                room, crm_deal, lead, health_score=health,
            )
        except Exception as exc:
            errors.append(f"deal_overview: {exc}")
            deal_overview = {}
        try:
            pipeline = DealRoomV2Service._build_pipeline(room, crm_deal, lead)
        except Exception as exc:
            errors.append(f"pipeline: {exc}")
            pipeline = {}
        buyer_info = await safe_section(
            "buyer_information",
            DealRoomV2Service._build_buyer_info(db, room, lead, crm_deal),
            default={},
            errors=errors,
            db=db,
        )
        try:
            revenue = DealRoomV2Service._build_revenue_integration(room, crm_deal, lead)
        except Exception as exc:
            errors.append(f"revenue_integration: {exc}")
            revenue = {}
        documents = await safe_section(
            "documents",
            DealRoomV2Service._load_documents(db, room, lead, crm_deal),
            default={"items": []},
            errors=errors,
            db=db,
        )
        timeline = await safe_section(
            "activity_timeline",
            DealRoomV2Service._build_timeline(db, room, lead, crm_deal),
            default={"items": []},
            errors=errors,
            db=db,
        )
        integrations = await safe_section(
            "integrations",
            DealRoomV2Service._integration_status(db, room),
            default={},
            errors=errors,
            db=db,
            timeout=3.0,
        )

        return {
            **room_meta,
            "deal_overview": deal_overview,
            "pipeline": pipeline,
            "buyer_information": buyer_info,
            "revenue_integration": revenue,
            "risk_assessment": risk,
            "documents": documents,
            "activity_timeline": timeline,
            "integrations": integrations,
            "guided_actions": DealRoomV2Service._guided_actions(),
            "safety_notice": _safety_notice(),
            "errors": errors,
        }

    @staticmethod
    def _build_deal_overview(
        room: DealRoom,
        crm_deal: CrmDeal | None,
        lead: CrmLead | None,
        *,
        health_score: int | None = None,
    ) -> dict[str, Any]:
        deal_value = DealRoomV2Service._deal_value(room, crm_deal, lead)
        stage = DealRoomV2Service._resolve_pipeline_stage(room, crm_deal, lead)
        base_prob = _STAGE_PROBABILITY.get(stage, room.probability or 10)

        close_prob = base_prob
        if health_score is None:
            health_score = 50
        if crm_deal:
            close_prob = int(crm_deal.probability or base_prob)
        elif room.probability:
            close_prob = room.probability

        expected_revenue = deal_value * (close_prob / 100.0)
        estimated_close = None
        if crm_deal and crm_deal.expected_close_date:
            estimated_close = crm_deal.expected_close_date
        elif lead and lead.next_follow_up_at:
            estimated_close = lead.next_follow_up_at + timedelta(days=30)

        deal_owner = None
        if lead and lead.attributed_by:
            deal_owner = lead.attributed_by
        elif lead:
            deal_owner = "Sales Team"

        return {
            "deal_health_score": health_score,
            "deal_value": deal_value,
            "expected_revenue": round(expected_revenue, 2),
            "close_probability": close_prob,
            "estimated_close_date": estimated_close,
            "deal_owner": deal_owner,
            "currency": crm_deal.currency if crm_deal else "UZS",
            "current_stage": stage,
            "current_stage_label": _PIPELINE_LABELS.get(stage, stage),
        }

    @staticmethod
    def _build_pipeline(
        room: DealRoom,
        crm_deal: CrmDeal | None,
        lead: CrmLead | None,
    ) -> dict[str, Any]:
        current = DealRoomV2Service._resolve_pipeline_stage(room, crm_deal, lead)
        current_idx = V2_PIPELINE_STAGES.index(current) if current in V2_PIPELINE_STAGES else 0

        stages = []
        for i, stage in enumerate(V2_PIPELINE_STAGES):
            if stage in ("closed_won", "closed_lost"):
                status = "completed" if stage == current else "skipped"
                if current in ("closed_won", "closed_lost") and stage == current:
                    status = "current"
            elif i < current_idx:
                status = "completed"
            elif i == current_idx:
                status = "current"
            else:
                status = "upcoming"
            stages.append({
                "stage": stage,
                "label": _PIPELINE_LABELS[stage],
                "status": status,
                "probability": _STAGE_PROBABILITY.get(stage, 0),
            })

        return {
            "current_stage": current,
            "current_stage_label": _PIPELINE_LABELS.get(current, current),
            "stages": stages,
        }

    @staticmethod
    async def _build_buyer_info(
        db: AsyncSession,
        room: DealRoom,
        lead: CrmLead | None,
        crm_deal: CrmDeal | None,
    ) -> dict[str, Any]:
        company = lead.company if lead and lead.company else room.deal_name
        country = None
        industry = None
        relationship_strength = "unknown"
        acquisition_source = lead.source if lead else "manual"
        buyer_profile_id = None
        match_score = None

        if lead:
            buyer_ev = None
            try:
                buyer_ev = await BuyerIntelligenceService.evaluate_buyer(db, lead)
            except Exception as exc:
                logger.debug("%s buyer intel skip: %s", MARKER, exc)
            if buyer_ev:
                match_score = buyer_ev.get("buyer_score")
                classification = buyer_ev.get("classification", "")
                if classification in ("hot", "strategic"):
                    relationship_strength = "strong"
                elif classification in ("active", "high_potential"):
                    relationship_strength = "moderate"
                elif classification in ("inactive", "at_risk"):
                    relationship_strength = "weak"
                else:
                    relationship_strength = "developing"

        try:
            engine_snap = await BuyerAcquisitionEngineService._snapshot(
                db, client_id=room.crm_client_id,
            )
            for buyer in engine_snap.get("buyers", []):
                b_company = (buyer.get("company_name") or "").lower()
                if company and b_company and (
                    b_company in company.lower() or company.lower() in b_company
                ):
                    buyer_profile_id = buyer.get("buyer_id")
                    match_score = match_score or buyer.get("match_score")
                    country = country or buyer.get("country")
                    industry = industry or buyer.get("industry")
                    if buyer.get("relationship_status") in ("strategic", "customer", "active"):
                        relationship_strength = "strong"
                    break
        except Exception as exc:
            logger.debug("%s buyer engine skip: %s", MARKER, exc)

        if lead:
            notes = (lead.notes or "") + (lead.interest or "")
            for token in ("uzbekistan", "kazakhstan", "russia", "uae", "turkey", "china"):
                if token in notes.lower():
                    country = country or token.title()
            if lead.attribution_source:
                acquisition_source = lead.attribution_source

        return {
            "linked_buyer_profile_id": buyer_profile_id,
            "company_name": company,
            "contact_name": lead.name if lead else None,
            "country": country,
            "industry": industry,
            "relationship_strength": relationship_strength,
            "acquisition_source": acquisition_source,
            "lead_id": lead.id if lead else None,
            "crm_deal_id": crm_deal.id if crm_deal else None,
            "match_score": match_score,
            "email": lead.email if lead else None,
            "phone": lead.phone if lead else None,
        }

    @staticmethod
    def _build_revenue_integration(
        room: DealRoom,
        crm_deal: CrmDeal | None,
        lead: CrmLead | None,
    ) -> dict[str, Any]:
        deal_value = DealRoomV2Service._deal_value(room, crm_deal, lead)
        stage = DealRoomV2Service._resolve_pipeline_stage(room, crm_deal, lead)
        close_prob = int(crm_deal.probability if crm_deal else room.probability or _STAGE_PROBABILITY.get(stage, 10))
        expected_revenue = round(deal_value * (close_prob / 100.0), 2)
        weighted_revenue = expected_revenue

        forecast_impact = "neutral"
        if close_prob >= 70 and deal_value >= 50000:
            forecast_impact = "high_positive"
        elif close_prob >= 50:
            forecast_impact = "positive"
        elif close_prob < 30:
            forecast_impact = "negative"

        pipeline_contribution = round(deal_value, 2) if stage not in ("closed_won", "closed_lost") else 0.0

        return {
            "expected_revenue": expected_revenue,
            "weighted_revenue": weighted_revenue,
            "revenue_forecast_impact": forecast_impact,
            "pipeline_contribution": pipeline_contribution,
            "deal_value": deal_value,
            "close_probability": close_prob,
            "currency": crm_deal.currency if crm_deal else "UZS",
        }

    @staticmethod
    async def _build_risk_assessment(
        db: AsyncSession,
        room: DealRoom,
        crm_deal: CrmDeal | None,
        lead: CrmLead | None,
    ) -> dict[str, Any]:
        deal_risk = None
        if crm_deal:
            try:
                deal_risk = await DealRiskService.evaluate_deal(db, crm_deal)
            except Exception as exc:
                logger.debug("%s deal risk skip: %s", MARKER, exc)

        health = int((deal_risk or {}).get("deal_health_score") or 50)
        risk_level = (deal_risk or {}).get("risk_level") or "watchlist"
        risk_reasons = (deal_risk or {}).get("risk_reasons") or []

        commercial = _clamp(100 - health + 20)
        payment = 30
        logistics = 25
        compliance = 20

        if crm_deal:
            status = (crm_deal.status or "").lower()
            if status in ("waiting_payment", "invoice"):
                payment = 55
            if status == "contract":
                commercial = _clamp(commercial + 10)

        for reason in risk_reasons:
            r = str(reason).lower()
            if "payment" in r or "invoice" in r:
                payment = _clamp(payment + 20)
            if "logistic" in r or "shipping" in r or "delivery" in r:
                logistics = _clamp(logistics + 25)
            if "compliance" in r or "certificate" in r or "regulatory" in r:
                compliance = _clamp(compliance + 25)
            if "proposal" in r or "negotiation" in r or "stalled" in r:
                commercial = _clamp(commercial + 15)

        if lead and _days_since(lead.updated_at) > 14:
            commercial = _clamp(commercial + 15)
        if room.status == "on_hold":
            commercial = _clamp(commercial + 10)

        overall = _clamp(int((commercial + payment + logistics + compliance) / 4))

        def _risk_band(score: int) -> str:
            if score >= 70:
                return "high"
            if score >= 45:
                return "medium"
            return "low"

        return {
            "commercial_risk": commercial,
            "commercial_risk_level": _risk_band(commercial),
            "payment_risk": payment,
            "payment_risk_level": _risk_band(payment),
            "logistics_risk": logistics,
            "logistics_risk_level": _risk_band(logistics),
            "compliance_risk": compliance,
            "compliance_risk_level": _risk_band(compliance),
            "overall_risk_score": overall,
            "overall_risk_level": _risk_band(overall),
            "deal_health_score": health,
            "deal_risk_classification": risk_level,
            "risk_factors": risk_reasons[:6],
        }

    @staticmethod
    async def _load_documents(
        db: AsyncSession,
        room: DealRoom,
        lead: CrmLead | None,
        crm_deal: CrmDeal | None,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []

        prop_q = select(ProposalDocument).order_by(ProposalDocument.updated_at.desc())
        if lead:
            prop_q = prop_q.where(
                or_(
                    ProposalDocument.lead_id == lead.id,
                    ProposalDocument.client_id == room.crm_client_id,
                ),
            )
        else:
            prop_q = prop_q.where(ProposalDocument.client_id == room.crm_client_id)
        for p in (await db.execute(prop_q.limit(10))).scalars().all():
            items.append({
                "id": str(p.id),
                "category": "quotation",
                "title": p.title,
                "status": p.status,
                "document_type": "quotation",
                "updated_at": p.updated_at,
                "sent_at": p.sent_at,
            })

        doc_q = select(CrmDocument).order_by(CrmDocument.updated_at.desc())
        if lead:
            doc_q = doc_q.where(
                or_(
                    CrmDocument.lead_id == lead.id,
                    CrmDocument.client_id == room.crm_client_id,
                ),
            )
        else:
            doc_q = doc_q.where(CrmDocument.client_id == room.crm_client_id)
        for d in (await db.execute(doc_q.limit(10))).scalars().all():
            category = "contract"
            if d.document_type in ("invoice",):
                category = "payment_confirmation"
            elif d.document_type in ("shipping", "delivery"):
                category = "shipping_document"
            items.append({
                "id": str(d.id),
                "category": category,
                "title": d.title,
                "status": d.status,
                "document_type": d.document_type,
                "amount": _decimal_float(d.amount),
                "currency": d.currency,
                "updated_at": d.updated_at,
            })

        client = await db.execute(select(Client).where(Client.id == room.crm_client_id))
        client_row = client.scalar_one_or_none()
        if client_row and client_row.tenant_id:
            cert_q = (
                select(FactoryCertificate)
                .where(FactoryCertificate.tenant_id == client_row.tenant_id)
                .order_by(FactoryCertificate.updated_at.desc())
                .limit(5)
            )
            for c in (await db.execute(cert_q)).scalars().all():
                today = date.today()
                items.append({
                    "id": str(c.id),
                    "category": "certificate",
                    "title": c.certificate_name or c.certificate_type or "Certificate",
                    "status": "active" if not c.expiry_date or c.expiry_date >= today else "expired",
                    "document_type": c.certificate_type,
                    "certificate_number": c.certificate_number,
                    "updated_at": c.updated_at,
                })

        if crm_deal:
            rev_q = (
                select(RevenueEvent)
                .where(RevenueEvent.deal_id == crm_deal.id)
                .order_by(RevenueEvent.created_at.desc())
                .limit(5)
            )
            for ev in (await db.execute(rev_q)).scalars().all():
                if ev.type in ("payment_received", "payment", "commission"):
                    items.append({
                        "id": str(ev.id),
                        "category": "payment_confirmation",
                        "title": f"Payment — {ev.type}",
                        "status": "confirmed",
                        "document_type": ev.type,
                        "amount": _decimal_float(ev.amount),
                        "updated_at": ev.created_at,
                    })

        items.sort(key=lambda x: _aware(x.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        return {
            "items": items,
            "quotation_count": sum(1 for i in items if i["category"] == "quotation"),
            "contract_count": sum(1 for i in items if i["category"] == "contract"),
            "certificate_count": sum(1 for i in items if i["category"] == "certificate"),
            "shipping_count": sum(1 for i in items if i["category"] == "shipping_document"),
            "payment_count": sum(1 for i in items if i["category"] == "payment_confirmation"),
        }

    @staticmethod
    async def _build_timeline(
        db: AsyncSession,
        room: DealRoom,
        lead: CrmLead | None,
        crm_deal: CrmDeal | None,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []

        items.append({
            "id": f"room-created-{room.id}",
            "event_type": "status_change",
            "category": "status_change",
            "title": "Deal room created",
            "description": f"Workspace opened for {room.deal_name}",
            "occurred_at": room.created_at,
        })

        if room.updated_at and room.updated_at != room.created_at:
            items.append({
                "id": f"room-updated-{room.id}",
                "event_type": "status_change",
                "category": "status_change",
                "title": f"Stage: {room.stage}",
                "description": f"Deal room stage updated to {room.stage}",
                "occurred_at": room.updated_at,
            })

        if lead:
            act_q = (
                select(CrmActivity)
                .where(CrmActivity.lead_id == lead.id)
                .order_by(CrmActivity.created_at.desc())
                .limit(15)
            )
            for act in (await db.execute(act_q)).scalars().all():
                category = "meeting" if act.type in ("meeting", "call", "visit") else "activity"
                items.append({
                    "id": str(act.id),
                    "event_type": act.type,
                    "category": category,
                    "title": act.type.replace("_", " ").title(),
                    "description": act.content[:200] if act.content else "",
                    "occurred_at": act.created_at,
                })

        prop_q = select(ProposalDocument).order_by(ProposalDocument.sent_at.desc().nullslast())
        if lead:
            prop_q = prop_q.where(ProposalDocument.lead_id == lead.id)
        else:
            prop_q = prop_q.where(ProposalDocument.client_id == room.crm_client_id)
        for p in (await db.execute(prop_q.limit(8))).scalars().all():
            ts = p.sent_at or p.created_at
            items.append({
                "id": f"prop-{p.id}",
                "event_type": "quotation",
                "category": "quotation",
                "title": f"Quotation: {p.title}",
                "description": f"Status: {p.status}",
                "occurred_at": ts,
            })

        if crm_deal:
            ev_q = (
                select(CrmDealEvent)
                .where(CrmDealEvent.deal_id == crm_deal.id)
                .order_by(CrmDealEvent.created_at.desc())
                .limit(10)
            )
            for ev in (await db.execute(ev_q)).scalars().all():
                cat = "contract_update" if ev.event_type in ("contract", "document") else "negotiation"
                if ev.event_type in ("status", "stage"):
                    cat = "status_change"
                items.append({
                    "id": str(ev.id),
                    "event_type": ev.event_type,
                    "category": cat,
                    "title": ev.title,
                    "description": (ev.payload_json or {}).get("note", "") if ev.payload_json else "",
                    "occurred_at": ev.created_at,
                })

        items.sort(
            key=lambda x: _aware(x.get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return {"items": items[:30]}

    @staticmethod
    async def _integration_status(db: AsyncSession, room: DealRoom) -> dict[str, Any]:
        """Lightweight integration flags — avoid heavy overview scans in workspace panel."""
        _ = db
        factory_ok = bool(room.client and room.client.tenant_id)
        return {
            "buyer_acquisition_engine": "ok",
            "revenue_engine": "ok",
            "factory_platform": "ok" if factory_ok else "unavailable",
            "crm": "ok",
            "deal_risk": "ok",
        }

    @staticmethod
    def _guided_actions() -> list[dict[str, str]]:
        return [
            {"action_id": a[0], "title": a[1], "description": a[2], "route": a[3]}
            for a in _ACTION_SPECS
        ]

    @staticmethod
    async def _platform_snapshot(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        client_ids = await DealRoomV2Service._resolve_client_ids(
            db, client_id=client_id, tenant_id=tenant_id,
        )

        q = select(DealRoom).options(selectinload(DealRoom.client)).where(DealRoom.status == "active")
        if client_ids is not None:
            q = q.where(DealRoom.crm_client_id.in_(client_ids))
        rooms = (await db.execute(q.limit(50))).scalars().all()

        total_pipeline = 0.0
        weighted = 0.0
        health_scores: list[int] = []
        high_risk = 0

        for room in rooms:
            lead = await DealRoomService._find_lead(db, room)
            crm_deal = await DealRoomService._find_crm_deal(db, room, lead)
            val = DealRoomV2Service._deal_value(room, crm_deal, lead)
            prob = _close_probability(crm_deal, room)
            total_pipeline += val
            weighted += val * (prob / 100.0)
            if prob < 30 or room.stage in ("lost",):
                high_risk += 1
            health_scores.append(prob)

        avg_health = int(sum(health_scores) / len(health_scores)) if health_scores else 0
        readiness = _clamp(avg_health + (10 if len(rooms) > 0 else 0))

        integrations = {
            "buyer_acquisition_engine": "ok",
            "revenue_engine": "ok",
            "factory_platform": "ok",
            "crm": "ok",
        }

        return {
            "readiness_score": readiness,
            "average_health_score": avg_health,
            "total_pipeline_value": round(total_pipeline, 2),
            "weighted_pipeline_value": round(weighted, 2),
            "high_risk_count": high_risk,
            "active_room_count": len(rooms),
            "integrations": integrations,
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        try:
            snap = await DealRoomV2Service._platform_snapshot(
                db, client_id=client_id, tenant_id=tenant_id,
            )
            ov_q = select(func.count()).select_from(DealRoom)
            if client_id:
                ov_q = ov_q.where(DealRoom.crm_client_id == client_id)
            total = (await db.execute(ov_q)).scalar_one() or 0

            top_room = None
            q = (
                select(DealRoom)
                .options(selectinload(DealRoom.client))
                .order_by(DealRoom.updated_at.desc())
            )
            if client_id:
                q = q.where(DealRoom.crm_client_id == client_id)
            room = (await db.execute(q.limit(1))).scalar_one_or_none()
            if room:
                lead = await DealRoomService._find_lead(db, room)
                crm_deal = await DealRoomService._find_crm_deal(db, room, lead)
                top_room = {
                    "deal_room_id": str(room.id),
                    "deal_name": room.deal_name,
                    "stage": DealRoomV2Service._resolve_pipeline_stage(room, crm_deal, lead),
                    "deal_value": DealRoomV2Service._deal_value(room, crm_deal, lead),
                    "close_probability": _close_probability(crm_deal, room),
                }

            return {
                "readiness_score": snap["readiness_score"],
                "total_deal_rooms": total,
                "active_deal_rooms": snap["active_room_count"],
                "total_pipeline_value": snap["total_pipeline_value"],
                "weighted_pipeline_value": snap["weighted_pipeline_value"],
                "average_health_score": snap["average_health_score"],
                "high_risk_deals": snap["high_risk_count"],
                "top_deal": top_room,
                "currency": "UZS",
                "safety_notice": _safety_notice(),
            }
        except Exception as exc:
            logger.warning("%s summary_widget failed: %s", MARKER, exc)
            return _empty_summary_widget()

    @staticmethod
    async def deal_acquisition_panel(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await DealRoomV2Service._platform_snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        client_ids = await DealRoomV2Service._resolve_client_ids(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        q = select(DealRoom).options(selectinload(DealRoom.client)).order_by(DealRoom.updated_at.desc())
        if client_ids is not None:
            q = q.where(DealRoom.crm_client_id.in_(client_ids))
        rooms = (await db.execute(q.limit(5))).scalars().all()

        deals = []
        for room in rooms:
            lead = await DealRoomService._find_lead(db, room)
            crm_deal = await DealRoomService._find_crm_deal(db, room, lead)
            buyer = await DealRoomV2Service._build_buyer_info(db, room, lead, crm_deal)
            deals.append({
                "deal_room_id": str(room.id),
                "deal_name": room.deal_name,
                "buyer_company": buyer.get("company_name"),
                "acquisition_source": buyer.get("acquisition_source"),
                "relationship_strength": buyer.get("relationship_strength"),
                "match_score": buyer.get("match_score"),
                "stage": DealRoomV2Service._resolve_pipeline_stage(room, crm_deal, lead),
            })

        return {
            "active_deal_rooms": snap["active_room_count"],
            "total_pipeline_value": snap["total_pipeline_value"],
            "deals": deals,
            "message": (
                f"{snap['active_room_count']} active deal room(s) connected to buyer acquisition pipeline"
            ),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def deal_revenue_panel(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await DealRoomV2Service._platform_snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        client_ids = await DealRoomV2Service._resolve_client_ids(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        q = select(DealRoom).options(selectinload(DealRoom.client)).order_by(DealRoom.updated_at.desc())
        if client_ids is not None:
            q = q.where(DealRoom.crm_client_id.in_(client_ids))
        rooms = (await db.execute(q.limit(5))).scalars().all()

        deals = []
        for room in rooms:
            lead = await DealRoomService._find_lead(db, room)
            crm_deal = await DealRoomService._find_crm_deal(db, room, lead)
            rev = DealRoomV2Service._build_revenue_integration(room, crm_deal, lead)
            deals.append({
                "deal_room_id": str(room.id),
                "deal_name": room.deal_name,
                "deal_value": rev["deal_value"],
                "expected_revenue": rev["expected_revenue"],
                "weighted_revenue": rev["weighted_revenue"],
                "pipeline_contribution": rev["pipeline_contribution"],
                "forecast_impact": rev["revenue_forecast_impact"],
                "stage": DealRoomV2Service._resolve_pipeline_stage(room, crm_deal, lead),
            })

        return {
            "readiness_score": snap["readiness_score"],
            "total_pipeline_value": snap["total_pipeline_value"],
            "weighted_pipeline_value": snap["weighted_pipeline_value"],
            "active_deal_rooms": snap["active_room_count"],
            "deals": deals,
            "message": (
                f"Deal Room pipeline {snap['total_pipeline_value']:,.0f} UZS — "
                f"weighted {snap['weighted_pipeline_value']:,.0f}"
            ),
            "currency": "UZS",
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def executive_summary(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        widget = await DealRoomV2Service.summary_widget(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return {
            "readiness_score": widget["readiness_score"],
            "total_deal_rooms": widget["total_deal_rooms"],
            "active_deal_rooms": widget["active_deal_rooms"],
            "total_pipeline_value": widget["total_pipeline_value"],
            "weighted_pipeline_value": widget["weighted_pipeline_value"],
            "high_risk_deals": widget["high_risk_deals"],
            "top_deal": widget.get("top_deal"),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def list_workspaces(
        db: AsyncSession,
        *,
        crm_client_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        base = await DealRoomService.list_rooms(
            db, crm_client_id=crm_client_id, status=status, skip=skip, limit=limit,
        )
        enriched = []
        for item in base.get("items") or []:
            room_id = item["id"]
            room = await DealRoomService._load_room(db, room_id)
            lead = await DealRoomService._find_lead(db, room)
            crm_deal = await DealRoomService._find_crm_deal(db, room, lead)
            stage = DealRoomV2Service._resolve_pipeline_stage(room, crm_deal, lead)
            enriched.append({
                **item,
                "v2_stage": stage,
                "v2_stage_label": _PIPELINE_LABELS.get(stage, stage),
                "deal_value": DealRoomV2Service._deal_value(room, crm_deal, lead),
                "close_probability": int(crm_deal.probability if crm_deal else item.get("probability") or 10),
            })
        return {"items": enriched, "total": base.get("total", 0)}

    @staticmethod
    async def refresh(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        snap = await DealRoomV2Service._platform_snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        logger.info("%s refresh %.0fms rooms=%s", MARKER, (time.perf_counter() - t0) * 1000, snap["active_room_count"])
        return {
            "refreshed_at": _utc_now(),
            "readiness_score": snap["readiness_score"],
            "active_deal_rooms": snap["active_room_count"],
            "total_pipeline_value": snap["total_pipeline_value"],
            "safety_notice": _safety_notice(),
        }
