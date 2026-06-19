"""Proposal → Deal closing workflow — sent/accepted/rejected and follow-up tasks."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm_deal import CrmDeal
from app.models.proposal_document import ProposalDocument
from app.schemas.crm import CrmActivityCreate, CrmDealCreate
from app.schemas.operator_task import OperatorTaskCreate
from app.schemas.proposal import (
    ProposalCreateFollowUpRequest,
    ProposalMarkAcceptedRequest,
    ProposalMarkRejectedRequest,
    ProposalMarkSentRequest,
)
from app.services.crm_service import CrmService
from app.services.deal_service import DealService
from app.services.operator_task_service import OperatorTaskService
from app.services.proposal_generator_service import ProposalGeneratorService, _serialize

logger = logging.getLogger(__name__)

MARKER = "[Proposal Workflow]"
FOLLOW_UP_DAYS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_suggested_value(doc: ProposalDocument, deal: CrmDeal | None) -> float | None:
    if deal and deal.expected_value is not None:
        return float(deal.expected_value)
    if doc.lead and doc.lead.estimated_value is not None:
        return float(doc.lead.estimated_value)
    pricing = (doc.proposal_json or {}).get("sections", {}).get("pricing", "")
    if pricing:
        nums = re.findall(r"[\d\s]+(?:[.,]\d+)?", pricing.replace(" ", ""))
        for raw in nums:
            cleaned = raw.replace(" ", "").replace(",", ".")
            try:
                val = float(cleaned)
                if val > 0:
                    return val
            except ValueError:
                continue
    return None


def _follow_up_description(doc: ProposalDocument) -> str:
    parts = [f"Proposal: {doc.title} (id={doc.id})"]
    if doc.lead_id:
        parts.append(f"Lead id: {doc.lead_id}")
    if doc.deal_id:
        parts.append(f"Deal id: {doc.deal_id}")
    return " · ".join(parts)


class ProposalWorkflowService:
    @staticmethod
    async def _create_follow_up_task(
        db: AsyncSession,
        doc: ProposalDocument,
        due_at: datetime,
    ) -> dict[str, Any] | None:
        title = f"Follow up proposal: {doc.title}"[:255]
        try:
            return await OperatorTaskService.create_task(
                db,
                OperatorTaskCreate(
                    client_id=doc.client_id,
                    source_type="proposal",
                    source_id=doc.id,
                    title=title,
                    description=_follow_up_description(doc),
                    due_at=due_at,
                    created_by="admin",
                ),
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                logger.info(
                    "%s follow-up task already exists: proposal=%s",
                    MARKER,
                    doc.id,
                )
                return None
            raise

    @staticmethod
    async def mark_sent(
        db: AsyncSession,
        proposal_id: UUID,
        data: ProposalMarkSentRequest | None = None,
    ) -> dict[str, Any]:
        body = data or ProposalMarkSentRequest()
        doc = await ProposalGeneratorService._load_document(db, proposal_id)
        now = _now()
        doc.status = "sent"
        doc.sent_at = now
        doc.updated_at = now

        follow_up_task_id = None
        if body.create_follow_up_task:
            due = now + timedelta(days=FOLLOW_UP_DAYS)
            doc.follow_up_at = due
            task = await ProposalWorkflowService._create_follow_up_task(db, doc, due)
            if task:
                follow_up_task_id = task["id"]
                logger.info("%s follow-up task created: proposal=%s task=%s", MARKER, doc.id, follow_up_task_id)

        if doc.lead_id:
            await CrmService.add_activity(
                db,
                doc.lead_id,
                CrmActivityCreate(
                    type="proposal",
                    content=f"Proposal sent: {doc.title}",
                ),
            )

        await db.commit()
        doc = await ProposalGeneratorService._load_document(db, doc.id)
        logger.info("%s marked sent: id=%s", MARKER, doc.id)
        return {
            "proposal": _serialize(doc),
            "follow_up_task_id": follow_up_task_id,
            "deal_created_id": None,
            "message": "Proposal marked as sent. No automatic delivery was performed.",
        }

    @staticmethod
    async def mark_accepted(
        db: AsyncSession,
        proposal_id: UUID,
        data: ProposalMarkAcceptedRequest | None = None,
    ) -> dict[str, Any]:
        body = data or ProposalMarkAcceptedRequest()
        doc = await ProposalGeneratorService._load_document(db, proposal_id)
        now = _now()
        doc.status = "accepted"
        doc.accepted_at = now
        doc.updated_at = now

        deal_created_id = None
        message = "Proposal marked as accepted. Revenue and payments were not changed."

        if body.create_deal:
            if doc.deal_id:
                raise HTTPException(status_code=400, detail="Proposal already linked to a deal")
            if not doc.lead_id:
                raise HTTPException(status_code=400, detail="Proposal has no lead — cannot create deal")

            deal_title = (body.deal_title or doc.title).strip()[:255]
            expected = body.expected_value
            if expected is None:
                suggested = _parse_suggested_value(doc, None)
                expected = Decimal(str(suggested)) if suggested else None

            deal_row = await DealService.create_deal(
                db,
                CrmDealCreate(
                    lead_id=doc.lead_id,
                    client_id=doc.client_id,
                    title=deal_title,
                    status="proposal",
                    expected_value=expected,
                ),
            )
            doc.deal_id = UUID(str(deal_row["id"]))
            deal_created_id = doc.deal_id
            message = "Proposal accepted and deal created. Review deal value on Revenue manually."

        await db.commit()
        doc = await ProposalGeneratorService._load_document(db, doc.id)
        logger.info("%s marked accepted: id=%s deal=%s", MARKER, doc.id, doc.deal_id)
        return {
            "proposal": _serialize(doc),
            "follow_up_task_id": None,
            "deal_created_id": deal_created_id,
            "message": message,
        }

    @staticmethod
    async def mark_rejected(
        db: AsyncSession,
        proposal_id: UUID,
        data: ProposalMarkRejectedRequest | None = None,
    ) -> dict[str, Any]:
        body = data or ProposalMarkRejectedRequest()
        doc = await ProposalGeneratorService._load_document(db, proposal_id)
        now = _now()
        doc.status = "rejected"
        doc.rejected_at = now
        doc.updated_at = now
        if body.buyer_feedback:
            doc.buyer_feedback = body.buyer_feedback.strip()

        if doc.lead_id:
            feedback_note = ""
            if doc.buyer_feedback:
                feedback_note = f"\nBuyer feedback: {doc.buyer_feedback}"
            await CrmService.add_activity(
                db,
                doc.lead_id,
                CrmActivityCreate(
                    type="proposal",
                    content=f"Proposal rejected: {doc.title}{feedback_note}",
                ),
            )

        await db.commit()
        doc = await ProposalGeneratorService._load_document(db, doc.id)
        logger.info("%s marked rejected: id=%s", MARKER, doc.id)
        return {
            "proposal": _serialize(doc),
            "follow_up_task_id": None,
            "deal_created_id": None,
            "message": "Proposal marked as rejected.",
        }

    @staticmethod
    async def create_follow_up_task(
        db: AsyncSession,
        proposal_id: UUID,
        data: ProposalCreateFollowUpRequest | None = None,
    ) -> dict[str, Any]:
        body = data or ProposalCreateFollowUpRequest()
        doc = await ProposalGeneratorService._load_document(db, proposal_id)
        due = body.due_at or (_now() + timedelta(days=FOLLOW_UP_DAYS))
        doc.follow_up_at = due
        doc.updated_at = _now()

        task = await ProposalWorkflowService._create_follow_up_task(db, doc, due)
        if not task:
            raise HTTPException(
                status_code=409,
                detail="Follow-up task already exists for this proposal",
            )

        await db.commit()
        doc = await ProposalGeneratorService._load_document(db, doc.id)
        logger.info("%s follow-up task created: proposal=%s task=%s", MARKER, doc.id, task["id"])
        return {
            "proposal": _serialize(doc),
            "follow_up_task_id": task["id"],
            "deal_created_id": None,
            "message": "Follow-up task created.",
        }
