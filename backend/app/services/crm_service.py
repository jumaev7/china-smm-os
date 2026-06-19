"""CRM + Sales Pipeline — lead management for Chinese businesses in Uzbekistan."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.client_scope_guard import guard_resource_client_id, scope_select
from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit
from app.models.client import Client
from app.models.crm_lead import CrmActivity, CrmLead
from app.schemas.crm import (
    PIPELINE_STATUSES,
    CrmActivityCreate,
    CrmExtractLeadRequest,
    CrmLeadCreate,
    CrmLeadUpdate,
)
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.client_service import ClientService
from app.services.deal_event_service import DealEventService
from app.services.partner_service import PartnerService
from app.services.schema_guard import CRM_LEAD_OPTIONAL_ATTRIBUTION, SchemaGuard

logger = logging.getLogger(__name__)

_PIPELINE_COLUMN_LIMIT = 50

LEAD_SOURCES = frozenset({"manual", "telegram", "website", "instagram", "referral", "landing_page", "other"})
LEAD_STATUSES = frozenset(PIPELINE_STATUSES)
LEAD_PRIORITIES = frozenset({"high", "medium", "low"})
ACTIVITY_TYPES = frozenset({"note", "call", "message", "meeting", "proposal", "follow_up"})

_PIPELINE_LABELS: dict[str, str] = {
    "new": "New",
    "contacted": "Contacted",
    "qualified": "Qualified",
    "proposal_sent": "Proposal Sent",
    "negotiation": "Negotiation",
    "won": "Won",
    "lost": "Lost",
}

_EXTRACT_SYSTEM = """\
You extract sales lead information from inbound messages for a Chinese company operating in Uzbekistan.
Return ONLY JSON:
{
  "name": "contact person name or null",
  "company": "company name or null",
  "phone": "phone number or null",
  "telegram": "telegram username or null",
  "email": "email or null",
  "interest": "what they want / product or service interest",
  "language": "ru|uz|en|zh or null",
  "priority": "high|medium|low",
  "suggested_next_step": "imperative for sales operator — what to do next"
}

