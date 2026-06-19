"""AI Buyer Outreach Generator — draft messages only, no auto-send."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.buyer_outreach import BuyerOutreachMessage
from app.models.buyer_recommendation import BuyerRecommendation
from app.models.client import Client
from app.models.crm_lead import CrmLead
from app.models.export_agent import ExportInsight, ExportOpportunity
from app.models.product import Product
from app.models.proposal_document import ProposalDocument
from app.schemas.outreach import OutreachGenerateRequest, OutreachRegenerateRequest, OutreachUpdate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.brand_profile import brand_profile_from_client
from app.services.client_service import ClientService
from app.services.proposal_generator_service import ProposalGeneratorService

logger = logging.getLogger(__name__)

MARKER = "[Outreach]"

CHANNELS = frozenset({"email", "whatsapp", "wechat", "linkedin"})
OUTREACH_TYPES = frozenset({"first_contact", "follow_up", "proposal_follow_up", "re_engagement"})
STATUSES = frozenset({"draft", "approved", "sent", "archived"})
STYLES = frozenset({"formal", "friendly", "executive", "distributor"})
LANGUAGES = frozenset({"ru", "en", "uz", "zh"})

_CHANNEL_GUIDE = {
    "email": "Email: include subject line, formal greeting, intro, value proposition, clear CTA. Structured paragraphs.",
    "whatsapp": "WhatsApp: short, conversational, 2-4 short paragraphs max, friendly but professional.",
    "wechat": "WeChat: concise business style, respectful tone, brief bullet-friendly structure if helpful.",
    "linkedin": "LinkedIn: connection-oriented, professional networking tone, mention mutual value, soft CTA.",
}

_STYLE_GUIDE = {
    "formal": "Formal B2B tone, complete sentences, respectful titles.",
    "friendly": "Warm and approachable while remaining professional.",
    "executive": "Brief, strategic, C-level — focus on ROI and partnership value.",
    "distributor": "Distribution/partnership angle — MOQ, margins, territory, channel fit.",
}

_GENERATE_SYSTEM = """\
You write B2B buyer outreach message DRAFTS for export/manufacturing sales.
Operator sends manually — NEVER suggest automatic sending or messaging.

Return ONLY JSON:
{
  "subject": "email subject or null for non-email channels",
  "message_text": "full message body"
}

