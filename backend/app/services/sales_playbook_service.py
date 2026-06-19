"""Sales Playbooks — reusable templates, recommend, apply (drafts only)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.buyer_outreach import BuyerOutreachMessage
from app.models.crm_lead import CrmLead
from app.models.product import Product
from app.models.proposal_document import ProposalDocument
from app.models.sales_playbook import SalesPlaybook, SalesPlaybookStep
from app.schemas.crm import CrmActivityCreate
from app.schemas.operator_task import OperatorTaskCreate
from app.schemas.proposal import ProposalGenerateRequest
from app.schemas.sales_playbook import (
    SalesPlaybookApplyRequest,
    SalesPlaybookCreate,
    SalesPlaybookGenerateRequest,
    SalesPlaybookRecommendRequest,
    SalesPlaybookStepCreate,
    SalesPlaybookStepUpdate,
    SalesPlaybookUpdate,
)
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.client_service import ClientService
from app.services.crm_service import CrmService
from app.services.operator_task_service import OperatorTaskService
from app.services.outreach_workflow_service import OutreachWorkflowService
from app.services.proposal_generator_service import ProposalGeneratorService

logger = logging.getLogger(__name__)

MARKER = "[Sales Playbook]"

STATUSES = frozenset({"draft", "active", "archived"})
STEP_TYPES = frozenset({"outreach", "follow_up", "proposal", "call", "internal_task"})
CHANNELS = frozenset({"email", "whatsapp", "wechat", "linkedin"})
LANGUAGES = frozenset({"ru", "en", "uz", "zh"})

_GENERATE_SYSTEM = """\
You design B2B export sales playbooks as step-by-step templates.
Operator executes manually — NEVER suggest automatic sending or messaging.

Return ONLY JSON:
{
  "name": "playbook title",
  "description": "short description",
  "steps": [
    {
      "step_order": 1,
      "step_type": "outreach|follow_up|proposal|call|internal_task",
      "title": "step title",
      "instructions": "operator instructions",
      "template_text": "message/proposal template draft text",
      "delay_days": 0
    }
  ]
}

Include 3-5 steps covering: first outreach, follow-up, proposal, second follow-up, close/re-engage.
Use delay_days for timing between steps (0 for first step).
Write template_text in the requested language.
Adapt tone to channel.
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_step(step: SalesPlaybookStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "playbook_id": step.playbook_id,
        "step_order": step.step_order,
        "step_type": step.step_type,
        "title": step.title,
        "instructions": step.instructions,
        "template_text": step.template_text,
        "delay_days": step.delay_days,
        "created_at": step.created_at,
        "updated_at": step.updated_at,
    }


def _serialize_playbook(
    playbook: SalesPlaybook,
    *,
    demo_mode: bool = False,
    include_steps: bool = True,
) -> dict[str, Any]:
    steps = sorted(playbook.steps or [], key=lambda s: s.step_order) if include_steps else []
    return {
        "id": playbook.id,
        "client_id": playbook.client_id,
        "client_name": playbook.client.company_name if playbook.client else None,
        "name": playbook.name,
        "description": playbook.description,
        "product_category": playbook.product_category,
        "buyer_type": playbook.buyer_type,
        "country": playbook.country,
        "language": playbook.language,
        "channel": playbook.channel,
        "status": playbook.status,
        "step_count": len(steps) if include_steps else len(playbook.steps or []),
        "steps": [_serialize_step(s) for s in steps] if include_steps else [],
        "demo_mode": demo_mode,
        "created_at": playbook.created_at,
        "updated_at": playbook.updated_at,
    }


