"""AI Proposal Generator v2 — CRM, products, communications, buyer/export context."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.client_scope_guard import guard_resource_client_id, scope_select
from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.core.storage import storage
from app.models.client import Client
from app.models.buyer_recommendation import BuyerRecommendation
from app.models.communication import CommunicationContact, CommunicationMessage, CommunicationThread
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.export_agent import ExportInsight, ExportOpportunity
from app.models.product import Product
from app.models.proposal_document import ProposalDocument
from app.schemas.proposal import (
    ProposalDocumentUpdate,
    ProposalGenerateRequest,
    ProposalRegenerateSectionRequest,
)
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.brand_profile import brand_profile_from_client
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.client_service import ClientService

logger = logging.getLogger(__name__)

MARKER = "[Proposal Generator]"

PROPOSAL_STATUSES = frozenset({"draft", "reviewed", "sent", "accepted", "rejected"})
LANGUAGES = frozenset({"ru", "uz", "en", "zh"})
PROPOSAL_TYPES = frozenset({
    "short_offer", "detailed_commercial_offer", "distributor_offer", "export_offer",
})
REGENERABLE_SECTIONS = frozenset({
    "intro", "product_summary", "pricing", "terms", "call_to_action",
})

SECTION_ORDER = (
    "intro",
    "buyer_need",
    "company_introduction",
    "recommended_products",
    "benefits",
    "pricing",
    "moq_payment_delivery",
    "next_steps",
    "call_to_action",
)

_SECTION_TO_JSON_KEY = {
    "product_summary": "recommended_products",
    "terms": "moq_payment_delivery",
}

_GENERATE_SYSTEM = """\
You write professional B2B commercial proposals for factory/export sales (Central Asia focus).
Operator sends manually — DRAFT only, never suggest auto-send.

Return ONLY JSON:
{
  "title": "proposal title",
  "sections": {
    "intro": "personalized opening",
    "buyer_need": "buyer need / pain summary",
    "company_introduction": "seller company intro",
    "recommended_products": "products with specs summary",
    "benefits": "key benefits and differentiators",
    "pricing": "pricing section with placeholders if exact price unknown",
    "moq_payment_delivery": "MOQ, payment terms, delivery placeholders",
    "next_steps": "clear next steps",
    "call_to_action": "contact CTA"
  }
}

