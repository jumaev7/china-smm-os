"""Executive CRM pipeline timeline — tenant-scoped audit events."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm_pipeline_event import CrmPipelineEvent, PIPELINE_EVENT_TYPES
from app.schemas.crm_pipeline import PIPELINE_STAGE_LABELS


class CrmPipelineTimelineService:
    @staticmethod
    def _stage_label(stage: str) -> str:
        return PIPELINE_STAGE_LABELS.get(stage, stage.replace("_", " ").title())

    @classmethod
    async def write_event(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        event_type: str,
        title: str,
        description: str | None = None,
        payload: dict | None = None,
        customer_id: UUID | None = None,
        lead_id: UUID | None = None,
        deal_id: UUID | None = None,
        actor: str | None = None,
    ) -> CrmPipelineEvent:
        if event_type not in PIPELINE_EVENT_TYPES:
            raise ValueError(f"Invalid pipeline event type: {event_type}")
        row = CrmPipelineEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            title=title,
            description=description,
            payload=payload,
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
            actor=actor,
        )
        db.add(row)
        await db.flush()
        return row

    @classmethod
    async def deal_created(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        deal_id: UUID,
        title: str,
        customer_id: UUID | None = None,
        lead_id: UUID | None = None,
        actor: str | None = None,
    ) -> CrmPipelineEvent:
        return await cls.write_event(
            db,
            tenant_id=tenant_id,
            event_type="deal_created",
            title=f"Deal created: {title}",
            description="New deal entered the pipeline at lead stage.",
            payload={"stage": "lead"},
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
            actor=actor,
        )

    @classmethod
    async def lead_created(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        lead_id: UUID,
        name: str,
        customer_id: UUID | None = None,
        actor: str | None = None,
    ) -> CrmPipelineEvent:
        return await cls.write_event(
            db,
            tenant_id=tenant_id,
            event_type="lead_created",
            title=f"Lead created: {name}",
            customer_id=customer_id,
            lead_id=lead_id,
            actor=actor,
        )

    @classmethod
    async def stage_changed(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        deal_id: UUID,
        from_stage: str,
        to_stage: str,
        customer_id: UUID | None = None,
        lead_id: UUID | None = None,
        stage_source: str = "manual",
        actor: str | None = None,
        notes: str | None = None,
    ) -> CrmPipelineEvent:
        from_label = cls._stage_label(from_stage)
        to_label = cls._stage_label(to_stage)
        return await cls.write_event(
            db,
            tenant_id=tenant_id,
            event_type="stage_changed",
            title=f"Stage: {from_label} → {to_label}",
            description=notes,
            payload={
                "from_stage": from_stage,
                "to_stage": to_stage,
                "stage_source": stage_source,
            },
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
            actor=actor,
        )

    @classmethod
    async def proposal_sent(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        proposal_number: str,
        deal_id: UUID | None = None,
        customer_id: UUID | None = None,
        lead_id: UUID | None = None,
        actor: str | None = None,
    ) -> CrmPipelineEvent:
        return await cls.write_event(
            db,
            tenant_id=tenant_id,
            event_type="proposal_sent",
            title=f"Proposal sent: {proposal_number}",
            payload={"proposal_id": str(proposal_id), "proposal_number": proposal_number},
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
            actor=actor,
        )

    @classmethod
    async def proposal_accepted(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        proposal_number: str,
        target_stage: str,
        deal_id: UUID | None = None,
        customer_id: UUID | None = None,
        lead_id: UUID | None = None,
        actor: str | None = None,
    ) -> CrmPipelineEvent:
        return await cls.write_event(
            db,
            tenant_id=tenant_id,
            event_type="proposal_accepted",
            title=f"Proposal accepted: {proposal_number}",
            description=f"Deal advanced to {cls._stage_label(target_stage)}.",
            payload={
                "proposal_id": str(proposal_id),
                "proposal_number": proposal_number,
                "target_stage": target_stage,
            },
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
            actor=actor,
        )

    @classmethod
    async def proposal_rejected(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        proposal_number: str,
        status: str,
        deal_id: UUID | None = None,
        customer_id: UUID | None = None,
        lead_id: UUID | None = None,
        actor: str | None = None,
    ) -> CrmPipelineEvent:
        label = "rejected" if status == "rejected" else "expired"
        return await cls.write_event(
            db,
            tenant_id=tenant_id,
            event_type="proposal_rejected",
            title=f"Proposal {label}: {proposal_number}",
            payload={
                "proposal_id": str(proposal_id),
                "proposal_number": proposal_number,
                "status": status,
            },
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
            actor=actor,
        )

    @classmethod
    async def meeting_scheduled(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        title: str,
        deal_id: UUID,
        customer_id: UUID | None = None,
        lead_id: UUID | None = None,
        scheduled_at: datetime | None = None,
        actor: str | None = None,
    ) -> CrmPipelineEvent:
        return await cls.write_event(
            db,
            tenant_id=tenant_id,
            event_type="meeting_added",
            title=f"Meeting scheduled: {title}",
            payload={"scheduled_at": scheduled_at.isoformat() if scheduled_at else None},
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
            actor=actor,
        )

    @classmethod
    async def manual_note(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        deal_id: UUID,
        description: str,
        title: str | None = None,
        customer_id: UUID | None = None,
        lead_id: UUID | None = None,
        actor: str | None = None,
    ) -> CrmPipelineEvent:
        return await cls.write_event(
            db,
            tenant_id=tenant_id,
            event_type="manual_note",
            title=title or "Manual note",
            description=description,
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
            actor=actor,
        )

    @classmethod
    async def publishing_active_placeholder(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        deal_id: UUID,
        customer_id: UUID | None = None,
        lead_id: UUID | None = None,
    ) -> CrmPipelineEvent:
        """Auto-derived hook when publishing becomes active — placeholder for Phase 3."""
        return await cls.write_event(
            db,
            tenant_id=tenant_id,
            event_type="publishing_connected",
            title="Publishing active (auto-derived)",
            description="Placeholder hook — publishing linkage detected.",
            payload={"auto_derived": True, "placeholder": True},
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
            actor="system",
        )

    @classmethod
    async def list_deal_timeline(
        cls,
        db: AsyncSession,
        deal_id: UUID,
        tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[CrmPipelineEvent], int]:
        base = (
            CrmPipelineEvent.tenant_id == tenant_id,
            CrmPipelineEvent.deal_id == deal_id,
        )
        count_q = select(func.count()).select_from(CrmPipelineEvent).where(*base)
        q = (
            select(CrmPipelineEvent)
            .where(*base)
            .order_by(CrmPipelineEvent.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        total = (await db.execute(count_q)).scalar_one()
        rows = (await db.execute(q)).scalars().all()
        return list(rows), total

    @classmethod
    async def list_lead_timeline(
        cls,
        db: AsyncSession,
        lead_id: UUID,
        tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[CrmPipelineEvent], int]:
        from app.models.sales_crm import SalesDeal

        deal_ids_q = select(SalesDeal.id).where(
            SalesDeal.tenant_id == tenant_id,
            SalesDeal.lead_id == lead_id,
        )
        deal_ids = [row[0] for row in (await db.execute(deal_ids_q)).all()]
        conditions = [CrmPipelineEvent.lead_id == lead_id]
        if deal_ids:
            conditions.append(CrmPipelineEvent.deal_id.in_(deal_ids))
        filt = or_(*conditions)
        base = (CrmPipelineEvent.tenant_id == tenant_id, filt)
        count_q = select(func.count()).select_from(CrmPipelineEvent).where(*base)
        q = (
            select(CrmPipelineEvent)
            .where(*base)
            .order_by(CrmPipelineEvent.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        total = (await db.execute(count_q)).scalar_one()
        rows = (await db.execute(q)).scalars().all()
        return list(rows), total