Structure for email: greeting, introduction, value proposition, call-to-action.
Adapt length and tone to channel and style instructions.
Use only facts from the provided context — no invented prices or commitments.
"""


def _serialize(msg: BuyerOutreachMessage, *, demo_mode: bool = False, style: str | None = None) -> dict[str, Any]:
    insp = sa_inspect(msg)
    event_rows = [] if "events" in insp.unloaded else (msg.events or [])
    events = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "payload_json": e.payload_json,
            "created_at": e.created_at,
        }
        for e in event_rows
    ]
    thread_title = None
    if "communication_thread" not in insp.unloaded and msg.communication_thread:
        thread_title = msg.communication_thread.title
    task_title = None
    if "follow_up_task" not in insp.unloaded and msg.follow_up_task:
        task_title = msg.follow_up_task.title
    playbook_name = None
    if "sales_playbook" not in insp.unloaded and msg.sales_playbook:
        playbook_name = msg.sales_playbook.name
    return {
        "id": msg.id,
        "client_id": msg.client_id,
        "client_name": msg.client.company_name if msg.client else None,
        "lead_id": msg.lead_id,
        "lead_name": msg.lead.name if msg.lead else None,
        "product_id": msg.product_id,
        "product_name": msg.product.name if msg.product else None,
        "proposal_id": msg.proposal_id,
        "proposal_title": msg.proposal.title if msg.proposal else None,
        "buyer_name": msg.buyer_name,
        "buyer_company": msg.buyer_company,
        "country": msg.country,
        "channel": msg.channel,
        "language": msg.language,
        "outreach_type": msg.outreach_type,
        "subject": msg.subject,
        "message_text": msg.message_text,
        "status": msg.status,
        "demo_mode": demo_mode,
        "style": style,
        "sent_at": msg.sent_at,
        "approved_at": msg.approved_at,
        "copied_at": msg.copied_at,
        "last_action_at": msg.last_action_at,
        "communication_thread_id": msg.communication_thread_id,
        "communication_thread_title": thread_title,
        "follow_up_task_id": msg.follow_up_task_id,
        "follow_up_task_title": task_title,
        "sales_playbook_id": msg.sales_playbook_id,
        "sales_playbook_name": playbook_name,
        "sales_playbook_step_id": msg.sales_playbook_step_id,
        "events": events,
        "created_at": msg.created_at,
        "updated_at": msg.updated_at,
    }


def _greeting(name: str | None, language: str) -> str:
    if language == "ru":
        return f"Уважаемый(ая) {name or 'коллега'},"
    if language == "zh":
        return f"尊敬的 {name or '合作伙伴'}，"
    return f"Dear {name or 'Colleague'},"


def _heuristic_message(
    *,
    client: Client,
    product: Product | None,
    proposal: ProposalDocument | None,
    buyer_name: str | None,
    buyer_company: str | None,
    country: str | None,
    channel: str,
    outreach_type: str,
    language: str,
    style: str,
) -> tuple[str | None, str]:
    brand = brand_profile_from_client(client)
    greet = _greeting(buyer_name, language)
    company = buyer_company or buyer_name or "your company"
    product_name = product.name if product else "our product line"
    seller = client.company_name
    country_phrase = country or "your market"

    type_intro = {
        "first_contact": "We would like to introduce our manufacturing capabilities.",
        "follow_up": "Following up on our previous conversation.",
        "proposal_follow_up": "I wanted to follow up regarding the commercial proposal we prepared.",
        "re_engagement": "We hope to reconnect and explore potential cooperation.",
    }.get(outreach_type, "We would like to explore a business opportunity.")

    if language == "ru":
        type_intro = {
            "first_contact": "Хотим представить наши производственные возможности.",
            "follow_up": "Возвращаемся к нашему предыдущему обсуждению.",
            "proposal_follow_up": "Связываемся по подготовленному коммерческому предложению.",
            "re_engagement": "Хотели бы возобновить диалог о сотрудничестве.",
        }.get(outreach_type, type_intro)

    value = (
        f"{product_name} — {(product.description or brand.get('products_services') or 'quality export products')[:200]}"
        if product
        else (brand.get("products_services") or "export-quality products")[:200]
    )

    proposal_note = ""
    if proposal:
        proposal_note = f"\n\nProposal reference: {proposal.title}"

    if channel == "email":
        subject = f"{seller} — {product_name} for {country_phrase}"
        if outreach_type == "proposal_follow_up" and proposal:
            subject = f"Follow-up: {proposal.title}"
        body = (
            f"{greet}\n\n{type_intro}\n\n"
            f"{seller} supplies {product_name} for partners in {country_phrase}. "
            f"{value}\n\n"
            f"We would welcome a brief call to discuss MOQ, pricing, and next steps.{proposal_note}\n\n"
            f"Best regards,\n{seller}"
        )
        return subject[:500], body

    if channel in ("whatsapp", "wechat"):
        body = (
            f"{greet}\n\n{type_intro} {seller} — {product_name}. "
            f"Interested in cooperation in {country_phrase}? Happy to share details."
            f"{proposal_note}"
        )
        return None, body

    # linkedin
    body = (
        f"Hello{(' ' + buyer_name) if buyer_name else ''},\n\n"
        f"I noticed {company} may be a fit for {product_name} from {seller}. "
        f"{type_intro} Open to connect and share a brief overview?"
    )
    return None, body


class BuyerOutreachService:
    @staticmethod
    async def _load_message(db: AsyncSession, msg_id: UUID) -> BuyerOutreachMessage:
        result = await db.execute(
            select(BuyerOutreachMessage)
            .options(
                selectinload(BuyerOutreachMessage.client),
                selectinload(BuyerOutreachMessage.lead),
                selectinload(BuyerOutreachMessage.product),
                selectinload(BuyerOutreachMessage.proposal),
                selectinload(BuyerOutreachMessage.communication_thread),
                selectinload(BuyerOutreachMessage.follow_up_task),
                selectinload(BuyerOutreachMessage.sales_playbook),
                selectinload(BuyerOutreachMessage.events),
            )
            .where(BuyerOutreachMessage.id == msg_id)
        )
        msg = result.scalar_one_or_none()
        if not msg:
            raise HTTPException(status_code=404, detail="Outreach message not found")
        return msg

    @staticmethod
    async def _load_product(db: AsyncSession, product_id: UUID) -> Product:
        result = await db.execute(select(Product).where(Product.id == product_id, Product.active.is_(True)))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return product

    @staticmethod
    async def _buyer_insights(db: AsyncSession, product_id: UUID) -> str:
        result = await db.execute(
            select(BuyerRecommendation)
            .where(BuyerRecommendation.product_id == product_id)
            .order_by(BuyerRecommendation.score.desc())
            .limit(5)
        )
        rows = result.scalars().all()
        if not rows:
            return ""
        return "Buyer Finder:\n" + "\n".join(
            f"- {r.recommendation_type} ({r.country or '—'}): {r.reason[:180]}" for r in rows
        )

    @staticmethod
    async def _export_insights(db: AsyncSession, product_id: UUID, country: str) -> str:
        parts = []
        opp_r = await db.execute(
            select(ExportOpportunity)
            .where(ExportOpportunity.product_id == product_id)
            .order_by(ExportOpportunity.score.desc())
            .limit(3)
        )
        for o in opp_r.scalars().all():
            if not country or o.country.lower() == country.lower() or len(parts) < 2:
                parts.append(f"- {o.country}: demand={o.demand_level}, score={o.score} — {(o.market_summary or '')[:120]}")
        ins_r = await db.execute(
            select(ExportInsight)
            .where(ExportInsight.product_id == product_id)
            .limit(3)
        )
        for i in ins_r.scalars().all():
            parts.append(f"- [{i.insight_type}] {i.title}: {i.description[:120]}")
        return ("Export Agent:\n" + "\n".join(parts)) if parts else ""

    @staticmethod
    async def _build_context(
        db: AsyncSession,
        *,
        client: Client,
        product: Product,
        lead: CrmLead | None,
        proposal: ProposalDocument | None,
        buyer_name: str | None,
        buyer_company: str | None,
        country: str,
        channel: str,
        outreach_type: str,
        language: str,
        style: str,
    ) -> str:
        brand = brand_profile_from_client(client)
        buyer_block = await BuyerOutreachService._buyer_insights(db, product.id)
        export_block = await BuyerOutreachService._export_insights(db, product.id, country)

        parts = [
            f"CHANNEL: {channel} — {_CHANNEL_GUIDE.get(channel, '')}",
            f"STYLE: {style} — {_STYLE_GUIDE.get(style, '')}",
            f"OUTREACH TYPE: {outreach_type}",
            f"LANGUAGE: {language}",
            f"SELLER: {client.company_name}",
            f"BRAND: {(brand.get('business_description') or '')[:400]}",
            f"PRODUCT: {product.name} | {product.category or '—'} | MOQ: {product.moq or 'TBD'} | "
            f"Price: {product.unit_price or 'TBD'} {product.currency}",
            f"DESCRIPTION: {(product.description or '')[:400]}",
            f"BUYER: {buyer_name or '—'} | {buyer_company or '—'} | Country: {country}",
        ]
        if lead:
            parts.append(
                f"CRM LEAD: {lead.name} | {lead.company or '—'} | interest: {(lead.interest or '')[:200]} | "
                f"notes: {(lead.notes or '')[:200]}"
            )
        if proposal:
            summary = (proposal.proposal_text or "")[:800]
            parts.append(f"PROPOSAL: {proposal.title}\n{summary}")
        if buyer_block:
            parts.append(buyer_block)
        if export_block:
            parts.append(export_block)
        return "\n\n".join(parts)

    @staticmethod
    async def _generate_text(
        db: AsyncSession,
        *,
        client: Client,
        product: Product,
        lead: CrmLead | None,
        proposal: ProposalDocument | None,
        buyer_name: str | None,
        buyer_company: str | None,
        country: str,
        channel: str,
        outreach_type: str,
        language: str,
        style: str,
    ) -> tuple[str | None, str, bool]:
        context = await BuyerOutreachService._build_context(
            db,
            client=client,
            product=product,
            lead=lead,
            proposal=proposal,
            buyer_name=buyer_name,
            buyer_company=buyer_company,
            country=country,
            channel=channel,
            outreach_type=outreach_type,
            language=language,
            style=style,
        )
        demo_mode = False
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("demo")
            _validate_api_key()
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _GENERATE_SYSTEM},
                    {"role": "user", "content": context[:12000]},
                ],
                temperature=0.5,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            subject = str(parsed.get("subject") or "").strip() or None
            message_text = str(parsed.get("message_text") or "").strip()
            if not message_text:
                raise ValueError("empty message")
            if channel != "email":
                subject = None
            return subject, message_text, demo_mode
        except Exception as exc:
            demo_mode = True
            logger.info("%s AI fallback: %s", MARKER, exc)
            subject, message_text = _heuristic_message(
                client=client,
                product=product,
                proposal=proposal,
                buyer_name=buyer_name,
                buyer_company=buyer_company,
                country=country,
                channel=channel,
                outreach_type=outreach_type,
                language=language,
                style=style,
            )
            return subject, message_text, demo_mode

    @staticmethod
    async def generate(db: AsyncSession, data: OutreachGenerateRequest) -> dict[str, Any]:
        if data.channel not in CHANNELS:
            raise HTTPException(status_code=400, detail="Invalid channel")
        if data.outreach_type not in OUTREACH_TYPES:
            raise HTTPException(status_code=400, detail="Invalid outreach type")
        if data.style not in STYLES:
            raise HTTPException(status_code=400, detail="Invalid style")
        lang = data.language if data.language in LANGUAGES else "en"

        product = await BuyerOutreachService._load_product(db, data.product_id)
        client = await ClientService.get(db, product.client_id)

        lead = None
        buyer_name = data.buyer_name
        buyer_company = data.buyer_company
        if data.lead_id:
            lead = await ProposalGeneratorService._load_lead(db, data.lead_id, client.id)
            if not buyer_name:
                buyer_name = lead.name
            if not buyer_company:
                buyer_company = lead.company

        proposal = None
        if data.proposal_id:
            proposal = await ProposalGeneratorService._load_document(db, data.proposal_id)
            if proposal.client_id != client.id:
                raise HTTPException(status_code=400, detail="Proposal belongs to a different client")

        subject, message_text, demo_mode = await BuyerOutreachService._generate_text(
            db,
            client=client,
            product=product,
            lead=lead,
            proposal=proposal,
            buyer_name=buyer_name,
            buyer_company=buyer_company,
            country=data.country.strip(),
            channel=data.channel,
            outreach_type=data.outreach_type,
            language=lang,
            style=data.style,
        )

        msg = BuyerOutreachMessage(
            client_id=client.id,
            lead_id=data.lead_id,
            product_id=product.id,
            proposal_id=data.proposal_id,
            buyer_name=buyer_name,
            buyer_company=buyer_company,
            country=data.country.strip(),
            channel=data.channel,
            language=lang,
            outreach_type=data.outreach_type,
            subject=subject,
            message_text=message_text,
            status="draft",
        )
        db.add(msg)
        await db.flush()
        from app.services.outreach_workflow_service import OutreachWorkflowService
        await OutreachWorkflowService.log_generated(db, msg.id)
        await db.commit()
        await db.refresh(msg, attribute_names=["client", "lead", "product", "proposal", "events"])

        logger.info(
            "%s generated: id=%s channel=%s type=%s demo=%s",
            MARKER, msg.id, data.channel, data.outreach_type, demo_mode,
        )
        return _serialize(msg, demo_mode=demo_mode, style=data.style)

    @staticmethod
    async def list_messages(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        lead_id: UUID | None = None,
        product_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        query = (
            select(BuyerOutreachMessage)
            .options(
                selectinload(BuyerOutreachMessage.client),
                selectinload(BuyerOutreachMessage.lead),
                selectinload(BuyerOutreachMessage.product),
                selectinload(BuyerOutreachMessage.proposal),
            )
            .order_by(BuyerOutreachMessage.created_at.desc())
        )
        count_q = select(func.count()).select_from(BuyerOutreachMessage)
        if client_id:
            query = query.where(BuyerOutreachMessage.client_id == client_id)
            count_q = count_q.where(BuyerOutreachMessage.client_id == client_id)
        if lead_id:
            query = query.where(BuyerOutreachMessage.lead_id == lead_id)
            count_q = count_q.where(BuyerOutreachMessage.lead_id == lead_id)
        if product_id:
            query = query.where(BuyerOutreachMessage.product_id == product_id)
            count_q = count_q.where(BuyerOutreachMessage.product_id == product_id)
        if status:
            query = query.where(BuyerOutreachMessage.status == status)
            count_q = count_q.where(BuyerOutreachMessage.status == status)

        total = (await db.execute(count_q)).scalar() or 0
        result = await db.execute(query.offset(skip).limit(limit))
        items = [_serialize(m) for m in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def get_message(db: AsyncSession, msg_id: UUID) -> dict[str, Any]:
        msg = await BuyerOutreachService._load_message(db, msg_id)
        return _serialize(msg)

    @staticmethod
    async def update_message(
        db: AsyncSession,
        msg_id: UUID,
        data: OutreachUpdate,
    ) -> dict[str, Any]:
        msg = await BuyerOutreachService._load_message(db, msg_id)
        payload = data.model_dump(exclude_unset=True)
        if "status" in payload and payload["status"] not in STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")

        old_status = msg.status
        for key, value in payload.items():
            setattr(msg, key, value)
        msg.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(msg, attribute_names=["client", "lead", "product", "proposal"])

        if old_status != msg.status and msg.status == "approved":
            logger.info("%s approved: id=%s", MARKER, msg.id)
        return _serialize(msg)

    @staticmethod
    async def regenerate(
        db: AsyncSession,
        msg_id: UUID,
        data: OutreachRegenerateRequest | None = None,
    ) -> dict[str, Any]:
        msg = await BuyerOutreachService._load_message(db, msg_id)
        style = (data.style if data and data.style else "formal")
        if style not in STYLES:
            raise HTTPException(status_code=400, detail="Invalid style")

        product = msg.product
        if not product and msg.product_id:
            product = await BuyerOutreachService._load_product(db, msg.product_id)
        if not product:
            raise HTTPException(status_code=400, detail="Outreach has no linked product")

        client = msg.client or await ClientService.get(db, msg.client_id)
        proposal = msg.proposal
        if msg.proposal_id and not proposal:
            proposal = await ProposalGeneratorService._load_document(db, msg.proposal_id)

        subject, message_text, demo_mode = await BuyerOutreachService._generate_text(
            db,
            client=client,
            product=product,
            lead=msg.lead,
            proposal=proposal,
            buyer_name=msg.buyer_name,
            buyer_company=msg.buyer_company,
            country=msg.country or "",
            channel=msg.channel,
            outreach_type=msg.outreach_type,
            language=msg.language,
            style=style,
        )

        msg.subject = subject
        msg.message_text = message_text
        msg.status = "draft"
        msg.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(msg, attribute_names=["client", "lead", "product", "proposal"])

        logger.info("%s regenerated: id=%s style=%s demo=%s", MARKER, msg.id, style, demo_mode)
        return _serialize(msg, demo_mode=demo_mode, style=style)