def _heuristic_playbook(data: SalesPlaybookGenerateRequest) -> dict[str, Any]:
    cat = data.product_category
    buyer = data.buyer_type
    country = data.country
    channel = data.channel
    lang = data.language

    if lang == "ru":
        steps = [
            {
                "step_order": 1,
                "step_type": "outreach",
                "title": "Первый контакт",
                "instructions": f"Отправьте первое сообщение {buyer} в {country} через {channel}.",
                "template_text": (
                    f"Здравствуйте,\n\nМы производитель в категории {cat} и ищем партнёров "
                    f"типа {buyer} в {country}. Готовы обсудить условия поставки и MOQ.\n\n"
                    "С уважением"
                ),
                "delay_days": 0,
            },
            {
                "step_order": 2,
                "step_type": "follow_up",
                "title": "Follow-up через 3 дня",
                "instructions": "Напомните о первом сообщении, предложите созвон.",
                "template_text": (
                    "Добрый день,\n\nНапоминаю о нашем предложении. "
                    "Можем отправить образцы и прайс. Удобно созвониться на этой неделе?"
                ),
                "delay_days": 3,
            },
            {
                "step_order": 3,
                "step_type": "proposal",
                "title": "Коммерческое предложение",
                "instructions": "Подготовьте и отправьте КП вручную после согласования.",
                "template_text": f"Коммерческое предложение для {buyer} — категория {cat}, рынок {country}.",
                "delay_days": 7,
            },
            {
                "step_order": 4,
                "step_type": "follow_up",
                "title": "Follow-up по КП",
                "instructions": "Уточните получение КП и ответьте на вопросы.",
                "template_text": "Добрый день,\n\nХотел уточнить, удалось ли ознакомиться с нашим предложением?",
                "delay_days": 14,
            },
            {
                "step_order": 5,
                "step_type": "outreach",
                "title": "Re-engage",
                "instructions": "Мягко возобновите контакт, предложите альтернативу.",
                "template_text": (
                    "Здравствуйте,\n\nХотели бы возобновить диалог о сотрудничестве. "
                    "Готовы обсудить обновлённые условия."
                ),
                "delay_days": 21,
            },
        ]
        name = data.name or f"Playbook: {cat} → {buyer} ({country})"
        desc = f"Шаблон продаж для {buyer} в {country}, канал {channel}."
    else:
        steps = [
            {
                "step_order": 1,
                "step_type": "outreach",
                "title": "First outreach",
                "instructions": f"Send first message to {buyer} in {country} via {channel}.",
                "template_text": (
                    f"Hello,\n\nWe manufacture {cat} products and are looking for {buyer} "
                    f"partners in {country}. Happy to discuss MOQ and pricing.\n\nBest regards"
                ),
                "delay_days": 0,
            },
            {
                "step_order": 2,
                "step_type": "follow_up",
                "title": "Follow-up (3 days)",
                "instructions": "Follow up on first message, offer a call.",
                "template_text": (
                    "Hello,\n\nFollowing up on my previous message. "
                    "We can share samples and pricing. Would a brief call work this week?"
                ),
                "delay_days": 3,
            },
            {
                "step_order": 3,
                "step_type": "proposal",
                "title": "Send proposal",
                "instructions": "Prepare and send commercial proposal manually.",
                "template_text": f"Commercial proposal for {buyer} — {cat}, market {country}.",
                "delay_days": 7,
            },
            {
                "step_order": 4,
                "step_type": "follow_up",
                "title": "Proposal follow-up",
                "instructions": "Confirm proposal receipt and answer questions.",
                "template_text": "Hello,\n\nWanted to check if you had a chance to review our proposal?",
                "delay_days": 14,
            },
            {
                "step_order": 5,
                "step_type": "outreach",
                "title": "Re-engage",
                "instructions": "Soft re-engagement with updated offer.",
                "template_text": (
                    "Hello,\n\nWe would like to reconnect about a potential partnership. "
                    "Open to discuss updated terms."
                ),
                "delay_days": 21,
            },
        ]
        name = data.name or f"Playbook: {cat} → {buyer} ({country})"
        desc = f"Sales template for {buyer} in {country}, channel {channel}."

    return {"name": name, "description": desc, "steps": steps}


def _outreach_type_for_step(step: SalesPlaybookStep, order: int) -> str:
    if step.step_type == "follow_up":
        return "follow_up"
    if order > 1 and "re-engage" in step.title.lower():
        return "re_engagement"
    if order > 3:
        return "re_engagement"
    return "first_contact"


