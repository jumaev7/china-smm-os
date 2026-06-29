"""Executive CRM pipeline — stage transitions, timeline, tenant-scoped deals."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.sales_crm import (
    PIPELINE_STAGES,
    STAGE_SOURCES,
    SalesCustomer,
    SalesDeal,
    SalesLead,
)
from app.schemas.crm_pipeline import (
    ALLOWED_STAGE_TRANSITIONS,
    DEFAULT_STAGE_PROBABILITY,
    TERMINAL_STAGES,
    PipelineMeetingCreate,
    PipelineNoteCreate,
    PipelineStageUpdate,
)
from app.services.crm_pipeline_timeline_service import CrmPipelineTimelineService
from app.services.sales_crm_service import SalesCrmService


class CrmPipelineService:
    @staticmethod
    def _assert_stage(stage: str) -> None:
        if stage not in PIPELINE_STAGES:
            raise HTTPException(status_code=422, detail=f"Invalid deal stage: {stage}")

    @staticmethod
    def _assert_stage_source(source: str) -> None:
        if source not in STAGE_SOURCES:
            raise HTTPException(status_code=422, detail=f"Invalid stage source: {source}")

    @classmethod
    def validate_transition(cls, from_stage: str, to_stage: str) -> None:
        cls._assert_stage(from_stage)
        cls._assert_stage(to_stage)
        if from_stage == to_stage:
            return
        allowed = ALLOWED_STAGE_TRANSITIONS.get(from_stage, frozenset())
        if to_stage not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Illegal stage transition: {from_stage} → {to_stage}",
            )

    @classmethod
    async def _load_deal(cls, db: AsyncSession, deal_id: UUID, tenant_id: UUID) -> SalesDeal:
        q = (
            select(SalesDeal)
            .options(selectinload(SalesDeal.customer), selectinload(SalesDeal.lead))
            .where(SalesDeal.id == deal_id, SalesDeal.tenant_id == tenant_id)
        )
        row = (await db.execute(q)).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Deal not found")
        return row

    @classmethod
    async def transition_stage(
        cls,
        db: AsyncSession,
        deal_id: UUID,
        tenant_id: UUID,
        body: PipelineStageUpdate,
        *,
        stage_source: str = "manual",
        actor: str | None = None,
        skip_override_check: bool = False,
        write_timeline: bool = True,
    ) -> dict:
        cls._assert_stage_source(stage_source)
        deal = await cls._load_deal(db, deal_id, tenant_id)
        old_stage = deal.stage
        new_stage = body.stage

        if (
            stage_source in ("auto", "proposal")
            and deal.stage_override
            and not skip_override_check
        ):
            await db.flush()
            return SalesCrmService._deal_to_dict(deal)

        if old_stage == new_stage:
            if body.expected_close_date is not None:
                deal.expected_close_date = body.expected_close_date
            if body.notes:
                deal.notes = body.notes
            await db.commit()
            return await SalesCrmService.get_deal(db, deal_id, tenant_id)

        cls.validate_transition(old_stage, new_stage)

        deal.stage = new_stage
        deal.stage_source = stage_source
        if stage_source == "manual" and body.stage_override:
            deal.stage_override = True
        if body.probability is not None:
            deal.probability = body.probability
        elif new_stage in DEFAULT_STAGE_PROBABILITY:
            deal.probability = DEFAULT_STAGE_PROBABILITY[new_stage]
        if body.expected_close_date is not None:
            deal.expected_close_date = body.expected_close_date
        if body.notes is not None:
            deal.notes = body.notes
        if new_stage in TERMINAL_STAGES:
            deal.closed_at = datetime.now(timezone.utc)
        elif old_stage in TERMINAL_STAGES:
            deal.closed_at = None

        if write_timeline:
            await CrmPipelineTimelineService.stage_changed(
                db,
                tenant_id=tenant_id,
                deal_id=deal.id,
                from_stage=old_stage,
                to_stage=new_stage,
                customer_id=deal.customer_id,
                lead_id=deal.lead_id,
                stage_source=stage_source,
                actor=actor,
                notes=body.notes,
            )

        await db.commit()
        return await SalesCrmService.get_deal(db, deal_id, tenant_id)

    @classmethod
    async def list_pipeline_deals(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        stage: str | None = None,
        customer_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        return await SalesCrmService.list_deals(
            db,
            tenant_id,
            stage=stage,
            customer_id=customer_id,
            skip=skip,
            limit=limit,
        )

    @classmethod
    async def get_deal_timeline(
        cls,
        db: AsyncSession,
        deal_id: UUID,
        tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list, int]:
        await cls._load_deal(db, deal_id, tenant_id)
        return await CrmPipelineTimelineService.list_deal_timeline(
            db, deal_id, tenant_id, skip=skip, limit=limit,
        )

    @classmethod
    async def get_lead_timeline(
        cls,
        db: AsyncSession,
        lead_id: UUID,
        tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list, int]:
        lead = (await db.execute(
            select(SalesLead).where(SalesLead.id == lead_id, SalesLead.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        return await CrmPipelineTimelineService.list_lead_timeline(
            db, lead_id, tenant_id, skip=skip, limit=limit,
        )

    @classmethod
    async def add_note(
        cls,
        db: AsyncSession,
        deal_id: UUID,
        tenant_id: UUID,
        body: PipelineNoteCreate,
        *,
        actor: str | None = None,
    ) -> dict:
        deal = await cls._load_deal(db, deal_id, tenant_id)
        await CrmPipelineTimelineService.manual_note(
            db,
            tenant_id=tenant_id,
            deal_id=deal.id,
            title=body.title,
            description=body.description,
            customer_id=deal.customer_id,
            lead_id=deal.lead_id,
            actor=actor,
        )
        await db.commit()
        events, total = await CrmPipelineTimelineService.list_deal_timeline(
            db, deal_id, tenant_id, skip=0, limit=1,
        )
        return {
            "event": events[0] if events else None,
            "timeline_total": total,
        }

    @classmethod
    async def schedule_meeting(
        cls,
        db: AsyncSession,
        deal_id: UUID,
        tenant_id: UUID,
        body: PipelineMeetingCreate,
        *,
        actor: str | None = None,
    ) -> dict:
        deal = await cls._load_deal(db, deal_id, tenant_id)
        scheduled_at = body.scheduled_at or datetime.now(timezone.utc)
        await CrmPipelineTimelineService.meeting_scheduled(
            db,
            tenant_id=tenant_id,
            title=body.title,
            deal_id=deal.id,
            customer_id=deal.customer_id,
            lead_id=deal.lead_id,
            scheduled_at=scheduled_at,
            actor=actor,
        )

        deal_result: dict | None = None
        if body.advance_stage and deal.stage != "meeting_scheduled":
            allowed = ALLOWED_STAGE_TRANSITIONS.get(deal.stage, frozenset())
            if "meeting_scheduled" in allowed and not (
                deal.stage_override and deal.stage_source != "manual"
            ):
                stage_body = PipelineStageUpdate(
                    stage="meeting_scheduled",
                    stage_override=False,
                )
                await cls.transition_stage(
                    db,
                    deal_id,
                    tenant_id,
                    stage_body,
                    stage_source="auto",
                    actor=actor,
                    write_timeline=True,
                )
                deal_result = await SalesCrmService.get_deal(db, deal_id, tenant_id)
            else:
                await db.commit()
        else:
            await db.commit()

        events, _ = await CrmPipelineTimelineService.list_deal_timeline(
            db, deal_id, tenant_id, skip=0, limit=1,
        )
        return {
            "event": events[0] if events else None,
            "deal": deal_result or await SalesCrmService.get_deal(db, deal_id, tenant_id),
        }

    @classmethod
    async def on_deal_created(
        cls,
        db: AsyncSession,
        deal: SalesDeal,
        *,
        actor: str | None = None,
    ) -> None:
        await CrmPipelineTimelineService.deal_created(
            db,
            tenant_id=deal.tenant_id,
            deal_id=deal.id,
            title=deal.title,
            customer_id=deal.customer_id,
            lead_id=deal.lead_id,
            actor=actor,
        )

    @classmethod
    async def on_lead_created(
        cls,
        db: AsyncSession,
        lead: SalesLead,
        *,
        actor: str | None = None,
    ) -> None:
        await CrmPipelineTimelineService.lead_created(
            db,
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            name=lead.name,
            customer_id=lead.customer_id,
            actor=actor,
        )

    @classmethod
    async def resolve_acceptance_stage(cls, db: AsyncSession, customer_id: UUID | None) -> str:
        if not customer_id:
            return "contract_pending"
        customer = (await db.execute(
            select(SalesCustomer).where(SalesCustomer.id == customer_id)
        )).scalar_one_or_none()
        if customer and customer.client_id:
            return "client_active"
        return "contract_pending"