Rules:
- Detect Russian, Uzbek, English, or Chinese text
- Phone formats: +998..., 998..., local Uzbek numbers
- Telegram: @username
- priority high if urgent/budget mentioned/large order; low if vague inquiry
- Do NOT invent contact details not present in the message
- suggested_next_step is for operator review only — never auto-contact
"""

_PHONE_RE = re.compile(r"(?:\+?998|\+?86|\+?\d{1,3})[\s\-]?\d[\d\s\-]{7,14}\d")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_TELEGRAM_RE = re.compile(r"@([a-zA-Z0-9_]{4,32})")


def _serialize_lead(lead: CrmLead, available: set[str] | None = None) -> dict[str, Any]:
    company_name = lead.client.company_name if lead.client else None
    cols = available or {c.name for c in CrmLead.__table__.columns}

    def _attr(name: str, default=None):
        if name not in cols:
            return default
        return lead.__dict__.get(name, default)

    return {
        "id": lead.id,
        "client_id": lead.client_id,
        "company_name": company_name,
        "name": lead.name,
        "company": _attr("company"),
        "phone": _attr("phone"),
        "telegram": _attr("telegram"),
        "email": _attr("email"),
        "source": _attr("source", "manual"),
        "language": _attr("language"),
        "interest": _attr("interest"),
        "notes": _attr("notes"),
        "status": _attr("status", "new"),
        "priority": _attr("priority", "medium"),
        "estimated_value": _attr("estimated_value"),
        "next_follow_up_at": _attr("next_follow_up_at"),
        "attribution_source": _attr("attribution_source"),
        "attribution_campaign": _attr("attribution_campaign"),
        "attribution_notes": _attr("attribution_notes"),
        "attributed_by": _attr("attributed_by"),
        "attribution_link_id": _attr("attribution_link_id"),
        "partner_id": _attr("partner_id"),
        "referral_code": _attr("referral_code"),
        "partner_name": getattr(lead, "_partner_name", None),
        "lead_score": _attr("lead_score"),
        "qualification_level": _attr("qualification_level"),
        "ai_summary": _attr("ai_summary"),
        "recommended_action": _attr("recommended_action"),
        "last_scored_at": _attr("last_scored_at"),
        "created_at": _attr("created_at"),
        "updated_at": _attr("updated_at"),
    }


def _serialize_activity(activity: CrmActivity) -> dict[str, Any]:
    return {
        "id": activity.id,
        "lead_id": activity.lead_id,
        "type": activity.type,
        "content": activity.content,
        "created_at": activity.created_at,
    }


def _heuristic_extract(text: str, *, client: Client) -> dict[str, Any]:
    lower = text.lower()
    phone_match = _PHONE_RE.search(text)
    email_match = _EMAIL_RE.search(text)
    tg_match = _TELEGRAM_RE.search(text)

    name = "Unknown contact"
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if lines:
        first = lines[0]
        if len(first) < 80 and not first.startswith("@"):
            name = first.split(",")[0].split("—")[0].strip()[:255]

    company = None
    for marker in ("компания", "company", "firma", "llc", "mchj", "ооо"):
        if marker in lower:
            for ln in lines:
                if marker in ln.lower():
                    company = ln[:255]
                    break

    interest = text[:500] if len(text) > 20 else None
    language = "ru"
    if any(w in lower for w in ("salom", "qiziq", "kerak", "uzb")):
        language = "uz"
    elif any(w in lower for w in ("hello", "need", "price", "quote")):
        language = "en"
    elif any("\u4e00" <= c <= "\u9fff" for c in text):
        language = "zh"

    priority = "medium"
    if any(w in lower for w in ("срочно", "urgent", "asap", "сегодня", "bugun")):
        priority = "high"
    elif any(w in lower for w in ("maybe", "возможно", "позже", "keyin")):
        priority = "low"

    suggested = "Review message and contact lead within 24 hours."
    if "цена" in lower or "price" in lower or "narx" in lower:
        suggested = "Send pricing information and schedule a call."
    elif "звон" in lower or "call" in lower or "qo'ng'iroq" in lower:
        suggested = "Schedule a phone call with the lead."

    return {
        "name": name,
        "company": company,
        "phone": phone_match.group(0).strip() if phone_match else None,
        "telegram": f"@{tg_match.group(1)}" if tg_match else None,
        "email": email_match.group(0) if email_match else None,
        "interest": interest,
        "language": language,
        "priority": priority,
        "suggested_next_step": suggested,
        "source": "fallback",
    }


async def _ai_extract(
    db: AsyncSession,
    *,
    client: Client,
    text: str,
) -> dict[str, Any]:
    if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
        return _heuristic_extract(text, client=client)

    _validate_api_key()
    kb_block = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, max_chars=2000, context="crm",
    )
    user_parts = [
        f"Client business: {client.company_name} ({client.business_category})",
        f"Message:\n{text[:6000]}",
    ]
    if kb_block:
        user_parts.append(kb_block)

    openai = get_openai()
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
        temperature=0.3,
        max_tokens=800,
        response_format={"type": "json_object"},
    )
    parsed = _extract_json(response.choices[0].message.content or "{}")
    priority = str(parsed.get("priority") or "medium").lower()
    if priority not in LEAD_PRIORITIES:
        priority = "medium"

    result = {
        "name": (str(parsed.get("name") or "").strip() or None),
        "company": (str(parsed.get("company") or "").strip() or None),
        "phone": (str(parsed.get("phone") or "").strip() or None),
        "telegram": (str(parsed.get("telegram") or "").strip() or None),
        "email": (str(parsed.get("email") or "").strip() or None),
        "interest": (str(parsed.get("interest") or "").strip() or None),
        "language": (str(parsed.get("language") or "").strip() or None),
        "priority": priority,
        "suggested_next_step": (str(parsed.get("suggested_next_step") or "").strip() or None),
        "source": "ai",
    }
    if not result["name"]:
        fallback = _heuristic_extract(text, client=client)
        result["name"] = fallback["name"]
        for key in ("phone", "telegram", "email", "company"):
            if not result.get(key) and fallback.get(key):
                result[key] = fallback[key]
    return result


class CrmService:
    @staticmethod
    async def list_leads(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        status: str | None = None,
        priority: str | None = None,
        source: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        available = await SchemaGuard.table_columns(db, "crm_leads")
        query = (
            select(CrmLead)
            .options(selectinload(CrmLead.client))
            .order_by(CrmLead.updated_at.desc())
        )
        query = await SchemaGuard.apply_crm_lead_query_options(db, query)
        count_q = select(func.count()).select_from(CrmLead)
        query, count_q = scope_select(query, count_q, CrmLead.client_id, client_id=client_id)
        if status:
            query = query.where(CrmLead.status == status)
            count_q = count_q.where(CrmLead.status == status)
        if priority:
            query = query.where(CrmLead.priority == priority)
            count_q = count_q.where(CrmLead.priority == priority)
        if source:
            query = query.where(CrmLead.source == source)
            count_q = count_q.where(CrmLead.source == source)

        total = (await db.execute(count_q)).scalar_one()

        result = await db.execute(query.offset(skip).limit(limit))
        items = [_serialize_lead(l, available) for l in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def get_lead(db: AsyncSession, lead_id: UUID) -> dict[str, Any]:
        available = await SchemaGuard.table_columns(db, "crm_leads")
        lead = await CrmService._load_lead(db, lead_id)
        data = _serialize_lead(lead, available)
        errors: list[str] = []

        async def _attribution() -> dict[str, Any]:
            from app.services.revenue_attribution_service import RevenueAttributionService
            return await RevenueAttributionService.lead_attribution(db, lead_id)

        data["revenue_attribution"] = await safe_section(
            "revenue_attribution",
            _attribution(),
            default=None,
            errors=errors,
            db=db,
        )
        return data

    @staticmethod
    async def create_lead(db: AsyncSession, data: CrmLeadCreate) -> dict[str, Any]:
        await ClientService.get(db, data.client_id)
        CrmService._validate_lead_fields(
            source=data.source,
            status=data.status,
            priority=data.priority,
        )
        partner_id = data.partner_id
        referral_code = data.referral_code
        if referral_code and not partner_id:
            partner_id, referral_code = await PartnerService.resolve_referral_code(
                db, referral_code,
            )

        lead = CrmLead(
            client_id=data.client_id,
            name=data.name.strip(),
            company=data.company,
            phone=data.phone,
            telegram=data.telegram,
            email=data.email,
            source=data.source,
            language=data.language,
            interest=data.interest,
            notes=data.notes,
            status=data.status,
            priority=data.priority,
            estimated_value=data.estimated_value,
            next_follow_up_at=data.next_follow_up_at,
        )
        available = await SchemaGuard.table_columns(db, "crm_leads")
        if "attribution_source" in available:
            lead.attribution_source = data.attribution_source or data.source
        if "attribution_campaign" in available:
            lead.attribution_campaign = data.attribution_campaign
        if "attribution_notes" in available:
            lead.attribution_notes = data.attribution_notes
        if "attributed_by" in available:
            lead.attributed_by = data.attributed_by
        if "partner_id" in available:
            lead.partner_id = partner_id
        if "referral_code" in available:
            lead.referral_code = referral_code
        db.add(lead)
        await db.flush()
        if data.attribution_link_id and "attribution_link_id" in available:
            from app.services.attribution_link_service import AttributionLinkService
            await AttributionLinkService.apply_to_lead(db, data.attribution_link_id, lead)
        await DealEventService.record_for_lead(
            db, lead.id, "activity", "Lead created", {"lead_id": str(lead.id)}, lead=lead,
        )
        await db.commit()
        await db.refresh(lead, attribute_names=["client"])
        logger.info("[CRM] lead created: id=%s client=%s", lead.id, lead.client_id)
        try:
            from app.services.platform_audit_service import PlatformAuditService
            client_row = await db.get(Client, lead.client_id)
            tenant_id = client_row.tenant_id if client_row else None
            await PlatformAuditService.record(
                db,
                actor_type="tenant",
                tenant_id=tenant_id,
                event_type="lead_creation",
                resource_type="crm_lead",
                resource_id=str(lead.id),
                details={"client_id": str(lead.client_id), "name": lead.name},
            )
        except Exception:
            logger.warning("[CRM] audit log failed on lead creation", exc_info=True)
        return _serialize_lead(lead, available)

    @staticmethod
    async def update_lead(
        db: AsyncSession,
        lead_id: UUID,
        data: CrmLeadUpdate,
    ) -> dict[str, Any]:
        lead = await CrmService._load_lead(db, lead_id)
        available = await SchemaGuard.table_columns(db, "crm_leads")
        payload = data.model_dump(exclude_unset=True)
        if "source" in payload:
            CrmService._validate_lead_fields(source=payload["source"])
        if "status" in payload:
            CrmService._validate_lead_fields(status=payload["status"])
        if "priority" in payload:
            CrmService._validate_lead_fields(priority=payload["priority"])
        if "name" in payload:
            payload["name"] = payload["name"].strip()

        attribution_link_id = payload.pop("attribution_link_id", None)

        for key, value in payload.items():
            if key in CRM_LEAD_OPTIONAL_ATTRIBUTION and key not in available:
                continue
            setattr(lead, key, value)
        if attribution_link_id is not None and "attribution_link_id" in available:
            from app.services.attribution_link_service import AttributionLinkService
            await AttributionLinkService.apply_to_lead(db, attribution_link_id, lead)
        lead.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(lead, attribute_names=["client"])
        logger.info("[CRM] lead updated: id=%s status=%s", lead.id, lead.status)
        return _serialize_lead(lead, available)

    @staticmethod
    async def delete_lead(db: AsyncSession, lead_id: UUID) -> None:
        lead = await CrmService._load_lead(db, lead_id)
        await db.delete(lead)
        await db.commit()
        logger.info("[CRM] lead deleted: id=%s", lead_id)

    @staticmethod
    async def list_activities(db: AsyncSession, lead_id: UUID) -> dict[str, Any]:
        await CrmService._load_lead(db, lead_id)
        result = await db.execute(
            select(CrmActivity)
            .where(CrmActivity.lead_id == lead_id)
            .order_by(CrmActivity.created_at.desc())
        )
        items = [_serialize_activity(a) for a in result.scalars().all()]
        return {"items": items, "total": len(items)}

    @staticmethod
    async def add_activity(
        db: AsyncSession,
        lead_id: UUID,
        data: CrmActivityCreate,
    ) -> dict[str, Any]:
        lead = await CrmService._load_lead(db, lead_id)
        if data.type not in ACTIVITY_TYPES:
            raise HTTPException(status_code=400, detail="Invalid activity type")

        activity = CrmActivity(
            lead_id=lead.id,
            type=data.type,
            content=data.content.strip(),
        )
        db.add(activity)
        lead.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(activity)
        logger.info("[CRM] activity added: lead=%s type=%s", lead_id, data.type)
        return _serialize_activity(activity)

    @staticmethod
    async def pipeline(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        per_column_limit: int = _PIPELINE_COLUMN_LIMIT,
    ) -> dict[str, Any]:
        errors: list[str] = []
        per_column_limit = min(max(1, per_column_limit), MAX_LIMIT)

        async def _build() -> dict[str, Any]:
            available = await SchemaGuard.table_columns(db, "crm_leads")
            count_q = select(CrmLead.status, func.count()).group_by(CrmLead.status)
            count_q, _ = scope_select(count_q, None, CrmLead.client_id, client_id=client_id)
            count_rows = await db.execute(count_q)
            counts: dict[str, int] = {s: 0 for s in PIPELINE_STATUSES}
            total = 0
            for status, cnt in count_rows.all():
                key = status if status in counts else "new"
                counts[key] = int(cnt or 0)
                total += int(cnt or 0)

            by_status: dict[str, list[dict[str, Any]]] = {s: [] for s in PIPELINE_STATUSES}
            for status in PIPELINE_STATUSES:
                order_by = [CrmLead.priority.desc()]
                if "lead_score" in available:
                    order_by.insert(0, CrmLead.lead_score.desc().nulls_last())
                order_by.extend([
                    CrmLead.next_follow_up_at.asc().nulls_last(),
                    CrmLead.updated_at.desc(),
                ])
                query = (
                    select(CrmLead)
                    .options(selectinload(CrmLead.client))
                    .where(CrmLead.status == status)
                    .order_by(*order_by)
                    .limit(per_column_limit)
                )
                query, _ = scope_select(query, None, CrmLead.client_id, client_id=client_id)
                query = await SchemaGuard.apply_crm_lead_query_options(db, query)
                result = await db.execute(query)
                by_status[status] = [_serialize_lead(l, available) for l in result.scalars().all()]

            columns = [
                {
                    "status": status,
                    "label": _PIPELINE_LABELS[status],
                    "leads": by_status[status],
                    "count": counts[status],
                }
                for status in PIPELINE_STATUSES
            ]
            return {"columns": columns, "total": total, "counts": counts}

        payload = await safe_section(
            "pipeline", _build(), default={
                "columns": [
                    {"status": s, "label": _PIPELINE_LABELS[s], "leads": [], "count": 0}
                    for s in PIPELINE_STATUSES
                ],
                "total": 0,
                "counts": {s: 0 for s in PIPELINE_STATUSES},
            },
            errors=errors,
        )
        payload["errors"] = errors
        return payload

    @staticmethod
    async def extract_lead(
        db: AsyncSession,
        data: CrmExtractLeadRequest,
    ) -> dict[str, Any]:
        client = await ClientService.get(db, data.client_id)
        text = data.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Text is required")

        try:
            result = await _ai_extract(db, client=client, text=text)
        except Exception as exc:
            logger.warning("[CRM] extract fallback: client=%s error=%s", client.id, exc)
            result = _heuristic_extract(text, client=client)

        logger.info("[CRM] lead extracted: client=%s source=%s", client.id, result.get("source"))
        return result

    @staticmethod
    def _validate_lead_fields(
        *,
        source: str | None = None,
        status: str | None = None,
        priority: str | None = None,
    ) -> None:
        if source is not None and source not in LEAD_SOURCES:
            raise HTTPException(status_code=400, detail=f"Invalid source: {source}")
        if status is not None and status not in LEAD_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        if priority is not None and priority not in LEAD_PRIORITIES:
            raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")

    @staticmethod
    async def _load_lead(db: AsyncSession, lead_id: UUID) -> CrmLead:
        query = (
            select(CrmLead)
            .options(selectinload(CrmLead.client))
            .where(CrmLead.id == lead_id)
        )
        query = await SchemaGuard.apply_crm_lead_query_options(db, query)
        result = await db.execute(query)
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        guard_resource_client_id(lead.client_id)
        return lead
