"""AI Proposal Generator — commercial proposals for CRM leads."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.crm_lead import CrmLead
from app.models.crm_proposal import CrmProposal
from app.schemas.crm import CrmProposalGenerateRequest, CrmProposalUpdate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.deal_event_service import DealEventService
from app.services.sales_copilot_service import SalesCopilotService

logger = logging.getLogger(__name__)

PROPOSAL_STATUSES = frozenset({"draft", "sent", "accepted", "rejected"})
LANGUAGES = frozenset({"ru", "uz", "en", "zh"})

_PROPOSAL_SYSTEM = """\
You write a commercial proposal for a B2B lead (Chinese company services in Uzbekistan market).
Operator sends manually — this is a DRAFT only.

Return ONLY JSON:
{
  "title": "proposal title",
  "intro": "short personalized intro (2-3 sentences)",
  "pain_problem": "client pain / problem based on lead interest",
  "proposed_solution": "how the provider solves it",
  "package_options": "1-3 package tiers or options as bullet-style text",
  "timeline": "realistic delivery timeline",
  "price_section": "pricing summary — use lead estimated_value if provided, else ranges",
  "estimated_value": null or number,
  "cta": "clear call to action with contact method"
}

Rules:
- Write ALL section content in the requested language (ru/uz/en/zh)
- Be factual — use client brand/KB, do not invent unsupported claims
- Professional tone suitable for Uzbekistan market
- Never mention AI or auto-send
"""


def _serialize_proposal(proposal: CrmProposal) -> dict[str, Any]:
    lead_name = proposal.lead.name if proposal.lead else None
    return {
        "id": proposal.id,
        "lead_id": proposal.lead_id,
        "client_id": proposal.client_id,
        "lead_name": lead_name,
        "title": proposal.title,
        "language": proposal.language,
        "status": proposal.status,
        "proposal_text": proposal.proposal_text,
        "estimated_value": proposal.estimated_value,
        "valid_until": proposal.valid_until,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
    }


def _format_proposal_document(
    *,
    title: str,
    sections: dict[str, Any],
    lead: CrmLead,
    client: Client,
    valid_until: datetime,
    language: str,
) -> str:
    labels = {
        "ru": {
            "prepared": "Подготовлено для",
            "from": "От",
            "valid": "Действительно до",
            "intro": "Введение",
            "pain": "Задача клиента",
            "solution": "Предлагаемое решение",
            "packages": "Пакеты и опции",
            "timeline": "Сроки",
            "price": "Стоимость",
            "cta": "Следующий шаг",
        },
        "uz": {
            "prepared": "Tayyorlangan",
            "from": "Dan",
            "valid": "Amal qilish muddati",
            "intro": "Kirish",
            "pain": "Mijoz muammosi",
            "solution": "Taklif etilgan yechim",
            "packages": "Paketlar",
            "timeline": "Muddatlar",
            "price": "Narx",
            "cta": "Keyingi qadam",
        },
        "en": {
            "prepared": "Prepared for",
            "from": "From",
            "valid": "Valid until",
            "intro": "Introduction",
            "pain": "Client challenge",
            "solution": "Proposed solution",
            "packages": "Packages & options",
            "timeline": "Timeline",
            "price": "Investment",
            "cta": "Next step",
        },
        "zh": {
            "prepared": "致",
            "from": "来自",
            "valid": "有效期至",
            "intro": "简介",
            "pain": "客户需求",
            "solution": "解决方案",
            "packages": "方案选项",
            "timeline": "时间线",
            "price": "价格",
            "cta": "下一步",
        },
    }
    L = labels.get(language, labels["ru"])
    recipient = lead.name + (f" — {lead.company}" if lead.company else "")

    parts = [
        f"# {title}",
        "",
        f"**{L['prepared']}:** {recipient}",
        f"**{L['from']}:** {client.company_name}",
        f"**{L['valid']}:** {valid_until.date().isoformat()}",
        "",
        f"## {L['intro']}",
        str(sections.get("intro") or "").strip(),
        "",
        f"## {L['pain']}",
        str(sections.get("pain_problem") or "").strip(),
        "",
        f"## {L['solution']}",
        str(sections.get("proposed_solution") or "").strip(),
        "",
        f"## {L['packages']}",
        str(sections.get("package_options") or "").strip(),
        "",
        f"## {L['timeline']}",
        str(sections.get("timeline") or "").strip(),
        "",
        f"## {L['price']}",
        str(sections.get("price_section") or "").strip(),
        "",
        f"## {L['cta']}",
        str(sections.get("cta") or "").strip(),
    ]
    return "\n".join(parts).strip()


def _heuristic_proposal(
    *,
    lead: CrmLead,
    client: Client,
    language: str,
) -> dict[str, Any]:
    interest = lead.interest or "social media and marketing services"
    value = float(lead.estimated_value) if lead.estimated_value else None
    recipient = lead.name

    if language == "uz":
        title = f"{client.company_name} — tijoriy taklif"
        sections = {
            "intro": f"Hurmatli {recipient}, {client.company_name} sizga moslashtirilgan taklif taqdim etadi.",
            "pain_problem": f"Sizning ehtiyojingiz: {interest}",
            "proposed_solution": f"{client.business_category} sohasida professional SMM va kontent yechimlari.",
            "package_options": "• Standart — oylik kontent rejasi\n• Pro — kontent + reklama qo'llab-quvvatlash\n• Premium — to'liq SMM boshqaruvi",
            "timeline": "Boshlash: 5-7 ish kuni ichida. Birinchi natijalar: 2-3 hafta.",
            "price_section": f"Taxminiy investitsiya: {value:,.0f} UZS" if value else "Narx individual hisoblanadi — batafsil muhokama qilamiz.",
            "cta": f"Bog'lanish: {client.cta_telegram or client.cta_phone or client.cta_website or 'operator orqali'}",
        }
    elif language == "en":
        title = f"Commercial Proposal — {client.company_name}"
        sections = {
            "intro": f"Dear {recipient}, thank you for your interest in {client.company_name}.",
            "pain_problem": f"Your stated need: {interest}",
            "proposed_solution": f"Tailored {client.business_category} marketing and content services for the Uzbekistan market.",
            "package_options": "• Standard — monthly content plan\n• Pro — content + ad support\n• Premium — full SMM management",
            "timeline": "Kickoff within 5-7 business days. First deliverables in 2-3 weeks.",
            "price_section": f"Estimated investment: {value:,.0f} UZS" if value else "Pricing tailored after discovery call.",
            "cta": f"Contact us: {client.cta_telegram or client.cta_phone or client.cta_website or 'via your account manager'}",
        }
    elif language == "zh":
        title = f"{client.company_name} — 商业方案"
        sections = {
            "intro": f"尊敬的{recipient}，感谢您对{client.company_name}的关注。",
            "pain_problem": f"您的需求：{interest}",
            "proposed_solution": f"为乌兹别克斯坦市场提供专业的{client.business_category}营销与内容服务。",
            "package_options": "• 标准版 — 月度内容计划\n• 专业版 — 内容+广告支持\n• 旗舰版 — 全面SMM管理",
            "timeline": "5-7个工作日内启动，2-3周内交付首批成果。",
            "price_section": f"预估投资：{value:,.0f} UZS" if value else "价格将根据需求单独报价。",
            "cta": f"联系方式：{client.cta_telegram or client.cta_phone or '请通过客户经理联系'}",
        }
    else:
        title = f"Коммерческое предложение — {client.company_name}"
        sections = {
            "intro": f"Уважаемый(ая) {recipient}, благодарим за интерес к {client.company_name}.",
            "pain_problem": f"Ваш запрос: {interest}",
            "proposed_solution": f"Комплексные SMM-услуги и контент для сегмента {client.business_category} на рынке Узбекистана.",
            "package_options": "• Стандарт — месячный контент-план\n• Про — контент + поддержка рекламы\n• Премиум — полное SMM-сопровождение",
            "timeline": "Старт через 5-7 рабочих дней. Первые материалы — через 2-3 недели.",
            "price_section": f"Ориентировочная стоимость: {value:,.0f} сум" if value else "Стоимость рассчитывается индивидуально после уточнения задач.",
            "cta": f"Связаться: {client.cta_telegram or client.cta_phone or client.cta_website or 'через менеджера'}",
        }

    return {
        "title": title,
        "sections": sections,
        "estimated_value": Decimal(str(value)) if value else lead.estimated_value,
        "source": "fallback",
    }


class ProposalService:
    @staticmethod
    async def generate(
        db: AsyncSession,
        lead_id: UUID,
        data: CrmProposalGenerateRequest,
    ) -> dict[str, Any]:
        lead, client, activities = await SalesCopilotService._load_context(db, lead_id)
        language = (data.language or lead.language or "ru").lower().strip()
        if language not in LANGUAGES:
            language = "ru"

        kb_block = await ClientKnowledgeBaseService.build_prompt_block(
            db, client.id, max_chars=3000, context="proposal",
        )
        from app.services.sales_copilot_service import _build_lead_context
        context = _build_lead_context(lead, client, activities)
        valid_until = datetime.now(timezone.utc) + timedelta(days=14)

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                generated = _heuristic_proposal(lead=lead, client=client, language=language)
                sections = generated["sections"]
                title = generated["title"]
                est_value = generated.get("estimated_value")
                source = "fallback"
            else:
                _validate_api_key()
                openai = get_openai()
                user = (
                    f"{context}\n\n{kb_block or ''}\n\n"
                    f"Write proposal in language: {language}\n"
                    f"Lead estimated_value: {lead.estimated_value or 'not set'}"
                )
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": _PROPOSAL_SYSTEM},
                        {"role": "user", "content": user[:12000]},
                    ],
                    temperature=0.45,
                    max_tokens=2000,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                title = str(parsed.get("title") or f"Proposal — {client.company_name}")[:255]
                sections = {
                    "intro": parsed.get("intro"),
                    "pain_problem": parsed.get("pain_problem"),
                    "proposed_solution": parsed.get("proposed_solution"),
                    "package_options": parsed.get("package_options"),
                    "timeline": parsed.get("timeline"),
                    "price_section": parsed.get("price_section"),
                    "cta": parsed.get("cta"),
                }
                raw_val = parsed.get("estimated_value")
                if raw_val is not None:
                    try:
                        est_value = Decimal(str(raw_val))
                    except Exception:
                        est_value = lead.estimated_value
                else:
                    est_value = lead.estimated_value
                source = "ai"
        except Exception as exc:
            logger.warning("[Proposal] AI fallback: lead=%s error=%s", lead_id, exc)
            generated = _heuristic_proposal(lead=lead, client=client, language=language)
            sections = generated["sections"]
            title = generated["title"]
            est_value = generated.get("estimated_value")
            source = "fallback"

        proposal_text = _format_proposal_document(
            title=title,
            sections=sections,
            lead=lead,
            client=client,
            valid_until=valid_until,
            language=language,
        )

        proposal = CrmProposal(
            lead_id=lead.id,
            client_id=client.id,
            title=title,
            language=language,
            status="draft",
            proposal_text=proposal_text,
            estimated_value=est_value,
            valid_until=valid_until,
        )
        db.add(proposal)
        await db.flush()
        await DealEventService.record_for_lead(
            db,
            lead.id,
            "proposal",
            "Proposal generated",
            {"proposal_id": str(proposal.id), "title": title},
            lead=lead,
        )
        await db.commit()
        await db.refresh(proposal, attribute_names=["lead"])

        logger.info(
            "[Proposal] generated: id=%s lead=%s lang=%s source=%s",
            proposal.id,
            lead_id,
            language,
            source,
        )
        return _serialize_proposal(proposal)

    @staticmethod
    async def list_for_lead(db: AsyncSession, lead_id: UUID) -> dict[str, Any]:
        await SalesCopilotService._load_context(db, lead_id)
        result = await db.execute(
            select(CrmProposal)
            .options(selectinload(CrmProposal.lead))
            .where(CrmProposal.lead_id == lead_id)
            .order_by(CrmProposal.created_at.desc())
        )
        items = [_serialize_proposal(p) for p in result.scalars().all()]
        return {"items": items, "total": len(items)}

    @staticmethod
    async def get_proposal(db: AsyncSession, proposal_id: UUID) -> dict[str, Any]:
        proposal = await ProposalService._load_proposal(db, proposal_id)
        return _serialize_proposal(proposal)

    @staticmethod
    async def update_proposal(
        db: AsyncSession,
        proposal_id: UUID,
        data: CrmProposalUpdate,
    ) -> dict[str, Any]:
        proposal = await ProposalService._load_proposal(db, proposal_id)
        old_status = proposal.status
        payload = data.model_dump(exclude_unset=True)

        if "status" in payload and payload["status"] not in PROPOSAL_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid proposal status")
        if "language" in payload and payload["language"] not in LANGUAGES:
            raise HTTPException(status_code=400, detail="Invalid language")
        if "title" in payload:
            payload["title"] = payload["title"].strip()[:255]

        for key, value in payload.items():
            setattr(proposal, key, value)
        proposal.updated_at = datetime.now(timezone.utc)

        if old_status != proposal.status:
            status_titles = {
                "sent": "Proposal sent",
                "accepted": "Proposal accepted",
                "rejected": "Proposal rejected",
                "draft": "Proposal returned to draft",
            }
            await DealEventService.record_for_lead(
                db,
                proposal.lead_id,
                "proposal",
                status_titles.get(proposal.status, f"Proposal status: {proposal.status}"),
                {
                    "proposal_id": str(proposal.id),
                    "from": old_status,
                    "to": proposal.status,
                },
            )

        await db.commit()
        await db.refresh(proposal, attribute_names=["lead"])

        if old_status != proposal.status:
            logger.info(
                "[Proposal] status changed: id=%s %s -> %s",
                proposal.id,
                old_status,
                proposal.status,
            )
        return _serialize_proposal(proposal)

    @staticmethod
    async def _load_proposal(db: AsyncSession, proposal_id: UUID) -> CrmProposal:
        result = await db.execute(
            select(CrmProposal)
            .options(selectinload(CrmProposal.lead))
            .where(CrmProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return proposal
