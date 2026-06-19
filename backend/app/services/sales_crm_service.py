"""Tenant-scoped Sales CRM business logic."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.sales_crm import (
    DEAL_STAGES,
    LEAD_PRIORITIES,
    LEAD_SOURCES,
    LEAD_STATUSES,
    ACTIVITY_TYPES,
    SalesActivity,
    SalesCustomer,
    SalesDeal,
    SalesLead,
)
from app.schemas.sales_crm import (
    SalesActivityCreate,
    SalesCustomerCreate,
    SalesCustomerResponse,
    SalesCustomerUpdate,
    SalesDashboardResponse,
    SalesDashboardStats,
    SalesDealCreate,
    SalesDealStageUpdate,
    SalesDealUpdate,
    SalesLeadCreate,
    SalesLeadUpdate,
    SalesPipelineStageSummary,
)


class SalesCrmService:
    @staticmethod
    def _assert_lead_status(status: str) -> None:
        if status not in LEAD_STATUSES:
            raise HTTPException(status_code=422, detail=f"Invalid lead status: {status}")

    @staticmethod
    def _assert_priority(priority: str) -> None:
        if priority not in LEAD_PRIORITIES:
            raise HTTPException(status_code=422, detail=f"Invalid priority: {priority}")

    @staticmethod
    def _assert_source(source: str) -> None:
        if source not in LEAD_SOURCES:
            raise HTTPException(status_code=422, detail=f"Invalid source: {source}")

    @staticmethod
    def _assert_stage(stage: str) -> None:
        if stage not in DEAL_STAGES:
            raise HTTPException(status_code=422, detail=f"Invalid deal stage: {stage}")

    @staticmethod
    def _assert_activity_type(activity_type: str) -> None:
        if activity_type not in ACTIVITY_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid activity type: {activity_type}")

    @staticmethod
    async def _load_customer(db: AsyncSession, customer_id: UUID, tenant_id: UUID | None) -> SalesCustomer:
        q = select(SalesCustomer).where(SalesCustomer.id == customer_id)
        if tenant_id is not None:
            q = q.where(SalesCustomer.tenant_id == tenant_id)
        row = (await db.execute(q)).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Customer not found")
        return row

    @staticmethod
    async def _load_lead(db: AsyncSession, lead_id: UUID, tenant_id: UUID | None) -> SalesLead:
        q = select(SalesLead).where(SalesLead.id == lead_id)
        if tenant_id is not None:
            q = q.where(SalesLead.tenant_id == tenant_id)
        row = (await db.execute(q)).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found")
        return row

    @staticmethod
    async def _load_deal(db: AsyncSession, deal_id: UUID, tenant_id: UUID | None) -> SalesDeal:
        q = select(SalesDeal).where(SalesDeal.id == deal_id)
        if tenant_id is not None:
            q = q.where(SalesDeal.tenant_id == tenant_id)
        row = (await db.execute(q)).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Deal not found")
        return row

    @staticmethod
    def _deal_to_dict(deal: SalesDeal) -> dict:
        customer_name = deal.customer.name if deal.customer else None
        lead_name = deal.lead.name if deal.lead else None
        return {
            "id": deal.id,
            "tenant_id": deal.tenant_id,
            "title": deal.title,
            "customer_id": deal.customer_id,
            "lead_id": deal.lead_id,
            "value": deal.value,
            "currency": deal.currency,
            "stage": deal.stage,
            "probability": deal.probability,
            "expected_close_date": deal.expected_close_date,
            "notes": deal.notes,
            "created_at": deal.created_at,
            "updated_at": deal.updated_at,
            "customer_name": customer_name,
            "lead_name": lead_name,
        }

    # ─── Dashboard ───────────────────────────────────────────────────────────

    @classmethod
    async def dashboard(cls, db: AsyncSession, tenant_id: UUID | None) -> SalesDashboardResponse:
        lead_q = select(SalesLead)
        deal_q = select(SalesDeal)
        customer_q = select(func.count()).select_from(SalesCustomer)
        if tenant_id is not None:
            lead_q = lead_q.where(SalesLead.tenant_id == tenant_id)
            deal_q = deal_q.where(SalesDeal.tenant_id == tenant_id)
            customer_q = customer_q.where(SalesCustomer.tenant_id == tenant_id)

        leads = (await db.execute(lead_q)).scalars().all()
        deals = (await db.execute(deal_q)).scalars().all()
        total_customers = (await db.execute(customer_q)).scalar_one()

        leads_by_status: dict[str, int] = {}
        leads_by_source: dict[str, int] = {}
        for lead in leads:
            leads_by_status[lead.status] = leads_by_status.get(lead.status, 0) + 1
            leads_by_source[lead.source] = leads_by_source.get(lead.source, 0) + 1

        pipeline_by_stage: list[SalesPipelineStageSummary] = []
        for stage in DEAL_STAGES:
            stage_deals = [d for d in deals if d.stage == stage]
            pipeline_by_stage.append(SalesPipelineStageSummary(
                stage=stage,
                count=len(stage_deals),
                total_value=sum((d.value or Decimal(0)) for d in stage_deals),
            ))

        won_deals = [d for d in deals if d.stage == "won"]
        open_deals = [d for d in deals if d.stage not in ("won", "lost")]

        activity_q = select(SalesActivity).order_by(SalesActivity.activity_date.desc()).limit(15)
        if tenant_id is not None:
            activity_q = activity_q.where(SalesActivity.tenant_id == tenant_id)
        recent = (await db.execute(activity_q)).scalars().all()

        stats = SalesDashboardStats(
            total_leads=len(leads),
            new_leads=leads_by_status.get("new", 0),
            qualified_leads=leads_by_status.get("qualified", 0),
            total_deals=len(deals),
            pipeline_value=sum((d.value or Decimal(0)) for d in open_deals),
            won_deals=len(won_deals),
            won_value=sum((d.value or Decimal(0)) for d in won_deals),
            total_customers=total_customers,
            leads_by_status=leads_by_status,
            leads_by_source=leads_by_source,
            pipeline_by_stage=pipeline_by_stage,
        )
        return SalesDashboardResponse(stats=stats, recent_activities=recent)

    # ─── Customers ───────────────────────────────────────────────────────────

    @classmethod
    async def list_customers(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        search: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        q = select(SalesCustomer)
        count_q = select(func.count()).select_from(SalesCustomer)
        if tenant_id is not None:
            q = q.where(SalesCustomer.tenant_id == tenant_id)
            count_q = count_q.where(SalesCustomer.tenant_id == tenant_id)
        if search:
            term = f"%{search.strip()}%"
            filt = or_(
                SalesCustomer.name.ilike(term),
                SalesCustomer.company.ilike(term),
                SalesCustomer.email.ilike(term),
                SalesCustomer.phone.ilike(term),
            )
            q = q.where(filt)
            count_q = count_q.where(filt)
        total = (await db.execute(count_q)).scalar_one()
        rows = (await db.execute(
            q.order_by(SalesCustomer.updated_at.desc()).offset(skip).limit(limit)
        )).scalars().all()

        items = []
        for c in rows:
            deal_count = (await db.execute(
                select(func.count()).select_from(SalesDeal).where(SalesDeal.customer_id == c.id)
            )).scalar_one()
            lead_count = (await db.execute(
                select(func.count()).select_from(SalesLead).where(SalesLead.customer_id == c.id)
            )).scalar_one()
            base = SalesCustomerResponse.model_validate(c)
            items.append(base.model_copy(update={"deal_count": deal_count, "lead_count": lead_count}))
        return items, total

    @classmethod
    async def get_customer(cls, db: AsyncSession, customer_id: UUID, tenant_id: UUID | None) -> SalesCustomer:
        return await cls._load_customer(db, customer_id, tenant_id)

    @classmethod
    async def create_customer(
        cls,
        db: AsyncSession,
        body: SalesCustomerCreate,
        tenant_id: UUID,
    ) -> SalesCustomer:
        row = SalesCustomer(tenant_id=tenant_id, **body.model_dump())
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @classmethod
    async def update_customer(
        cls,
        db: AsyncSession,
        customer_id: UUID,
        body: SalesCustomerUpdate,
        tenant_id: UUID | None,
    ) -> SalesCustomer:
        row = await cls._load_customer(db, customer_id, tenant_id)
        for key, val in body.model_dump(exclude_unset=True).items():
            setattr(row, key, val)
        await db.commit()
        await db.refresh(row)
        return row

    @classmethod
    async def delete_customer(cls, db: AsyncSession, customer_id: UUID, tenant_id: UUID | None) -> None:
        row = await cls._load_customer(db, customer_id, tenant_id)
        await db.delete(row)
        await db.commit()

    # ─── Leads ───────────────────────────────────────────────────────────────

    @classmethod
    async def list_leads(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        search: str | None = None,
        status: str | None = None,
        source: str | None = None,
        priority: str | None = None,
        customer_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[SalesLead], int]:
        q = select(SalesLead)
        count_q = select(func.count()).select_from(SalesLead)
        if tenant_id is not None:
            q = q.where(SalesLead.tenant_id == tenant_id)
            count_q = count_q.where(SalesLead.tenant_id == tenant_id)
        if customer_id:
            q = q.where(SalesLead.customer_id == customer_id)
            count_q = count_q.where(SalesLead.customer_id == customer_id)
        if status:
            cls._assert_lead_status(status)
            q = q.where(SalesLead.status == status)
            count_q = count_q.where(SalesLead.status == status)
        if source:
            cls._assert_source(source)
            q = q.where(SalesLead.source == source)
            count_q = count_q.where(SalesLead.source == source)
        if priority:
            cls._assert_priority(priority)
            q = q.where(SalesLead.priority == priority)
            count_q = count_q.where(SalesLead.priority == priority)
        if search:
            term = f"%{search.strip()}%"
            filt = or_(
                SalesLead.name.ilike(term),
                SalesLead.company.ilike(term),
                SalesLead.email.ilike(term),
                SalesLead.phone.ilike(term),
            )
            q = q.where(filt)
            count_q = count_q.where(filt)
        total = (await db.execute(count_q)).scalar_one()
        rows = (await db.execute(
            q.order_by(SalesLead.updated_at.desc()).offset(skip).limit(limit)
        )).scalars().all()
        return list(rows), total

    @classmethod
    async def get_lead(cls, db: AsyncSession, lead_id: UUID, tenant_id: UUID | None) -> SalesLead:
        return await cls._load_lead(db, lead_id, tenant_id)

    @classmethod
    async def create_lead(
        cls,
        db: AsyncSession,
        body: SalesLeadCreate,
        tenant_id: UUID,
        created_by: str | None = None,
    ) -> SalesLead:
        cls._assert_lead_status(body.status)
        cls._assert_priority(body.priority)
        cls._assert_source(body.source)
        if body.customer_id:
            await cls._load_customer(db, body.customer_id, tenant_id)
        row = SalesLead(tenant_id=tenant_id, **body.model_dump())
        db.add(row)
        await db.flush()
        activity = SalesActivity(
            tenant_id=tenant_id,
            type="note",
            title=f"Lead created: {row.name}",
            description=row.notes,
            lead_id=row.id,
            created_by=created_by,
            activity_date=datetime.now(timezone.utc),
        )
        db.add(activity)
        await db.commit()
        await db.refresh(row)
        return row

    @classmethod
    async def update_lead(
        cls,
        db: AsyncSession,
        lead_id: UUID,
        body: SalesLeadUpdate,
        tenant_id: UUID | None,
    ) -> SalesLead:
        row = await cls._load_lead(db, lead_id, tenant_id)
        data = body.model_dump(exclude_unset=True)
        if "status" in data:
            cls._assert_lead_status(data["status"])
        if "priority" in data:
            cls._assert_priority(data["priority"])
        if "source" in data:
            cls._assert_source(data["source"])
        if data.get("customer_id"):
            await cls._load_customer(db, data["customer_id"], row.tenant_id)
        for key, val in data.items():
            setattr(row, key, val)
        await db.commit()
        await db.refresh(row)
        return row

    @classmethod
    async def delete_lead(cls, db: AsyncSession, lead_id: UUID, tenant_id: UUID | None) -> None:
        row = await cls._load_lead(db, lead_id, tenant_id)
        await db.delete(row)
        await db.commit()

    # ─── Deals ───────────────────────────────────────────────────────────────

    @classmethod
    async def list_deals(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        stage: str | None = None,
        customer_id: UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict], int]:
        q = (
            select(SalesDeal)
            .options(selectinload(SalesDeal.customer), selectinload(SalesDeal.lead))
        )
        count_q = select(func.count()).select_from(SalesDeal)
        if tenant_id is not None:
            q = q.where(SalesDeal.tenant_id == tenant_id)
            count_q = count_q.where(SalesDeal.tenant_id == tenant_id)
        if customer_id:
            q = q.where(SalesDeal.customer_id == customer_id)
            count_q = count_q.where(SalesDeal.customer_id == customer_id)
        if stage:
            cls._assert_stage(stage)
            q = q.where(SalesDeal.stage == stage)
            count_q = count_q.where(SalesDeal.stage == stage)
        total = (await db.execute(count_q)).scalar_one()
        rows = (await db.execute(
            q.order_by(SalesDeal.updated_at.desc()).offset(skip).limit(limit)
        )).scalars().all()
        return [cls._deal_to_dict(d) for d in rows], total

    @classmethod
    async def get_deal(cls, db: AsyncSession, deal_id: UUID, tenant_id: UUID | None) -> dict:
        q = (
            select(SalesDeal)
            .options(selectinload(SalesDeal.customer), selectinload(SalesDeal.lead))
            .where(SalesDeal.id == deal_id)
        )
        if tenant_id is not None:
            q = q.where(SalesDeal.tenant_id == tenant_id)
        deal = (await db.execute(q)).scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        return cls._deal_to_dict(deal)

    @classmethod
    async def create_deal(
        cls,
        db: AsyncSession,
        body: SalesDealCreate,
        tenant_id: UUID,
        created_by: str | None = None,
    ) -> dict:
        cls._assert_stage(body.stage)
        if body.customer_id:
            await cls._load_customer(db, body.customer_id, tenant_id)
        if body.lead_id:
            await cls._load_lead(db, body.lead_id, tenant_id)
        row = SalesDeal(tenant_id=tenant_id, **body.model_dump())
        db.add(row)
        await db.flush()
        activity = SalesActivity(
            tenant_id=tenant_id,
            type="note",
            title=f"Deal created: {row.title}",
            description=row.notes,
            deal_id=row.id,
            customer_id=row.customer_id,
            lead_id=row.lead_id,
            created_by=created_by,
            activity_date=datetime.now(timezone.utc),
        )
        db.add(activity)
        await db.commit()
        return await cls.get_deal(db, row.id, tenant_id)

    @classmethod
    async def update_deal(
        cls,
        db: AsyncSession,
        deal_id: UUID,
        body: SalesDealUpdate,
        tenant_id: UUID | None,
    ) -> dict:
        row = await cls._load_deal(db, deal_id, tenant_id)
        data = body.model_dump(exclude_unset=True)
        if "stage" in data:
            cls._assert_stage(data["stage"])
        if data.get("customer_id"):
            await cls._load_customer(db, data["customer_id"], row.tenant_id)
        if data.get("lead_id"):
            await cls._load_lead(db, data["lead_id"], row.tenant_id)
        for key, val in data.items():
            setattr(row, key, val)
        await db.commit()
        return await cls.get_deal(db, deal_id, tenant_id)

    @classmethod
    async def move_deal_stage(
        cls,
        db: AsyncSession,
        deal_id: UUID,
        body: SalesDealStageUpdate,
        tenant_id: UUID | None,
        created_by: str | None = None,
    ) -> dict:
        cls._assert_stage(body.stage)
        row = await cls._load_deal(db, deal_id, tenant_id)
        old_stage = row.stage
        row.stage = body.stage
        activity = SalesActivity(
            tenant_id=row.tenant_id,
            type="note",
            title=f"Deal moved: {old_stage} → {body.stage}",
            deal_id=row.id,
            customer_id=row.customer_id,
            lead_id=row.lead_id,
            created_by=created_by,
            activity_date=datetime.now(timezone.utc),
        )
        db.add(activity)
        await db.commit()
        return await cls.get_deal(db, deal_id, tenant_id)

    @classmethod
    async def delete_deal(cls, db: AsyncSession, deal_id: UUID, tenant_id: UUID | None) -> None:
        row = await cls._load_deal(db, deal_id, tenant_id)
        await db.delete(row)
        await db.commit()

    # ─── Activities ──────────────────────────────────────────────────────────

    @classmethod
    async def list_activities(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        lead_id: UUID | None = None,
        customer_id: UUID | None = None,
        deal_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[SalesActivity], int]:
        q = select(SalesActivity)
        count_q = select(func.count()).select_from(SalesActivity)
        if tenant_id is not None:
            q = q.where(SalesActivity.tenant_id == tenant_id)
            count_q = count_q.where(SalesActivity.tenant_id == tenant_id)
        if lead_id:
            q = q.where(SalesActivity.lead_id == lead_id)
            count_q = count_q.where(SalesActivity.lead_id == lead_id)
        if customer_id:
            q = q.where(SalesActivity.customer_id == customer_id)
            count_q = count_q.where(SalesActivity.customer_id == customer_id)
        if deal_id:
            q = q.where(SalesActivity.deal_id == deal_id)
            count_q = count_q.where(SalesActivity.deal_id == deal_id)
        total = (await db.execute(count_q)).scalar_one()
        rows = (await db.execute(
            q.order_by(SalesActivity.activity_date.desc()).offset(skip).limit(limit)
        )).scalars().all()
        return list(rows), total

    @classmethod
    async def create_activity(
        cls,
        db: AsyncSession,
        body: SalesActivityCreate,
        tenant_id: UUID,
        created_by: str | None = None,
    ) -> SalesActivity:
        cls._assert_activity_type(body.type)
        if body.lead_id:
            await cls._load_lead(db, body.lead_id, tenant_id)
        if body.customer_id:
            await cls._load_customer(db, body.customer_id, tenant_id)
        if body.deal_id:
            await cls._load_deal(db, body.deal_id, tenant_id)
        row = SalesActivity(
            tenant_id=tenant_id,
            created_by=created_by,
            activity_date=body.activity_date or datetime.now(timezone.utc),
            **body.model_dump(exclude={"activity_date"}),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row
