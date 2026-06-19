"""CRM document drafts — contracts and invoices from proposals."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.crm_document import CrmDocument
from app.models.crm_lead import CrmLead
from app.models.crm_proposal import CrmProposal
from app.schemas.crm import CrmDocumentGenerateRequest, CrmDocumentUpdate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.deal_event_service import DealEventService

logger = logging.getLogger(__name__)

DOCUMENT_TYPES = frozenset({"contract", "invoice", "offer"})
DOCUMENT_STATUSES = frozenset({"draft", "sent", "signed", "paid", "canceled"})
LANGUAGES = frozenset({"ru", "uz", "en", "zh"})
LEGAL_DISCLAIMER = (
    "\n\n---\n"
    "**DRAFT ONLY — NOT LEGALLY BINDING.** "
    "Review with qualified legal counsel before signing. "
    "This document was generated as a draft for operator review only."
)

_CONTRACT_SYSTEM = """\
Generate a DRAFT service contract outline. Return ONLY JSON:
{
  "title": "contract title",
  "parties": "provider and client party descriptions",
  "scope_of_work": "services scope from proposal",
  "timeline": "delivery timeline",
  "payment_terms": "payment schedule and method",
  "responsibilities": "each party responsibilities",
  "termination": "basic termination clause",
  "amount": null or number
}
Write in requested language. Do not claim legal validity.
"""

_INVOICE_SYSTEM = """\
Generate a DRAFT invoice outline. Return ONLY JSON:
{
  "title": "invoice title",
  "client_block": "bill-to client/lead details",
  "service_name": "service description",
  "line_items": "itemized services and amounts as text",
  "amount": number,
  "payment_notes": "how to pay, bank/details placeholder"
}
Write in requested language.
"""


def _serialize_document(doc: CrmDocument) -> dict[str, Any]:
    return {
        "id": doc.id,
        "proposal_id": doc.proposal_id,
        "lead_id": doc.lead_id,
        "client_id": doc.client_id,
        "lead_name": doc.lead.name if doc.lead else None,
        "proposal_title": doc.proposal.title if doc.proposal else None,
        "document_type": doc.document_type,
        "title": doc.title,
        "language": doc.language,
        "status": doc.status,
        "document_text": doc.document_text,
        "amount": doc.amount,
        "currency": doc.currency,
        "due_date": doc.due_date,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }


def _format_contract(
    *,
    title: str,
    sections: dict[str, Any],
    lead: CrmLead,
    client: Client,
    language: str,
) -> str:
    labels = {
        "ru": ("Стороны", "Предмет договора", "Сроки", "Оплата", "Обязанности сторон", "Расторжение"),
        "uz": ("Tomonlar", "Shartnoma predmeti", "Muddatlar", "To'lov", "Tomonlar majburiyatlari", "Bekor qilish"),
        "en": ("Parties", "Scope of work", "Timeline", "Payment terms", "Responsibilities", "Termination"),
        "zh": ("双方", "工作范围", "时间线", "付款条款", "责任", "终止"),
    }
    L = labels.get(language, labels["ru"])
    provider = client.company_name
    client_party = lead.company or lead.name

    parts = [
        f"# {title}",
        "",
        f"## {L[0]}",
        f"**Provider:** {provider}",
        f"**Client:** {client_party} ({lead.name})",
        str(sections.get("parties") or "").strip(),
        "",
        f"## {L[1]}",
        str(sections.get("scope_of_work") or "").strip(),
        "",
        f"## {L[2]}",
        str(sections.get("timeline") or "").strip(),
        "",
        f"## {L[3]}",
        str(sections.get("payment_terms") or "").strip(),
        "",
        f"## {L[4]}",
        str(sections.get("responsibilities") or "").strip(),
        "",
        f"## {L[5]}",
        str(sections.get("termination") or "Either party may terminate with 14 days written notice.").strip(),
        "",
        "*Draft only, review legally before signing.*",
    ]
    return "\n".join(parts).strip() + LEGAL_DISCLAIMER


def _format_invoice(
    *,
    title: str,
    sections: dict[str, Any],
    lead: CrmLead,
    client: Client,
    amount: Decimal | None,
    currency: str,
    due_date: datetime,
    language: str,
) -> str:
    amt_str = f"{float(amount):,.2f} {currency}" if amount else f"TBD {currency}"
    parts = [
        f"# {title}",
        "",
        "## Bill to",
        str(sections.get("client_block") or f"{lead.name}\n{lead.company or ''}\n{lead.phone or ''}\n{lead.email or ''}").strip(),
        "",
        f"**From:** {client.company_name}",
        f"**Due date:** {due_date.date().isoformat()}",
        "",
        "## Service",
        str(sections.get("service_name") or "Professional services per accepted proposal").strip(),
        "",
        "## Line items",
        str(sections.get("line_items") or f"Services — {amt_str}").strip(),
        "",
        f"## Total: {amt_str}",
        "",
        "## Payment notes",
        str(sections.get("payment_notes") or "Payment due by due date. Contact provider for bank details.").strip(),
        "",
        "*Draft only. Review before signing.*",
    ]
    return "\n".join(parts).strip() + LEGAL_DISCLAIMER


def _heuristic_document(
    *,
    doc_type: str,
    proposal: CrmProposal,
    lead: CrmLead,
    client: Client,
    language: str,
    amount: Decimal | None,
    due_date: datetime,
) -> tuple[str, str, dict[str, Any]]:
    interest = lead.interest or proposal.title
    if doc_type == "invoice":
        title = f"Invoice — {client.company_name}"
        sections = {
            "client_block": f"{lead.name}\n{lead.company or ''}",
            "service_name": interest[:200],
            "line_items": f"1. SMM / marketing services — {float(amount or 0):,.0f} UZS",
            "payment_notes": f"Pay within 14 days. Contact: {client.cta_phone or client.cta_telegram or 'provider'}",
        }
        text = _format_invoice(
            title=title,
            sections=sections,
            lead=lead,
            client=client,
            amount=amount,
            currency="UZS",
            due_date=due_date,
            language=language,
        )
        return title, text, sections

    title = f"Service Contract — {client.company_name} / {lead.name}"
    sections = {
        "parties": f"Provider: {client.company_name}. Client: {lead.name}.",
        "scope_of_work": f"Services as described in proposal: {interest[:300]}",
        "timeline": "Per agreed proposal timeline.",
        "payment_terms": f"Total: {float(amount or 0):,.0f} UZS. 50% upfront, 50% on delivery unless otherwise agreed.",
        "responsibilities": "Provider delivers agreed services. Client provides materials and timely feedback.",
        "termination": "Either party may terminate with 14 days written notice.",
    }
    text = _format_contract(
        title=title,
        sections=sections,
        lead=lead,
        client=client,
        language=language,
    )
    return title, text, sections


class DocumentService:
    @staticmethod
    async def generate(
        db: AsyncSession,
        proposal_id: UUID,
        data: CrmDocumentGenerateRequest,
    ) -> dict[str, Any]:
        proposal, lead, client = await DocumentService._load_proposal_context(db, proposal_id)
        doc_type = data.document_type
        if doc_type not in DOCUMENT_TYPES:
            raise HTTPException(status_code=400, detail="Invalid document_type")

        language = (data.language or proposal.language or lead.language or "ru").lower()
        if language not in LANGUAGES:
            language = "ru"

        amount = proposal.estimated_value or lead.estimated_value
        due_date = datetime.now(timezone.utc) + timedelta(days=14)

        kb_block = await ClientKnowledgeBaseService.build_prompt_block(
            db, client.id, max_chars=2500, context="contract_invoice",
        )
        context = (
            f"PROPOSAL TITLE: {proposal.title}\n"
            f"PROPOSAL STATUS: {proposal.status}\n"
            f"PROPOSAL TEXT (excerpt):\n{proposal.proposal_text[:3000]}\n\n"
            f"LEAD: {lead.name}, company={lead.company}, interest={lead.interest}\n"
            f"CLIENT: {client.company_name}, category={client.business_category}\n"
            f"AMOUNT: {amount or 'TBD'} UZS\n"
            f"LANGUAGE: {language}\n"
            f"{kb_block or ''}"
        )

        system = _INVOICE_SYSTEM if doc_type == "invoice" else _CONTRACT_SYSTEM

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                title, document_text, _ = _heuristic_document(
                    doc_type=doc_type,
                    proposal=proposal,
                    lead=lead,
                    client=client,
                    language=language,
                    amount=amount,
                    due_date=due_date,
                )
                source = "fallback"
            else:
                _validate_api_key()
                openai = get_openai()
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": context[:10000]},
                    ],
                    temperature=0.35,
                    max_tokens=1800,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                title = str(parsed.get("title") or f"{doc_type.title()} — {lead.name}")[:255]
                raw_amt = parsed.get("amount")
                if raw_amt is not None:
                    try:
                        amount = Decimal(str(raw_amt))
                    except Exception:
                        pass
                if doc_type == "invoice":
                    document_text = _format_invoice(
                        title=title,
                        sections=parsed,
                        lead=lead,
                        client=client,
                        amount=amount,
                        currency="UZS",
                        due_date=due_date,
                        language=language,
                    )
                else:
                    document_text = _format_contract(
                        title=title,
                        sections=parsed,
                        lead=lead,
                        client=client,
                        language=language,
                    )
                source = "ai"
        except Exception as exc:
            logger.warning("[Document] AI fallback: proposal=%s error=%s", proposal_id, exc)
            title, document_text, _ = _heuristic_document(
                doc_type=doc_type,
                proposal=proposal,
                lead=lead,
                client=client,
                language=language,
                amount=amount,
                due_date=due_date,
            )
            source = "fallback"

        doc = CrmDocument(
            proposal_id=proposal.id,
            lead_id=lead.id,
            client_id=client.id,
            document_type=doc_type,
            title=title,
            language=language,
            status="draft",
            document_text=document_text,
            amount=amount,
            currency="UZS",
            due_date=due_date if doc_type == "invoice" else None,
        )
        db.add(doc)
        await db.flush()
        event_type = "invoice" if doc_type == "invoice" else "contract"
        event_title = "Invoice generated" if doc_type == "invoice" else "Contract draft generated"
        await DealEventService.record_for_lead(
            db,
            lead.id,
            event_type,
            event_title,
            {"document_id": str(doc.id), "document_type": doc_type, "title": title},
            lead=lead,
        )
        await db.commit()
        await db.refresh(doc, attribute_names=["lead", "proposal"])

        logger.info(
            "[Document] generated: id=%s type=%s proposal=%s source=%s",
            doc.id,
            doc_type,
            proposal_id,
            source,
        )
        return _serialize_document(doc)

    @staticmethod
    async def list_for_proposal(db: AsyncSession, proposal_id: UUID) -> dict[str, Any]:
        await DocumentService._load_proposal_context(db, proposal_id)
        result = await db.execute(
            select(CrmDocument)
            .options(selectinload(CrmDocument.lead), selectinload(CrmDocument.proposal))
            .where(CrmDocument.proposal_id == proposal_id)
            .order_by(CrmDocument.created_at.desc())
        )
        items = [_serialize_document(d) for d in result.scalars().all()]
        return {"items": items, "total": len(items)}

    @staticmethod
    async def get_document(db: AsyncSession, document_id: UUID) -> dict[str, Any]:
        doc = await DocumentService._load_document(db, document_id)
        return _serialize_document(doc)

    @staticmethod
    async def update_document(
        db: AsyncSession,
        document_id: UUID,
        data: CrmDocumentUpdate,
    ) -> dict[str, Any]:
        doc = await DocumentService._load_document(db, document_id)
        old_status = doc.status
        payload = data.model_dump(exclude_unset=True)

        if "status" in payload and payload["status"] not in DOCUMENT_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid document status")
        if "language" in payload and payload["language"] not in LANGUAGES:
            raise HTTPException(status_code=400, detail="Invalid language")
        if "title" in payload:
            payload["title"] = payload["title"].strip()[:255]

        for key, value in payload.items():
            setattr(doc, key, value)
        doc.updated_at = datetime.now(timezone.utc)

        if old_status != doc.status:
            event_type = "invoice" if doc.document_type == "invoice" else "contract"
            status_titles = {
                "sent": f"{doc.document_type.title()} sent",
                "signed": "Contract signed",
                "paid": "Invoice paid",
                "canceled": f"{doc.document_type.title()} canceled",
                "draft": f"{doc.document_type.title()} returned to draft",
            }
            await DealEventService.record_for_lead(
                db,
                doc.lead_id,
                event_type,
                status_titles.get(doc.status, f"{doc.document_type} status: {doc.status}"),
                {
                    "document_id": str(doc.id),
                    "from": old_status,
                    "to": doc.status,
                },
            )

        await db.commit()
        await db.refresh(doc, attribute_names=["lead", "proposal"])

        if old_status != doc.status:
            logger.info(
                "[Document] status changed: id=%s %s -> %s",
                doc.id,
                old_status,
                doc.status,
            )
        return _serialize_document(doc)

    @staticmethod
    async def _load_proposal_context(
        db: AsyncSession,
        proposal_id: UUID,
    ) -> tuple[CrmProposal, CrmLead, Client]:
        result = await db.execute(
            select(CrmProposal)
            .options(
                selectinload(CrmProposal.lead).selectinload(CrmLead.client),
            )
            .where(CrmProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        lead = proposal.lead
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        client = lead.client
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        return proposal, lead, client

    @staticmethod
    async def _load_document(db: AsyncSession, document_id: UUID) -> CrmDocument:
        result = await db.execute(
            select(CrmDocument)
            .options(selectinload(CrmDocument.lead), selectinload(CrmDocument.proposal))
            .where(CrmDocument.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc
