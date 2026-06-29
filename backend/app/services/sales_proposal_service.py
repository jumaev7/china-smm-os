"""Tenant-scoped commercial proposals / quotations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.sales_crm import (
    PROPOSAL_STATUSES,
    SalesCustomer,
    SalesDeal,
    SalesLead,
    SalesProposal,
    SalesProposalItem,
)
from app.schemas.sales_crm import (
    SalesProposalCreate,
    SalesProposalItemCreate,
    SalesProposalStatusUpdate,
    SalesProposalUpdate,
)


class SalesProposalService:
    @staticmethod
    def _assert_status(status: str) -> None:
        if status not in PROPOSAL_STATUSES:
            raise HTTPException(status_code=422, detail=f"Invalid proposal status: {status}")

    @staticmethod
    def _calc_item_total(item: SalesProposalItemCreate | SalesProposalItem) -> Decimal:
        line = Decimal(str(item.quantity)) * Decimal(str(item.unit_price))
        discount = Decimal(str(item.discount or 0))
        return max(line - discount, Decimal("0"))

    @classmethod
    def _calc_totals(
        cls,
        items: list[SalesProposalItemCreate],
        proposal_discount: Decimal,
        tax: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal]:
        subtotal = sum(cls._calc_item_total(i) for i in items)
        discount = Decimal(str(proposal_discount or 0))
        tax_amt = Decimal(str(tax or 0))
        total = max(subtotal - discount, Decimal("0")) + tax_amt
        return subtotal, discount, total

    @staticmethod
    def _status_history_entry(status: str, note: str | None = None) -> dict:
        return {
            "status": status,
            "at": datetime.now(timezone.utc).isoformat(),
            "note": note,
        }

    @staticmethod
    def _append_status(proposal: SalesProposal, status: str, note: str | None = None) -> None:
        history = list(proposal.status_history or [])
        history.append(SalesProposalService._status_history_entry(status, note))
        proposal.status_history = history

    @classmethod
    async def _next_proposal_number(cls, db: AsyncSession, tenant_id: UUID) -> str:
        year = datetime.now(timezone.utc).year
        prefix = f"PROP-{year}-"
        count_q = select(func.count()).select_from(SalesProposal).where(
            SalesProposal.tenant_id == tenant_id,
            SalesProposal.proposal_number.like(f"{prefix}%"),
        )
        count = (await db.execute(count_q)).scalar_one()
        return f"{prefix}{count + 1:04d}"

    @classmethod
    async def _load_proposal(
        cls,
        db: AsyncSession,
        proposal_id: UUID,
        tenant_id: UUID | None,
    ) -> SalesProposal:
        q = (
            select(SalesProposal)
            .options(
                selectinload(SalesProposal.items),
                selectinload(SalesProposal.customer),
                selectinload(SalesProposal.lead),
                selectinload(SalesProposal.deal),
            )
            .where(SalesProposal.id == proposal_id)
        )
        if tenant_id is not None:
            q = q.where(SalesProposal.tenant_id == tenant_id)
        row = (await db.execute(q)).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return row

    @classmethod
    def _to_response(cls, proposal: SalesProposal) -> dict:
        history = proposal.status_history or []
        return {
            "id": proposal.id,
            "tenant_id": proposal.tenant_id,
            "proposal_number": proposal.proposal_number,
            "title": proposal.title,
            "customer_id": proposal.customer_id,
            "lead_id": proposal.lead_id,
            "deal_id": proposal.deal_id,
            "issue_date": proposal.issue_date,
            "valid_until": proposal.valid_until,
            "currency": proposal.currency,
            "subtotal": proposal.subtotal,
            "discount": proposal.discount,
            "tax": proposal.tax,
            "total": proposal.total,
            "status": proposal.status,
            "version": proposal.version,
            "sent_at": proposal.sent_at,
            "accepted_at": proposal.accepted_at,
            "attachment_url": proposal.attachment_url,
            "notes": proposal.notes,
            "terms": proposal.terms,
            "status_history": history,
            "created_at": proposal.created_at,
            "updated_at": proposal.updated_at,
            "items": proposal.items,
            "customer_name": proposal.customer.name if proposal.customer else None,
            "lead_name": proposal.lead.name if proposal.lead else None,
            "deal_title": proposal.deal.title if proposal.deal else None,
        }

    @classmethod
    async def _validate_links(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        customer_id: UUID | None,
        lead_id: UUID | None,
        deal_id: UUID | None,
    ) -> tuple[UUID | None, UUID | None, UUID | None]:
        resolved_customer = customer_id
        resolved_lead = lead_id
        resolved_deal = deal_id

        if lead_id:
            lead = (await db.execute(
                select(SalesLead).where(SalesLead.id == lead_id, SalesLead.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if not lead:
                raise HTTPException(status_code=404, detail="Lead not found")
            if not resolved_customer and lead.customer_id:
                resolved_customer = lead.customer_id

        if deal_id:
            deal = (await db.execute(
                select(SalesDeal).where(SalesDeal.id == deal_id, SalesDeal.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if not deal:
                raise HTTPException(status_code=404, detail="Deal not found")
            if not resolved_customer and deal.customer_id:
                resolved_customer = deal.customer_id
            if not resolved_lead and deal.lead_id:
                resolved_lead = deal.lead_id

        if resolved_customer:
            customer = (await db.execute(
                select(SalesCustomer).where(
                    SalesCustomer.id == resolved_customer,
                    SalesCustomer.tenant_id == tenant_id,
                )
            )).scalar_one_or_none()
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found")

        return resolved_customer, resolved_lead, resolved_deal

    @classmethod
    def _build_items(
        cls,
        proposal_id: UUID,
        items_data: list[SalesProposalItemCreate],
    ) -> list[SalesProposalItem]:
        rows: list[SalesProposalItem] = []
        for idx, item in enumerate(items_data):
            rows.append(SalesProposalItem(
                proposal_id=proposal_id,
                product_or_service_name=item.product_or_service_name.strip(),
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount=item.discount,
                total=cls._calc_item_total(item),
                sort_order=idx,
            ))
        return rows

    @classmethod
    async def list_proposals(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        search: str | None = None,
        status: str | None = None,
        customer_id: UUID | None = None,
        deal_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        q = select(SalesProposal).options(
            selectinload(SalesProposal.items),
            selectinload(SalesProposal.customer),
            selectinload(SalesProposal.lead),
            selectinload(SalesProposal.deal),
        )
        count_q = select(func.count()).select_from(SalesProposal)
        if tenant_id is not None:
            q = q.where(SalesProposal.tenant_id == tenant_id)
            count_q = count_q.where(SalesProposal.tenant_id == tenant_id)
        if search:
            term = f"%{search.strip()}%"
            filt = or_(
                SalesProposal.title.ilike(term),
                SalesProposal.proposal_number.ilike(term),
            )
            q = q.where(filt)
            count_q = count_q.where(filt)
        if status:
            cls._assert_status(status)
            q = q.where(SalesProposal.status == status)
            count_q = count_q.where(SalesProposal.status == status)
        if customer_id:
            q = q.where(SalesProposal.customer_id == customer_id)
            count_q = count_q.where(SalesProposal.customer_id == customer_id)
        if deal_id:
            q = q.where(SalesProposal.deal_id == deal_id)
            count_q = count_q.where(SalesProposal.deal_id == deal_id)
        if date_from:
            q = q.where(SalesProposal.issue_date >= date_from)
            count_q = count_q.where(SalesProposal.issue_date >= date_from)
        if date_to:
            q = q.where(SalesProposal.issue_date <= date_to)
            count_q = count_q.where(SalesProposal.issue_date <= date_to)

        total = (await db.execute(count_q)).scalar_one()
        rows = (await db.execute(
            q.order_by(SalesProposal.created_at.desc()).offset(skip).limit(limit)
        )).scalars().all()
        return [cls._to_response(r) for r in rows], total

    @classmethod
    async def get_proposal(cls, db: AsyncSession, proposal_id: UUID, tenant_id: UUID | None) -> dict:
        proposal = await cls._load_proposal(db, proposal_id, tenant_id)
        return cls._to_response(proposal)

    @classmethod
    async def create_proposal(
        cls,
        db: AsyncSession,
        body: SalesProposalCreate,
        *,
        tenant_id: UUID,
    ) -> dict:
        customer_id, lead_id, deal_id = await cls._validate_links(
            db, tenant_id,
            customer_id=body.customer_id,
            lead_id=body.lead_id,
            deal_id=body.deal_id,
        )
        subtotal, discount, total = cls._calc_totals(body.items, body.discount, body.tax)
        proposal_number = await cls._next_proposal_number(db, tenant_id)
        proposal = SalesProposal(
            tenant_id=tenant_id,
            proposal_number=proposal_number,
            title=body.title.strip(),
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
            issue_date=body.issue_date,
            valid_until=body.valid_until,
            currency=body.currency,
            subtotal=subtotal,
            discount=discount,
            tax=body.tax,
            total=total,
            status="draft",
            notes=body.notes,
            terms=body.terms,
            status_history=[cls._status_history_entry("draft", "Proposal created")],
        )
        db.add(proposal)
        await db.flush()
        for item in cls._build_items(proposal.id, body.items):
            db.add(item)
        await db.commit()
        return await cls.get_proposal(db, proposal.id, tenant_id)

    @classmethod
    async def create_from_lead(
        cls,
        db: AsyncSession,
        lead_id: UUID,
        *,
        tenant_id: UUID,
        title: str | None = None,
    ) -> dict:
        lead = (await db.execute(
            select(SalesLead).where(SalesLead.id == lead_id, SalesLead.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        now = datetime.now(timezone.utc)
        body = SalesProposalCreate(
            title=title or f"Proposal for {lead.name}",
            customer_id=lead.customer_id,
            lead_id=lead.id,
            deal_id=None,
            issue_date=now,
            valid_until=now + timedelta(days=30),
            currency="USD",
            items=[SalesProposalItemCreate(
                product_or_service_name="Product / Service",
                description=None,
                quantity=Decimal("1"),
                unit_price=Decimal("0"),
            )],
        )
        return await cls.create_proposal(db, body, tenant_id=tenant_id)

    @classmethod
    async def create_from_deal(
        cls,
        db: AsyncSession,
        deal_id: UUID,
        *,
        tenant_id: UUID,
        title: str | None = None,
    ) -> dict:
        deal = (await db.execute(
            select(SalesDeal).where(SalesDeal.id == deal_id, SalesDeal.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        now = datetime.now(timezone.utc)
        unit_price = deal.value or Decimal("0")
        body = SalesProposalCreate(
            title=title or f"Proposal — {deal.title}",
            customer_id=deal.customer_id,
            lead_id=deal.lead_id,
            deal_id=deal.id,
            issue_date=now,
            valid_until=now + timedelta(days=30),
            currency=deal.currency,
            items=[SalesProposalItemCreate(
                product_or_service_name=deal.title,
                description=deal.notes,
                quantity=Decimal("1"),
                unit_price=unit_price,
            )],
        )
        return await cls.create_proposal(db, body, tenant_id=tenant_id)

    @classmethod
    async def update_proposal(
        cls,
        db: AsyncSession,
        proposal_id: UUID,
        body: SalesProposalUpdate,
        tenant_id: UUID | None,
    ) -> dict:
        proposal = await cls._load_proposal(db, proposal_id, tenant_id)
        effective_tenant = proposal.tenant_id

        customer_id = body.customer_id if body.customer_id is not None else proposal.customer_id
        lead_id = body.lead_id if body.lead_id is not None else proposal.lead_id
        deal_id = body.deal_id if body.deal_id is not None else proposal.deal_id
        customer_id, lead_id, deal_id = await cls._validate_links(
            db, effective_tenant,
            customer_id=customer_id,
            lead_id=lead_id,
            deal_id=deal_id,
        )

        if body.title is not None:
            proposal.title = body.title.strip()
        proposal.customer_id = customer_id
        proposal.lead_id = lead_id
        proposal.deal_id = deal_id
        if body.issue_date is not None:
            proposal.issue_date = body.issue_date
        if body.valid_until is not None:
            proposal.valid_until = body.valid_until
        if body.currency is not None:
            proposal.currency = body.currency
        if body.notes is not None:
            proposal.notes = body.notes
        if body.terms is not None:
            proposal.terms = body.terms

        items_data = body.items
        if items_data is not None:
            for old in list(proposal.items):
                await db.delete(old)
            await db.flush()
            for item in cls._build_items(proposal.id, items_data):
                db.add(item)
            calc_items = items_data
        else:
            calc_items = [
                SalesProposalItemCreate(
                    product_or_service_name=i.product_or_service_name,
                    description=i.description,
                    quantity=i.quantity,
                    unit_price=i.unit_price,
                    discount=i.discount,
                )
                for i in proposal.items
            ]

        discount = body.discount if body.discount is not None else proposal.discount
        tax = body.tax if body.tax is not None else proposal.tax
        subtotal, discount, total = cls._calc_totals(calc_items, discount, tax)
        proposal.subtotal = subtotal
        proposal.discount = discount
        proposal.tax = tax
        proposal.total = total

        await db.commit()
        return await cls.get_proposal(db, proposal_id, tenant_id)

    @classmethod
    async def update_status(
        cls,
        db: AsyncSession,
        proposal_id: UUID,
        body: SalesProposalStatusUpdate,
        tenant_id: UUID | None,
        *,
        actor: str | None = None,
    ) -> dict:
        cls._assert_status(body.status)
        proposal = await cls._load_proposal(db, proposal_id, tenant_id)
        effective_tenant = proposal.tenant_id
        now = datetime.now(timezone.utc)
        status_changed = proposal.status != body.status

        if status_changed:
            proposal.status = body.status
            cls._append_status(proposal, body.status)

        if body.status == "sent" and proposal.sent_at is None:
            proposal.sent_at = now
        if body.status == "accepted" and proposal.accepted_at is None:
            proposal.accepted_at = now

        if status_changed and proposal.deal_id:
            from app.services.crm_pipeline_service import CrmPipelineService
            from app.schemas.crm_pipeline import PipelineStageUpdate

            deal = (await db.execute(
                select(SalesDeal).where(
                    SalesDeal.id == proposal.deal_id,
                    SalesDeal.tenant_id == effective_tenant,
                )
            )).scalar_one_or_none()

            if deal:
                if body.status == "sent":
                    from app.services.crm_pipeline_timeline_service import CrmPipelineTimelineService

                    await CrmPipelineTimelineService.proposal_sent(
                        db,
                        tenant_id=effective_tenant,
                        proposal_id=proposal.id,
                        proposal_number=proposal.proposal_number,
                        deal_id=deal.id,
                        customer_id=proposal.customer_id,
                        lead_id=proposal.lead_id,
                        actor=actor,
                    )
                    await CrmPipelineService.transition_stage(
                        db,
                        deal.id,
                        effective_tenant,
                        PipelineStageUpdate(stage="proposal_sent", stage_override=False),
                        stage_source="proposal",
                        actor=actor,
                    )
                elif body.status == "accepted":
                    target_stage = await CrmPipelineService.resolve_acceptance_stage(
                        db, proposal.customer_id,
                    )
                    from app.services.crm_pipeline_timeline_service import CrmPipelineTimelineService

                    await CrmPipelineTimelineService.proposal_accepted(
                        db,
                        tenant_id=effective_tenant,
                        proposal_id=proposal.id,
                        proposal_number=proposal.proposal_number,
                        target_stage=target_stage,
                        deal_id=deal.id,
                        customer_id=proposal.customer_id,
                        lead_id=proposal.lead_id,
                        actor=actor,
                    )
                    await CrmPipelineService.transition_stage(
                        db,
                        deal.id,
                        effective_tenant,
                        PipelineStageUpdate(stage=target_stage, stage_override=False),
                        stage_source="proposal",
                        actor=actor,
                    )
                elif body.status in ("rejected", "expired"):
                    from app.services.crm_pipeline_timeline_service import CrmPipelineTimelineService

                    await CrmPipelineTimelineService.proposal_rejected(
                        db,
                        tenant_id=effective_tenant,
                        proposal_id=proposal.id,
                        proposal_number=proposal.proposal_number,
                        status=body.status,
                        deal_id=deal.id,
                        customer_id=proposal.customer_id,
                        lead_id=proposal.lead_id,
                        actor=actor,
                    )
                    if body.close_deal_on_reject:
                        await CrmPipelineService.transition_stage(
                            db,
                            deal.id,
                            effective_tenant,
                            PipelineStageUpdate(stage="closed_lost", stage_override=False),
                            stage_source="proposal",
                            actor=actor,
                        )
                else:
                    await db.commit()
                    return await cls.get_proposal(db, proposal_id, tenant_id)
            else:
                await db.commit()
                return await cls.get_proposal(db, proposal_id, tenant_id)
        else:
            await db.commit()
            return await cls.get_proposal(db, proposal_id, tenant_id)

        await db.commit()
        return await cls.get_proposal(db, proposal_id, tenant_id)

    @classmethod
    async def delete_proposal(
        cls,
        db: AsyncSession,
        proposal_id: UUID,
        tenant_id: UUID | None,
    ) -> None:
        proposal = await cls._load_proposal(db, proposal_id, tenant_id)
        await db.delete(proposal)
        await db.commit()

    @classmethod
    async def duplicate_proposal(
        cls,
        db: AsyncSession,
        proposal_id: UUID,
        tenant_id: UUID | None,
    ) -> dict:
        source = await cls._load_proposal(db, proposal_id, tenant_id)
        items = [
            SalesProposalItemCreate(
                product_or_service_name=i.product_or_service_name,
                description=i.description,
                quantity=i.quantity,
                unit_price=i.unit_price,
                discount=i.discount,
            )
            for i in source.items
        ]
        body = SalesProposalCreate(
            title=f"{source.title} (Copy)",
            customer_id=source.customer_id,
            lead_id=source.lead_id,
            deal_id=source.deal_id,
            issue_date=datetime.now(timezone.utc),
            valid_until=source.valid_until,
            currency=source.currency,
            discount=source.discount,
            tax=source.tax,
            notes=source.notes,
            terms=source.terms,
            items=items,
        )
        return await cls.create_proposal(db, body, tenant_id=source.tenant_id)