Rules:
- Write ALL content in the requested language
- Use provided client profile, products, CRM and communication context only
- For export/distributor offers emphasize MOQ, logistics, payment terms placeholders
- Never invent certifications or prices not in context — use [TBD] placeholders
- Professional tone suitable for Uzbekistan / Central Asia B2B
"""


def _section_labels(language: str) -> dict[str, str]:
    labels = {
        "ru": {
            "intro": "Введение",
            "buyer_need": "Потребность клиента",
            "company_introduction": "О компании",
            "recommended_products": "Рекомендуемые продукты",
            "benefits": "Преимущества",
            "pricing": "Стоимость",
            "moq_payment_delivery": "MOQ, оплата и поставка",
            "next_steps": "Следующие шаги",
            "call_to_action": "Контакты",
        },
        "en": {
            "intro": "Introduction",
            "buyer_need": "Buyer need",
            "company_introduction": "Company introduction",
            "recommended_products": "Recommended products",
            "benefits": "Benefits",
            "pricing": "Pricing",
            "moq_payment_delivery": "MOQ, payment & delivery",
            "next_steps": "Next steps",
            "call_to_action": "Contact",
        },
        "uz": {
            "intro": "Kirish",
            "buyer_need": "Mijoz ehtiyoji",
            "company_introduction": "Kompaniya haqida",
            "recommended_products": "Tavsiya etilgan mahsulotlar",
            "benefits": "Afzalliklar",
            "pricing": "Narx",
            "moq_payment_delivery": "MOQ, to'lov va yetkazib berish",
            "next_steps": "Keyingi qadamlar",
            "call_to_action": "Aloqa",
        },
        "zh": {
            "intro": "简介",
            "buyer_need": "客户需求",
            "company_introduction": "公司介绍",
            "recommended_products": "推荐产品",
            "benefits": "优势",
            "pricing": "价格",
            "moq_payment_delivery": "起订量、付款与交付",
            "next_steps": "下一步",
            "call_to_action": "联系方式",
        },
    }
    return labels.get(language, labels["ru"])


def _format_proposal_text(title: str, sections: dict[str, str], language: str) -> str:
    L = _section_labels(language)
    parts = [f"# {title}", ""]
    for key in SECTION_ORDER:
        body = str(sections.get(key) or "").strip()
        if not body:
            continue
        parts.extend([f"## {L.get(key, key)}", body, ""])
    return "\n".join(parts).strip()


def _heuristic_sections(
    *,
    client: Client,
    lead: CrmLead | None,
    products: list[Product],
    language: str,
    proposal_type: str,
    custom_requirements: str | None,
) -> dict[str, str]:
    buyer = lead.name if lead else "Valued partner"
    company = lead.company if lead else None
    interest = (lead.interest if lead else None) or custom_requirements or "your procurement needs"
    recipient = f"{buyer}" + (f" ({company})" if company else "")

    product_lines = []
    for p in products:
        price = f"{p.unit_price} {p.currency}" if p.unit_price else "[TBD]"
        moq = f"MOQ: {p.moq}" if p.moq else "MOQ: [TBD]"
        product_lines.append(f"• {p.name} — {p.category or 'General'} — {price} — {moq}")

    products_block = "\n".join(product_lines) if product_lines else "• Products per catalog — pricing [TBD]"

    cta = client.cta_telegram or client.cta_phone or client.cta_website or "your account manager"

    if language == "en":
        return {
            "intro": f"Dear {recipient}, thank you for your interest in {client.company_name}.",
            "buyer_need": f"Based on your inquiry: {interest[:500]}",
            "company_introduction": (
                f"{client.company_name} — {client.business_category or 'manufacturing'}. "
                f"{(client.business_description or '')[:400]}"
            ).strip(),
            "recommended_products": products_block,
            "benefits": "• Factory-direct pricing\n• Quality control\n• Flexible MOQ options\n• Export documentation support",
            "pricing": "Pricing per attached product list. Volume discounts available upon request.",
            "moq_payment_delivery": "MOQ: [TBD per SKU] · Payment: [TBD] · Delivery: [TBD] · Incoterms: [TBD]",
            "next_steps": "1. Confirm SKU quantities\n2. Finalize commercial terms\n3. Issue proforma invoice",
            "call_to_action": f"Contact us: {cta}",
        }

    return {
        "intro": f"Уважаемый(ая) {recipient}, благодарим за интерес к {client.company_name}.",
        "buyer_need": f"Ваш запрос: {interest[:500]}",
        "company_introduction": (
            f"{client.company_name} — {client.business_category or 'производство'}. "
            f"{(client.business_description or '')[:400]}"
        ).strip(),
        "recommended_products": products_block,
        "benefits": "• Прямые цены с завода\n• Контроль качества\n• Гибкий MOQ\n• Поддержка экспортной документации",
        "pricing": "Стоимость по прайс-листу. Скидки при объёме — по запросу.",
        "moq_payment_delivery": "MOQ: [уточняется] · Оплата: [TBD] · Поставка: [TBD] · Incoterms: [TBD]",
        "next_steps": "1. Подтвердить позиции и объёмы\n2. Согласовать коммерческие условия\n3. Выставить проформу",
        "call_to_action": f"Связаться: {cta}",
    }


def _revenue_hint(doc: ProposalDocument, deal: CrmDeal | None) -> dict[str, Any] | None:
    if doc.status != "accepted":
        return None
    pricing = (doc.proposal_json or {}).get("sections", {}).get("pricing", "")
    suggested = None
    if deal and deal.expected_value:
        suggested = float(deal.expected_value)
    elif deal and deal.deal_amount:
        suggested = float(deal.deal_amount)
    return {
        "message": "Proposal accepted — review deal amount on Revenue manually (no auto-update).",
        "suggested_deal_amount": suggested,
        "deal_id": str(deal.id) if deal else None,
        "pricing_excerpt": pricing[:300] if pricing else None,
    }


def _deal_hint(doc: ProposalDocument, deal: CrmDeal | None) -> dict[str, Any] | None:
    if not deal or doc.status != "accepted":
        return None
    suggested = None
    if deal.expected_value is not None:
        suggested = float(deal.expected_value)
    elif doc.lead and doc.lead.estimated_value is not None:
        suggested = float(doc.lead.estimated_value)
    suggested_status = "proposal" if deal.status in ("new", "lost") else None
    return {
        "deal_id": deal.id,
        "message": "Review updating deal status and expected value manually (no auto-update).",
        "current_status": deal.status,
        "current_expected_value": float(deal.expected_value) if deal.expected_value else None,
        "suggested_status": suggested_status,
        "suggested_expected_value": suggested,
    }


def _serialize(doc: ProposalDocument) -> dict[str, Any]:
    pj = doc.proposal_json or {}
    sections = pj.get("sections") or {}
    deal = doc.deal
    return {
        "id": doc.id,
        "client_id": doc.client_id,
        "client_name": doc.client.company_name if doc.client else None,
        "lead_id": doc.lead_id,
        "lead_name": doc.lead.name if doc.lead else None,
        "deal_id": doc.deal_id,
        "deal_title": deal.title if deal else None,
        "product_id": doc.product_id,
        "product_ids": pj.get("product_ids") or [],
        "title": doc.title,
        "language": doc.language,
        "status": doc.status,
        "proposal_type": pj.get("proposal_type"),
        "sections": sections,
        "proposal_text": doc.proposal_text,
        "demo_mode": bool(pj.get("demo_mode")),
        "revenue_hint": _revenue_hint(doc, deal),
        "exported_pdf_path": doc.exported_pdf_path,
        "exported_docx_path": doc.exported_docx_path,
        "last_exported_at": doc.last_exported_at,
        "pdf_download_url": storage.get_url(doc.exported_pdf_path) if doc.exported_pdf_path else None,
        "docx_download_url": storage.get_url(doc.exported_docx_path) if doc.exported_docx_path else None,
        "sent_at": doc.sent_at,
        "accepted_at": doc.accepted_at,
        "rejected_at": doc.rejected_at,
        "follow_up_at": doc.follow_up_at,
        "buyer_feedback": doc.buyer_feedback,
        "deal_hint": _deal_hint(doc, deal),
        "can_create_deal": bool(doc.status == "accepted" and not doc.deal_id and doc.lead_id),
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }


class ProposalGeneratorService:
    @staticmethod
    async def _load_products(
        db: AsyncSession,
        client_id: UUID,
        product_ids: list[UUID],
    ) -> list[Product]:
        if not product_ids:
            return []
        result = await db.execute(
            select(Product)
            .where(Product.client_id == client_id, Product.id.in_(product_ids), Product.active.is_(True))
        )
        products = list(result.scalars().all())
        if len(products) != len(set(product_ids)):
            found = {p.id for p in products}
            missing = [str(pid) for pid in product_ids if pid not in found]
            raise HTTPException(status_code=404, detail=f"Products not found: {', '.join(missing)}")
        return products

    @staticmethod
    async def _load_lead(db: AsyncSession, lead_id: UUID, client_id: UUID) -> CrmLead:
        result = await db.execute(select(CrmLead).where(CrmLead.id == lead_id))
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        if lead.client_id != client_id:
            raise HTTPException(status_code=400, detail="Lead belongs to a different client")
        return lead

    @staticmethod
    async def _load_deal(db: AsyncSession, deal_id: UUID, client_id: UUID) -> CrmDeal:
        result = await db.execute(
            select(CrmDeal).options(selectinload(CrmDeal.lead)).where(CrmDeal.id == deal_id)
        )
        deal = result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        if deal.client_id != client_id:
            raise HTTPException(status_code=400, detail="Deal belongs to a different client")
        return deal

    @staticmethod
    async def _communication_summary(db: AsyncSession, lead_id: UUID | None) -> str:
        if not lead_id:
            return ""
        contact_r = await db.execute(
            select(CommunicationContact)
            .where(CommunicationContact.lead_id == lead_id)
            .limit(1)
        )
        contact = contact_r.scalar_one_or_none()
        if not contact:
            return ""

        thread_r = await db.execute(
            select(CommunicationThread)
            .where(CommunicationThread.contact_id == contact.id)
            .order_by(CommunicationThread.updated_at.desc())
            .limit(1)
        )
        thread = thread_r.scalar_one_or_none()
        if not thread:
            return f"Contact: {contact.name} ({contact.company or '—'})"

        msg_r = await db.execute(
            select(CommunicationMessage)
            .where(CommunicationMessage.thread_id == thread.id)
            .order_by(CommunicationMessage.created_at.desc())
            .limit(8)
        )
        msgs = list(reversed(msg_r.scalars().all()))
        lines = [f"Thread: {thread.title or 'Conversation'}"]
        for m in msgs:
            lines.append(f"- [{m.direction}] {(m.message_text or '')[:200]}")
        return "\n".join(lines)[:2500]

    @staticmethod
    async def _buyer_insights(db: AsyncSession, product_ids: list[UUID]) -> str:
        if not product_ids:
            return ""
        result = await db.execute(
            select(BuyerRecommendation)
            .where(BuyerRecommendation.product_id.in_(product_ids))
            .order_by(BuyerRecommendation.score.desc())
            .limit(5)
        )
        rows = result.scalars().all()
        if not rows:
            return ""
        return "Buyer Finder insights:\n" + "\n".join(
            f"- {r.recommendation_type} ({r.country or '—'}): {r.reason[:200]}" for r in rows
        )

    @staticmethod
    async def _export_insights(db: AsyncSession, product_ids: list[UUID]) -> str:
        if not product_ids:
            return ""
        opp_r = await db.execute(
            select(ExportOpportunity)
            .where(ExportOpportunity.product_id.in_(product_ids))
            .order_by(ExportOpportunity.score.desc())
            .limit(3)
        )
        opps = opp_r.scalars().all()
        ins_r = await db.execute(
            select(ExportInsight)
            .where(ExportInsight.product_id.in_(product_ids))
            .order_by(ExportInsight.confidence.desc().nullslast())
            .limit(3)
        )
        insights = ins_r.scalars().all()
        parts = []
        for o in opps:
            parts.append(f"- {o.country}: demand={o.demand_level}, score={o.score} — {(o.market_summary or '')[:150]}")
        for i in insights:
            parts.append(f"- [{i.insight_type}] {i.title}: {i.description[:150]}")
        return ("Export Agent insights:\n" + "\n".join(parts)) if parts else ""

    @staticmethod
    async def _build_context_block(
        db: AsyncSession,
        *,
        client: Client,
        lead: CrmLead | None,
        deal: CrmDeal | None,
        products: list[Product],
        comm_summary: str,
        buyer_block: str,
        export_block: str,
        proposal_type: str,
        custom_requirements: str | None,
        language: str,
    ) -> str:
        brand = brand_profile_from_client(client)
        kb = await ClientKnowledgeBaseService.build_prompt_block(
            db, client.id, max_chars=2500, context="proposal",
        )
        product_lines = []
        for p in products:
            product_lines.append(
                f"- {p.name} | SKU: {p.sku or '—'} | Cat: {p.category or '—'} | "
                f"MOQ: {p.moq or 'TBD'} | Price: {p.unit_price or 'TBD'} {p.currency} | "
                f"{(p.description or '')[:200]}"
            )

        parts = [
            f"PROPOSAL TYPE: {proposal_type}",
            f"LANGUAGE: {language}",
            f"CLIENT: {client.company_name}",
            f"BRAND: {brand.get('business_description', '')[:400]}",
            f"PRODUCTS/SERVICES: {brand.get('products_services', '')[:300]}",
        ]
        if lead:
            parts.extend([
                f"LEAD: {lead.name} | {lead.company or '—'}",
                f"INTEREST: {lead.interest or '—'}",
                f"STATUS: {lead.status} | EST VALUE: {lead.estimated_value or '—'}",
                f"NOTES: {(lead.notes or '')[:400]}",
            ])
        if deal:
            parts.append(
                f"DEAL: {deal.title} | status={deal.status} | expected={deal.expected_value or '—'}"
            )
        if product_lines:
            parts.append("PRODUCT CATALOG:\n" + "\n".join(product_lines))
        if comm_summary:
            parts.append(f"COMMUNICATION:\n{comm_summary}")
        if buyer_block:
            parts.append(buyer_block)
        if export_block:
            parts.append(export_block)
        if custom_requirements:
            parts.append(f"CUSTOM REQUIREMENTS:\n{custom_requirements[:1000]}")
        if kb:
            parts.append(kb)
        return "\n\n".join(parts)

    @staticmethod
    async def generate(db: AsyncSession, data: ProposalGenerateRequest) -> dict[str, Any]:
        client = await ClientService.get(db, data.client_id)
        language = (data.language or "ru").lower().strip()
        if language not in LANGUAGES:
            language = "ru"
        proposal_type = data.proposal_type
        if proposal_type not in PROPOSAL_TYPES:
            raise HTTPException(status_code=400, detail="Invalid proposal type")

        lead: CrmLead | None = None
        deal: CrmDeal | None = None
        if data.lead_id:
            lead = await ProposalGeneratorService._load_lead(db, data.lead_id, client.id)
        if data.deal_id:
            deal = await ProposalGeneratorService._load_deal(db, data.deal_id, client.id)
            if lead and deal.lead_id != lead.id:
                raise HTTPException(status_code=400, detail="Deal does not match lead")
            if not lead:
                lead = deal.lead

        products = await ProposalGeneratorService._load_products(db, client.id, data.product_ids)
        product_ids = [p.id for p in products]

        comm_summary = await ProposalGeneratorService._communication_summary(db, lead.id if lead else None)
        buyer_block = await ProposalGeneratorService._buyer_insights(db, product_ids)
        export_block = await ProposalGeneratorService._export_insights(db, product_ids)

        context = await ProposalGeneratorService._build_context_block(
            db,
            client=client,
            lead=lead,
            deal=deal,
            products=products,
            comm_summary=comm_summary,
            buyer_block=buyer_block,
            export_block=export_block,
            proposal_type=proposal_type,
            custom_requirements=data.custom_requirements,
            language=language,
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
                    {"role": "user", "content": context[:14000]},
                ],
                temperature=0.45,
                max_tokens=3500,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            title = str(parsed.get("title") or f"Proposal — {client.company_name}")[:255]
            raw_sections = parsed.get("sections") or {}
            sections = {k: str(raw_sections.get(k) or "").strip() for k in SECTION_ORDER}
        except Exception as exc:
            demo_mode = True
            logger.info("%s AI fallback: %s", MARKER, exc)
            sections = _heuristic_sections(
                client=client,
                lead=lead,
                products=products,
                language=language,
                proposal_type=proposal_type,
                custom_requirements=data.custom_requirements,
            )
            title = f"{'Export offer' if proposal_type == 'export_offer' else 'Commercial proposal'} — {client.company_name}"[:255]

        proposal_text = _format_proposal_text(title, sections, language)
        proposal_json = {
            "proposal_type": proposal_type,
            "product_ids": [str(pid) for pid in product_ids],
            "sections": sections,
            "demo_mode": demo_mode,
            "custom_requirements": data.custom_requirements,
        }

        doc = ProposalDocument(
            client_id=client.id,
            lead_id=lead.id if lead else None,
            deal_id=deal.id if deal else None,
            product_id=product_ids[0] if product_ids else None,
            title=title,
            language=language,
            status="draft",
            proposal_json=proposal_json,
            proposal_text=proposal_text,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc, attribute_names=["client", "lead", "deal"])

        logger.info(
            "%s generated: id=%s client=%s lead=%s deal=%s products=%s demo=%s",
            MARKER, doc.id, client.id, lead.id if lead else None,
            deal.id if deal else None, len(product_ids), demo_mode,
        )
        return _serialize(doc)

    @staticmethod
    async def list_documents(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        lead_id: UUID | None = None,
        deal_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        q = select(ProposalDocument).options(
            selectinload(ProposalDocument.client),
            selectinload(ProposalDocument.lead),
            selectinload(ProposalDocument.deal),
        )
        count_q = select(func.count()).select_from(ProposalDocument)
        q, count_q = scope_select(q, count_q, ProposalDocument.client_id, client_id=client_id)
        if lead_id:
            q = q.where(ProposalDocument.lead_id == lead_id)
            count_q = count_q.where(ProposalDocument.lead_id == lead_id)
        if deal_id:
            q = q.where(ProposalDocument.deal_id == deal_id)
            count_q = count_q.where(ProposalDocument.deal_id == deal_id)
        if status:
            q = q.where(ProposalDocument.status == status)
            count_q = count_q.where(ProposalDocument.status == status)

        total = int(await db.scalar(count_q) or 0)
        result = await db.execute(
            q.order_by(ProposalDocument.created_at.desc()).offset(skip).limit(limit)
        )
        items = [_serialize(d) for d in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def get_document(db: AsyncSession, doc_id: UUID) -> dict[str, Any]:
        doc = await ProposalGeneratorService._load_document(db, doc_id)
        return _serialize(doc)

    @staticmethod
    async def update_document(
        db: AsyncSession,
        doc_id: UUID,
        data: ProposalDocumentUpdate,
    ) -> dict[str, Any]:
        doc = await ProposalGeneratorService._load_document(db, doc_id)
        payload = data.model_dump(exclude_unset=True)

        if "status" in payload and payload["status"] not in PROPOSAL_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        if "language" in payload and payload["language"] not in LANGUAGES:
            raise HTTPException(status_code=400, detail="Invalid language")

        sections_update = payload.pop("sections", None)
        if sections_update:
            pj = dict(doc.proposal_json or {})
            merged = dict(pj.get("sections") or {})
            merged.update(sections_update)
            pj["sections"] = merged
            doc.proposal_json = pj
            doc.proposal_text = _format_proposal_text(doc.title, merged, doc.language)

        for key, value in payload.items():
            if key == "title" and value:
                value = value.strip()[:255]
            setattr(doc, key, value)

        doc.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(doc, attribute_names=["client", "lead", "deal"])

        logger.info("%s updated: id=%s status=%s", MARKER, doc.id, doc.status)
        return _serialize(doc)

    @staticmethod
    async def regenerate_section(
        db: AsyncSession,
        doc_id: UUID,
        data: ProposalRegenerateSectionRequest,
    ) -> dict[str, Any]:
        if data.section not in REGENERABLE_SECTIONS:
            raise HTTPException(status_code=400, detail="Invalid section")

        doc = await ProposalGeneratorService._load_document(db, doc_id)
        json_key = _SECTION_TO_JSON_KEY.get(data.section, data.section)
        pj = dict(doc.proposal_json or {})
        sections = dict(pj.get("sections") or {})
        product_ids = [UUID(pid) for pid in (pj.get("product_ids") or []) if pid]

        client = doc.client
        lead = doc.lead
        products = await ProposalGeneratorService._load_products(db, client.id, product_ids) if product_ids else []

        context = await ProposalGeneratorService._build_context_block(
            db,
            client=client,
            lead=lead,
            deal=doc.deal,
            products=products,
            comm_summary=await ProposalGeneratorService._communication_summary(db, doc.lead_id),
            buyer_block=await ProposalGeneratorService._buyer_insights(db, product_ids),
            export_block=await ProposalGeneratorService._export_insights(db, product_ids),
            proposal_type=pj.get("proposal_type") or "detailed_commercial_offer",
            custom_requirements=data.custom_requirements or pj.get("custom_requirements"),
            language=doc.language,
        )

        section_prompt = (
            f"Regenerate ONLY the section '{data.section}' (json key: '{json_key}') "
            f"for proposal '{doc.title}'. Return JSON: {{\"content\": \"...\"}}"
        )

        new_content = ""
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("demo")
            _validate_api_key()
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _GENERATE_SYSTEM},
                    {"role": "user", "content": f"{context}\n\n{section_prompt}"[:12000]},
                ],
                temperature=0.5,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            new_content = str(parsed.get("content") or "").strip()
        except Exception as exc:
            logger.info("%s section fallback: %s — %s", MARKER, data.section, exc)
            fallback = _heuristic_sections(
                client=client,
                lead=lead,
                products=products,
                language=doc.language,
                proposal_type=pj.get("proposal_type") or "detailed_commercial_offer",
                custom_requirements=data.custom_requirements,
            )
            new_content = fallback.get(json_key, "")

        if not new_content:
            raise HTTPException(status_code=502, detail="Failed to regenerate section")

        sections[json_key] = new_content
        pj["sections"] = sections
        doc.proposal_json = pj
        doc.proposal_text = _format_proposal_text(doc.title, sections, doc.language)
        doc.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(doc, attribute_names=["client", "lead", "deal"])

        logger.info("%s regenerated section: id=%s section=%s", MARKER, doc.id, data.section)
        return _serialize(doc)

    @staticmethod
    async def _load_document(db: AsyncSession, doc_id: UUID) -> ProposalDocument:
        result = await db.execute(
            select(ProposalDocument)
            .options(
                selectinload(ProposalDocument.client),
                selectinload(ProposalDocument.lead),
                selectinload(ProposalDocument.deal),
            )
            .where(ProposalDocument.id == doc_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=404, detail="Proposal document not found")
        guard_resource_client_id(doc.client_id)
        return doc