def _score_playbook(
    playbook: SalesPlaybook,
    *,
    client_id: UUID | None,
    product_category: str | None,
    buyer_type: str | None,
    country: str | None,
    language: str | None,
    channel: str | None,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if playbook.status != "active":
        return 0, []

    if client_id:
        if playbook.client_id is None:
            score += 1
            reasons.append("global template")
        elif playbook.client_id == client_id:
            score += 3
            reasons.append("client match")

    for field, value, label in (
        (playbook.product_category, product_category, "product category"),
        (playbook.buyer_type, buyer_type, "buyer type"),
        (playbook.country, country, "country"),
        (playbook.language, language, "language"),
        (playbook.channel, channel, "channel"),
    ):
        if not value:
            continue
        if field and field.lower() == value.lower():
            score += 2
            reasons.append(f"{label} match")
        elif field is None:
            score += 1

    return score, reasons


class SalesPlaybookService:
    @staticmethod
    async def _load_playbook(db: AsyncSession, playbook_id: UUID) -> SalesPlaybook:
        result = await db.execute(
            select(SalesPlaybook)
            .options(
                selectinload(SalesPlaybook.client),
                selectinload(SalesPlaybook.steps),
            )
            .where(SalesPlaybook.id == playbook_id)
        )
        playbook = result.scalar_one_or_none()
        if not playbook:
            raise HTTPException(status_code=404, detail="Playbook not found")
        return playbook

    @staticmethod
    async def _load_step(db: AsyncSession, step_id: UUID) -> SalesPlaybookStep:
        result = await db.execute(
            select(SalesPlaybookStep)
            .options(selectinload(SalesPlaybookStep.playbook))
            .where(SalesPlaybookStep.id == step_id)
        )
        step = result.scalar_one_or_none()
        if not step:
            raise HTTPException(status_code=404, detail="Playbook step not found")
        return step

    @staticmethod
    async def list_playbooks(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        query = (
            select(SalesPlaybook)
            .options(selectinload(SalesPlaybook.client), selectinload(SalesPlaybook.steps))
            .order_by(SalesPlaybook.updated_at.desc())
        )
        count_q = select(func.count()).select_from(SalesPlaybook)
        if client_id:
            query = query.where(or_(SalesPlaybook.client_id.is_(None), SalesPlaybook.client_id == client_id))
            count_q = count_q.where(or_(SalesPlaybook.client_id.is_(None), SalesPlaybook.client_id == client_id))
        if status:
            query = query.where(SalesPlaybook.status == status)
            count_q = count_q.where(SalesPlaybook.status == status)

        total = (await db.execute(count_q)).scalar() or 0
        result = await db.execute(query.offset(skip).limit(limit))
        playbooks = list(result.scalars().all())
        items = [_serialize_playbook(p, include_steps=False) for p in playbooks]
        return {"items": items, "total": total}

    @staticmethod
    async def get_playbook(db: AsyncSession, playbook_id: UUID) -> dict[str, Any]:
        playbook = await SalesPlaybookService._load_playbook(db, playbook_id)
        return _serialize_playbook(playbook)

    @staticmethod
    async def create_playbook(db: AsyncSession, data: SalesPlaybookCreate) -> dict[str, Any]:
        if data.channel not in CHANNELS:
            raise HTTPException(status_code=400, detail="Invalid channel")
        if data.status not in STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        if data.client_id:
            await ClientService.get(db, data.client_id)

        playbook = SalesPlaybook(
            client_id=data.client_id,
            name=data.name.strip(),
            description=data.description,
            product_category=data.product_category,
            buyer_type=data.buyer_type,
            country=data.country,
            language=data.language if data.language in LANGUAGES else "en",
            channel=data.channel,
            status=data.status,
        )
        db.add(playbook)
        await db.flush()

        for step_data in data.steps:
            if step_data.step_type not in STEP_TYPES:
                raise HTTPException(status_code=400, detail=f"Invalid step_type: {step_data.step_type}")
            db.add(SalesPlaybookStep(
                playbook_id=playbook.id,
                step_order=step_data.step_order,
                step_type=step_data.step_type,
                title=step_data.title.strip(),
                instructions=step_data.instructions,
                template_text=step_data.template_text,
                delay_days=step_data.delay_days,
            ))

        await db.commit()
        playbook = await SalesPlaybookService._load_playbook(db, playbook.id)
        return _serialize_playbook(playbook)

    @staticmethod
    async def update_playbook(
        db: AsyncSession,
        playbook_id: UUID,
        data: SalesPlaybookUpdate,
    ) -> dict[str, Any]:
        playbook = await SalesPlaybookService._load_playbook(db, playbook_id)
        payload = data.model_dump(exclude_unset=True)
        if "channel" in payload and payload["channel"] not in CHANNELS:
            raise HTTPException(status_code=400, detail="Invalid channel")
        if "status" in payload and payload["status"] not in STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")

        for key, value in payload.items():
            setattr(playbook, key, value)
        playbook.updated_at = _now()
        await db.commit()
        playbook = await SalesPlaybookService._load_playbook(db, playbook_id)
        return _serialize_playbook(playbook)

    @staticmethod
    async def create_step(
        db: AsyncSession,
        playbook_id: UUID,
        data: SalesPlaybookStepCreate,
    ) -> dict[str, Any]:
        playbook = await SalesPlaybookService._load_playbook(db, playbook_id)
        if data.step_type not in STEP_TYPES:
            raise HTTPException(status_code=400, detail="Invalid step_type")

        step = SalesPlaybookStep(
            playbook_id=playbook.id,
            step_order=data.step_order,
            step_type=data.step_type,
            title=data.title.strip(),
            instructions=data.instructions,
            template_text=data.template_text,
            delay_days=data.delay_days,
        )
        db.add(step)
        playbook.updated_at = _now()
        await db.commit()
        await db.refresh(step)
        logger.info("%s step created: playbook=%s step=%s", MARKER, playbook_id, step.id)
        return _serialize_step(step)

    @staticmethod
    async def update_step(
        db: AsyncSession,
        step_id: UUID,
        data: SalesPlaybookStepUpdate,
    ) -> dict[str, Any]:
        step = await SalesPlaybookService._load_step(db, step_id)
        payload = data.model_dump(exclude_unset=True)
        if "step_type" in payload and payload["step_type"] not in STEP_TYPES:
            raise HTTPException(status_code=400, detail="Invalid step_type")

        for key, value in payload.items():
            setattr(step, key, value)
        step.updated_at = _now()
        if step.playbook:
            step.playbook.updated_at = _now()
        await db.commit()
        await db.refresh(step)
        return _serialize_step(step)

    @staticmethod
    async def generate(db: AsyncSession, data: SalesPlaybookGenerateRequest) -> dict[str, Any]:
        if data.channel not in CHANNELS:
            raise HTTPException(status_code=400, detail="Invalid channel")
        lang = data.language if data.language in LANGUAGES else "en"
        if data.client_id:
            await ClientService.get(db, data.client_id)

        demo_mode = False
        parsed: dict[str, Any]
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("demo")
            _validate_api_key()
            openai = get_openai()
            user_prompt = (
                f"Product category: {data.product_category}\n"
                f"Buyer type: {data.buyer_type}\n"
                f"Country: {data.country}\n"
                f"Language: {lang}\n"
                f"Channel: {data.channel}\n"
            )
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _GENERATE_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.5,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            if not parsed.get("steps"):
                raise ValueError("empty steps")
        except Exception as exc:
            demo_mode = True
            logger.info("%s AI fallback: %s", MARKER, exc)
            parsed = _heuristic_playbook(data)

        steps_in = parsed.get("steps") or []
        step_creates: list[SalesPlaybookStepCreate] = []
        for raw in steps_in[:5]:
            st = str(raw.get("step_type") or "outreach")
            if st not in STEP_TYPES:
                st = "follow_up" if "follow" in st else "outreach"
            step_creates.append(SalesPlaybookStepCreate(
                step_order=int(raw.get("step_order") or len(step_creates) + 1),
                step_type=st,  # type: ignore[arg-type]
                title=str(raw.get("title") or f"Step {len(step_creates) + 1}")[:255],
                instructions=str(raw.get("instructions") or "").strip() or None,
                template_text=str(raw.get("template_text") or "").strip() or None,
                delay_days=int(raw["delay_days"]) if raw.get("delay_days") is not None else None,
            ))

        create_data = SalesPlaybookCreate(
            client_id=data.client_id,
            name=str(parsed.get("name") or data.name or f"Playbook: {data.product_category}")[:255],
            description=str(parsed.get("description") or "").strip() or None,
            product_category=data.product_category,
            buyer_type=data.buyer_type,
            country=data.country,
            language=lang,
            channel=data.channel,
            status="draft",
            steps=step_creates,
        )
        result = await SalesPlaybookService.create_playbook(db, create_data)
        result["demo_mode"] = demo_mode
        logger.info("%s generated: id=%s demo=%s", MARKER, result["id"], demo_mode)
        return result

    @staticmethod
    async def recommend(
        db: AsyncSession,
        data: SalesPlaybookRecommendRequest,
    ) -> dict[str, Any]:
        product_category = data.product_category
        buyer_type = data.buyer_type
        country = data.country
        language = data.language
        channel = data.channel
        client_id = data.client_id

        if data.product_id:
            pr = await db.execute(select(Product).where(Product.id == data.product_id))
            product = pr.scalar_one_or_none()
            if product:
                client_id = client_id or product.client_id
                product_category = product_category or product.category

        if data.lead_id:
            lr = await db.execute(select(CrmLead).where(CrmLead.id == data.lead_id))
            lead = lr.scalar_one_or_none()
            if lead:
                client_id = client_id or lead.client_id
                country = country or None
                language = language or lead.language

        result = await db.execute(
            select(SalesPlaybook)
            .options(selectinload(SalesPlaybook.client), selectinload(SalesPlaybook.steps))
            .where(SalesPlaybook.status == "active")
        )
        scored: list[tuple[int, SalesPlaybook, list[str]]] = []
        for playbook in result.scalars().all():
            score, reasons = _score_playbook(
                playbook,
                client_id=client_id,
                product_category=product_category,
                buyer_type=buyer_type,
                country=country,
                language=language,
                channel=channel,
            )
            if score > 0:
                scored.append((score, playbook, reasons))

        scored.sort(key=lambda x: (-x[0], x[1].updated_at.timestamp() if x[1].updated_at else 0))
        items = [_serialize_playbook(p) for _, p, _ in scored[:10]]
        match_reasons = {str(p.id): reasons for _, p, reasons in scored[:10]}
        return {"items": items, "match_reasons": match_reasons}

    @staticmethod
    async def apply_to_lead(
        db: AsyncSession,
        playbook_id: UUID,
        lead_id: UUID,
        data: SalesPlaybookApplyRequest | None = None,
    ) -> dict[str, Any]:
        body = data or SalesPlaybookApplyRequest()
        playbook = await SalesPlaybookService._load_playbook(db, playbook_id)
        if playbook.status == "archived":
            raise HTTPException(status_code=400, detail="Cannot apply archived playbook")

        lead_r = await db.execute(select(CrmLead).where(CrmLead.id == lead_id))
        lead = lead_r.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        if playbook.client_id and playbook.client_id != lead.client_id:
            raise HTTPException(status_code=400, detail="Playbook belongs to a different client")

        product_id = body.product_id
        product: Product | None = None
        if product_id:
            pr = await db.execute(select(Product).where(Product.id == product_id, Product.active.is_(True)))
            product = pr.scalar_one_or_none()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
            if product.client_id != lead.client_id:
                raise HTTPException(status_code=400, detail="Product belongs to a different client")

        steps = sorted(playbook.steps or [], key=lambda s: s.step_order)
        if not steps:
            raise HTTPException(status_code=400, detail="Playbook has no steps")

        outreach_ids: list[UUID] = []
        proposal_ids: list[UUID] = []
        task_ids: list[UUID] = []
        base = _now()
        country = playbook.country or "—"

        for step in steps:
            due = base + timedelta(days=step.delay_days or 0)

            if step.step_type in ("outreach", "follow_up"):
                text = (step.template_text or step.instructions or step.title).strip()
                if not text:
                    text = step.title
                subject = None
                if playbook.channel == "email":
                    subject = step.title[:500]

                outreach = BuyerOutreachMessage(
                    client_id=lead.client_id,
                    lead_id=lead.id,
                    product_id=product_id,
                    buyer_name=lead.name,
                    buyer_company=lead.company,
                    country=country,
                    channel=playbook.channel,
                    language=playbook.language,
                    outreach_type=_outreach_type_for_step(step, step.step_order),
                    subject=subject,
                    message_text=text,
                    status="draft",
                    sales_playbook_id=playbook.id,
                    sales_playbook_step_id=step.id,
                )
                db.add(outreach)
                await db.flush()
                await OutreachWorkflowService.log_generated(db, outreach.id)
                outreach_ids.append(outreach.id)

            elif step.step_type == "proposal":
                if product_id:
                    try:
                        doc = await ProposalGeneratorService.generate(
                            db,
                            ProposalGenerateRequest(
                                client_id=lead.client_id,
                                lead_id=lead.id,
                                product_ids=[product_id],
                                language=playbook.language,
                                proposal_type="export_offer",
                                custom_requirements=step.instructions,
                            ),
                        )
                        pid = UUID(str(doc["id"]))
                        pr = await db.execute(select(ProposalDocument).where(ProposalDocument.id == pid))
                        pdoc = pr.scalar_one_or_none()
                        if pdoc:
                            pdoc.sales_playbook_id = playbook.id
                            pdoc.sales_playbook_step_id = step.id
                        proposal_ids.append(pid)
                    except Exception as exc:
                        logger.info("%s proposal generate fallback: %s", MARKER, exc)
                        pdoc = ProposalDocument(
                            client_id=lead.client_id,
                            lead_id=lead.id,
                            product_id=product_id,
                            title=step.title[:255],
                            language=playbook.language,
                            status="draft",
                            proposal_json={"sections": {}},
                            proposal_text=(step.template_text or step.instructions or step.title),
                            sales_playbook_id=playbook.id,
                            sales_playbook_step_id=step.id,
                        )
                        db.add(pdoc)
                        await db.flush()
                        proposal_ids.append(pdoc.id)
                else:
                    pdoc = ProposalDocument(
                        client_id=lead.client_id,
                        lead_id=lead.id,
                        title=step.title[:255],
                        language=playbook.language,
                        status="draft",
                        proposal_json={"sections": {}},
                        proposal_text=(step.template_text or step.instructions or step.title),
                        sales_playbook_id=playbook.id,
                        sales_playbook_step_id=step.id,
                    )
                    db.add(pdoc)
                    await db.flush()
                    proposal_ids.append(pdoc.id)

            elif step.step_type in ("call", "internal_task"):
                try:
                    task = await OperatorTaskService.create_task(
                        db,
                        OperatorTaskCreate(
                            client_id=lead.client_id,
                            source_type="sales_playbook",
                            source_id=step.id,
                            title=step.title[:255],
                            description=(step.instructions or step.template_text or "").strip() or None,
                            due_at=due,
                            created_by="admin",
                        ),
                    )
                    task_ids.append(UUID(str(task["id"])))
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    logger.info("%s task skipped duplicate: step=%s", MARKER, step.id)

        await CrmService.add_activity(
            db,
            lead.id,
            CrmActivityCreate(
                type="note",
                content=(
                    f"Sales playbook applied: {playbook.name} "
                    f"({len(outreach_ids)} outreach, {len(proposal_ids)} proposals, {len(task_ids)} tasks — drafts only)"
                ),
            ),
        )

        await db.commit()
        logger.info(
            "%s applied: playbook=%s lead=%s outreach=%s proposals=%s tasks=%s",
            MARKER, playbook_id, lead_id, len(outreach_ids), len(proposal_ids), len(task_ids),
        )
        return {
            "playbook_id": playbook_id,
            "lead_id": lead_id,
            "outreach_ids": outreach_ids,
            "proposal_ids": proposal_ids,
            "task_ids": task_ids,
            "message": "Playbook applied — drafts and tasks created. No messages were sent.",
        }
