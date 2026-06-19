"""AI Sales Copilot — pipeline guidance and message drafts for CRM leads."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.crm_lead import CrmActivity, CrmLead
from app.schemas.crm import PIPELINE_STATUSES
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.brand_profile import brand_profile_from_client
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService

logger = logging.getLogger(__name__)

MESSAGE_PURPOSES = frozenset({
    "first_contact",
    "follow_up",
    "proposal",
    "objection_reply",
    "meeting_reminder",
})
LANGUAGES = frozenset({"ru", "uz", "en", "zh"})

_STATUS_NEXT: dict[str, tuple[str, str | None]] = {
    "new": ("Send a warm first contact message and confirm their interest.", "contacted"),
    "contacted": ("Qualify the lead — ask about budget, timeline, and decision maker.", "qualified"),
    "qualified": ("Prepare and send a tailored proposal with clear pricing.", "proposal_sent"),
    "proposal_sent": ("Follow up on the proposal and address any questions.", "negotiation"),
    "negotiation": ("Confirm terms and close the deal or schedule final call.", "won"),
    "won": ("Send thank-you message and discuss onboarding.", None),
    "lost": ("Archive lead or send polite re-engagement in 3 months.", None),
}

_SUGGEST_SYSTEM = """\
You are a sales copilot for operators selling services for Chinese companies in Uzbekistan.
Analyze the lead and return ONLY JSON:
{
  "recommended_next_step": "imperative action for operator",
  "suggested_message": "draft message to send manually (match lead language)",
  "suggested_status_change": "new|contacted|qualified|proposal_sent|negotiation|won|lost or null",
  "follow_up_date": "YYYY-MM-DD or null",
  "reasoning": "2-3 sentences explaining the recommendation"
}

Rules:
- Operator sends messages manually — never imply auto-send
- Match lead language (ru/uz/en/zh) in suggested_message
- suggested_status_change only if pipeline should advance; null if stay on current status
- follow_up_date realistic (1-14 days based on urgency)
- Use client brand/KB context when relevant
- Be practical for B2B SMM/agency/local business sales in Uzbekistan
"""

_GENERATE_SYSTEM = """\
You draft sales messages for operators to review and send manually.
Return ONLY JSON:
{
  "message_text": "full message ready to copy",
  "tone": "short tone label e.g. professional, warm",
  "cta": "call-to-action phrase at end"
}

Rules:
- Never mention AI or internal systems
- Match requested language and purpose
- Under 600 characters unless proposal needs more detail
- Include client CTA (phone/telegram/website) when available
- Operator sends manually — no auto-send language
"""

_PURPOSE_HINTS: dict[str, str] = {
    "first_contact": "First outreach — introduce the company and acknowledge their interest.",
    "follow_up": "Polite follow-up after prior contact with value reminder.",
    "proposal": "Summarize offer/value and invite them to review proposal details.",
    "objection_reply": "Address price/timing/competitor concerns empathetically.",
    "meeting_reminder": "Remind about scheduled call/meeting with time confirmation.",
}


def _format_activities(activities: list[CrmActivity], limit: int = 12) -> str:
    if not activities:
        return "No activities logged yet."
    lines: list[str] = []
    for act in activities[:limit]:
        ts = act.created_at.strftime("%Y-%m-%d") if act.created_at else "?"
        lines.append(f"- [{ts}] {act.type}: {act.content[:300]}")
    return "\n".join(lines)


def _build_lead_context(lead: CrmLead, client: Client, activities: list[CrmActivity]) -> str:
    brand = brand_profile_from_client(client)
    brand_lines = "\n".join(f"{k}: {v}" for k, v in brand.items() if v)[:2000]
    return f"""\
LEAD:
- Name: {lead.name}
- Company: {lead.company or '—'}
- Phone: {lead.phone or '—'}
- Telegram: {lead.telegram or '—'}
- Email: {lead.email or '—'}
- Source: {lead.source}
- Language: {lead.language or 'ru'}
- Status: {lead.status}
- Priority: {lead.priority}
- Interest: {lead.interest or '—'}
- Notes: {(lead.notes or '—')[:800]}
- Est. value: {lead.estimated_value or '—'}
- Next follow-up: {lead.next_follow_up_at.isoformat() if lead.next_follow_up_at else '—'}

CLIENT BUSINESS:
- {client.company_name} ({client.business_category})
{brand_lines}

RECENT ACTIVITIES:
{_format_activities(activities)}
"""


def _parse_follow_up(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        text = str(raw).strip()[:10]
        dt = datetime.fromisoformat(text)
        return dt.replace(tzinfo=timezone.utc) + timedelta(hours=10)
    except (ValueError, TypeError):
        return None


def _normalize_status(raw: Any) -> str | None:
    if raw is None:
        return None
    key = str(raw).lower().strip()
    if key in PIPELINE_STATUSES and key != "null" and key != "none":
        return key
    return None


def _heuristic_suggest(lead: CrmLead, *, client: Client) -> dict[str, Any]:
    step, status_change = _STATUS_NEXT.get(lead.status, ("Review lead and plan next action.", None))
    lang = lead.language or "ru"
    name = lead.name.split()[0] if lead.name else "there"

    if lang == "uz":
        message = f"Assalomu alaykum, {name}! {client.company_name} jamoasidan murojaat qilyapmiz. Qiziqishingiz bo'yicha yordam bera olamiz."
    elif lang == "en":
        message = f"Hello {name}, this is {client.company_name}. We'd love to discuss how we can help with your request."
    elif lang == "zh":
        message = f"您好 {name}，我们是{client.company_name}，很高兴与您进一步沟通您的需求。"
    else:
        message = f"Здравствуйте, {name}! Это {client.company_name}. Готовы обсудить ваш запрос."

    follow_up = datetime.now(timezone.utc) + timedelta(days=2 if lead.priority == "high" else 5)
    return {
        "recommended_next_step": step,
        "suggested_message": message,
        "suggested_status_change": status_change,
        "follow_up_date": follow_up,
        "reasoning": f"Lead is in '{lead.status}' stage with {lead.priority} priority. Standard next action for this pipeline stage.",
        "source": "fallback",
    }


def _heuristic_message(
    lead: CrmLead,
    *,
    client: Client,
    purpose: str,
    language: str,
) -> dict[str, Any]:
    name = lead.name.split()[0] if lead.name else ""
    company = client.company_name
    cta = client.cta_telegram or client.cta_phone or client.cta_website or "contact us"

    templates: dict[str, dict[str, str]] = {
        "first_contact": {
            "ru": f"Здравствуйте{', ' + name if name else ''}! Меня зовут команда {company}. Получили ваш запрос и готовы помочь. Подскажите, удобное время для короткого звонка?",
            "uz": f"Assalomu alaykum{', ' + name if name else ''}! {company} jamoasidanmiz. So'rovingizni oldik — qisqa qo'ng'iroq qilish uchun qulay vaqt bormi?",
            "en": f"Hello{', ' + name if name else ''}! We're from {company}. We received your inquiry and would love to connect. When is a good time for a brief call?",
            "zh": f"您好{name and '，' + name or ''}！我们是{company}，已收到您的咨询，方便约个时间简短沟通吗？",
        },
        "follow_up": {
            "ru": f"Добрый день{', ' + name if name else ''}! Напоминаем о нашем предложении от {company}. Готовы ответить на вопросы.",
            "uz": f"Salom{', ' + name if name else ''}! {company} taklifimizni eslatamiz — savollaringiz bo'lsa, javob beramiz.",
            "en": f"Hi{', ' + name if name else ''}! Following up on our offer from {company}. Happy to answer any questions.",
            "zh": f"您好{name and '，' + name or ''}！跟进一下{company}的方案，如有疑问随时联系。",
        },
        "proposal": {
            "ru": f"Добрый день! Направляем предложение от {company} с учётом вашего запроса: {lead.interest or 'ваши задачи'}. Готовы обсудить детали.",
            "uz": f"Salom! {company} dan so'rovingizga mos taklif yuboramiz. Tafsilotlarni muhokama qilishga tayyormiz.",
            "en": f"Hello! Please find our proposal from {company} tailored to: {lead.interest or 'your needs'}. Ready to discuss details.",
            "zh": f"您好！附上{company}根据您的需求准备的方案，欢迎进一步讨论。",
        },
        "objection_reply": {
            "ru": "Спасибо за обратную связь. Понимаем ваши сомнения — давайте найдём формат, который подойдёт по бюджету и срокам.",
            "uz": "Fikringiz uchun rahmat. Tushunamiz — byudjet va muddatga mos yechim topamiz.",
            "en": "Thank you for sharing your concerns. We understand — let's find an option that fits your budget and timeline.",
            "zh": "感谢您的反馈，我们理解您的顾虑，可以一起找到合适的方案。",
        },
        "meeting_reminder": {
            "ru": f"Напоминаем о нашей встрече/звонке. Команда {company} будет на связи. Подтвердите, пожалуйста, время.",
            "uz": f"Uchrashuv/qo'ng'iroqni eslatamiz. {company} jamoasi aloqada bo'ladi — vaqtni tasdiqlang.",
            "en": f"Reminder about our scheduled call/meeting. The {company} team will be ready — please confirm the time.",
            "zh": f"提醒您的预约沟通，{company}团队届时与您联系，请确认时间。",
        },
    }

    purpose_templates = templates.get(purpose, templates["follow_up"])
    text = purpose_templates.get(language, purpose_templates["ru"])
    return {
        "message_text": f"{text}\n\n{cta}",
        "tone": "professional",
        "cta": str(cta),
        "source": "fallback",
    }


async def _save_copilot_activity(
    db: AsyncSession,
    lead: CrmLead,
    content: str,
) -> CrmActivity:
    activity = CrmActivity(
        lead_id=lead.id,
        type="note",
        content=content.strip(),
    )
    db.add(activity)
    lead.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("[Sales Copilot] saved activity: lead=%s", lead.id)
    return activity


class SalesCopilotService:
    @staticmethod
    async def suggest_next_step(db: AsyncSession, lead_id: UUID) -> dict[str, Any]:
        lead, client, activities = await SalesCopilotService._load_context(db, lead_id)
        logger.info("[Sales Copilot] suggest next step: lead=%s status=%s", lead_id, lead.status)

        kb_block = await ClientKnowledgeBaseService.build_prompt_block(
            db, client.id, max_chars=2500, context="sales_copilot",
        )
        context = _build_lead_context(lead, client, activities)

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                result = _heuristic_suggest(lead, client=client)
            else:
                _validate_api_key()
                openai = get_openai()
                user = f"{context}\n\n{kb_block or ''}\n\nSuggest the best next step for this lead."
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": _SUGGEST_SYSTEM},
                        {"role": "user", "content": user[:12000]},
                    ],
                    temperature=0.4,
                    max_tokens=900,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                status_change = _normalize_status(parsed.get("suggested_status_change"))
                if status_change == lead.status:
                    status_change = None
                result = {
                    "recommended_next_step": str(parsed.get("recommended_next_step") or "").strip()
                    or _heuristic_suggest(lead, client=client)["recommended_next_step"],
                    "suggested_message": str(parsed.get("suggested_message") or "").strip(),
                    "suggested_status_change": status_change,
                    "follow_up_date": _parse_follow_up(parsed.get("follow_up_date")),
                    "reasoning": str(parsed.get("reasoning") or "").strip(),
                    "source": "ai",
                }
                if not result["suggested_message"]:
                    result["suggested_message"] = _heuristic_suggest(lead, client=client)["suggested_message"]
        except Exception as exc:
            logger.warning("[Sales Copilot] suggest fallback: lead=%s error=%s", lead_id, exc)
            result = _heuristic_suggest(lead, client=client)

        activity_body = (
            "[Sales Copilot — Next step suggestion]\n"
            f"Recommended: {result['recommended_next_step']}\n"
            f"Message draft:\n{result['suggested_message']}\n"
            f"Suggested status: {result.get('suggested_status_change') or '(no change)'}\n"
            f"Follow-up: {result['follow_up_date'].date().isoformat() if result.get('follow_up_date') else '—'}\n"
            f"Reasoning: {result.get('reasoning', '')}"
        )
        activity = await _save_copilot_activity(db, lead, activity_body)
        await db.commit()
        await db.refresh(activity)

        return {
            "recommended_next_step": result["recommended_next_step"],
            "suggested_message": result["suggested_message"],
            "suggested_status_change": result.get("suggested_status_change"),
            "follow_up_date": result.get("follow_up_date"),
            "reasoning": result.get("reasoning", ""),
            "activity_id": activity.id,
            "source": result.get("source", "fallback"),
        }

    @staticmethod
    async def generate_message(
        db: AsyncSession,
        lead_id: UUID,
        *,
        purpose: str,
        language: str,
    ) -> dict[str, Any]:
        if purpose not in MESSAGE_PURPOSES:
            raise HTTPException(status_code=400, detail=f"Invalid purpose: {purpose}")
        lang = language.lower().strip()
        if lang not in LANGUAGES:
            raise HTTPException(status_code=400, detail=f"Invalid language: {language}")

        lead, client, activities = await SalesCopilotService._load_context(db, lead_id)
        logger.info(
            "[Sales Copilot] generate message: lead=%s purpose=%s lang=%s",
            lead_id,
            purpose,
            lang,
        )

        kb_block = await ClientKnowledgeBaseService.build_prompt_block(
            db, client.id, max_chars=2000, context="sales_copilot",
        )
        context = _build_lead_context(lead, client, activities)
        purpose_hint = _PURPOSE_HINTS.get(purpose, purpose)

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                result = _heuristic_message(lead, client=client, purpose=purpose, language=lang)
            else:
                _validate_api_key()
                openai = get_openai()
                user = (
                    f"{context}\n\n{kb_block or ''}\n\n"
                    f"PURPOSE: {purpose} — {purpose_hint}\n"
                    f"Write message in language: {lang}"
                )
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": _GENERATE_SYSTEM},
                        {"role": "user", "content": user[:10000]},
                    ],
                    temperature=0.5,
                    max_tokens=700,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                message_text = str(parsed.get("message_text") or "").strip()
                if not message_text:
                    result = _heuristic_message(lead, client=client, purpose=purpose, language=lang)
                else:
                    result = {
                        "message_text": message_text,
                        "tone": str(parsed.get("tone") or "professional").strip(),
                        "cta": str(parsed.get("cta") or "").strip(),
                        "source": "ai",
                    }
        except Exception as exc:
            logger.warning("[Sales Copilot] generate fallback: lead=%s error=%s", lead_id, exc)
            result = _heuristic_message(lead, client=client, purpose=purpose, language=lang)

        return {
            "message_text": result["message_text"],
            "tone": result.get("tone", "professional"),
            "cta": result.get("cta", ""),
            "purpose": purpose,
            "language": lang,
            "source": result.get("source", "fallback"),
        }

    @staticmethod
    async def save_message_as_activity(
        db: AsyncSession,
        lead_id: UUID,
        *,
        message_text: str,
        purpose: str,
        tone: str | None = None,
    ) -> dict[str, Any]:
        lead, _, _ = await SalesCopilotService._load_context(db, lead_id)
        content = (
            f"[Sales Copilot — Generated message ({purpose})]\n"
            f"Tone: {tone or 'professional'}\n\n"
            f"{message_text.strip()}"
        )
        activity = await _save_copilot_activity(db, lead, content)
        await db.commit()
        return {
            "id": activity.id,
            "lead_id": activity.lead_id,
            "type": activity.type,
            "content": activity.content,
            "created_at": activity.created_at,
        }

    @staticmethod
    async def _load_context(
        db: AsyncSession,
        lead_id: UUID,
    ) -> tuple[CrmLead, Client, list[CrmActivity]]:
        result = await db.execute(
            select(CrmLead)
            .options(selectinload(CrmLead.client))
            .where(CrmLead.id == lead_id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        client = lead.client
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        act_result = await db.execute(
            select(CrmActivity)
            .where(CrmActivity.lead_id == lead_id)
            .order_by(CrmActivity.created_at.desc())
            .limit(20)
        )
        activities = list(act_result.scalars().all())
        return lead, client, activities
