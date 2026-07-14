"""Tenant-scoped Buyer Network CRM business logic."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_crm import (
    BUYER_ACTIVITY_TYPES,
    BUYER_ENTITY_TYPES,
    BUYER_STATUSES,
    Buyer,
    BuyerActivity,
    BuyerEntityLink,
    BuyerNote,
    BuyerStatusHistory,
)
from app.models.sales_crm import SalesCustomer, SalesDeal, SalesLead, SalesProposal
from app.schemas.buyer_crm import (
    BuyerActivityCreate,
    BuyerCreate,
    BuyerDashboardResponse,
    BuyerDetailResponse,
    BuyerEntityLinkCreate,
    BuyerLinkedEntity,
    BuyerNoteCreate,
    BuyerResponse,
    BuyerTimelineItem,
    BuyerTimelineResponse,
    BuyerUpdate,
    DistributionItem,
)
from app.services.automation_domain_events import emit_domain_event


class BuyerCrmService:
    @staticmethod
    def _assert_status(status: str) -> None:
        if status not in BUYER_STATUSES:
            raise HTTPException(status_code=422, detail=f"Invalid buyer status: {status}")

    @staticmethod
    def _assert_activity_type(activity_type: str) -> None:
        if activity_type not in BUYER_ACTIVITY_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid activity type: {activity_type}")

    @staticmethod
    def _assert_entity_type(entity_type: str) -> None:
        if entity_type not in BUYER_ENTITY_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid entity type: {entity_type}")

    @staticmethod
    async def _load_buyer(db: AsyncSession, buyer_id: UUID, tenant_id: UUID | None) -> Buyer:
        q = select(Buyer).where(Buyer.id == buyer_id)
        if tenant_id is not None:
            q = q.where(Buyer.tenant_id == tenant_id)
        row = (await db.execute(q)).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Buyer not found")
        return row

    @staticmethod
    def _buyer_to_response(buyer: Buyer, link_count: int = 0) -> BuyerResponse:
        return BuyerResponse(
            id=buyer.id,
            tenant_id=buyer.tenant_id,
            company_name=buyer.company_name,
            contact_person=buyer.contact_person,
            country=buyer.country,
            city=buyer.city,
            industry=buyer.industry,
            website=buyer.website,
            email=buyer.email,
            phone=buyer.phone,
            telegram=buyer.telegram,
            whatsapp=buyer.whatsapp,
            wechat=buyer.wechat,
            annual_purchase_volume=buyer.annual_purchase_volume,
            product_categories=buyer.product_categories or [],
            notes=buyer.notes,
            tags=buyer.tags or [],
            status=buyer.status,
            created_at=buyer.created_at,
            updated_at=buyer.updated_at,
            link_count=link_count,
        )

    @classmethod
    async def _entity_label(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        entity_type: str,
        entity_id: UUID,
    ) -> str:
        if entity_type == "lead":
            row = (await db.execute(
                select(SalesLead).where(SalesLead.id == entity_id, SalesLead.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if row:
                return row.company or row.name
        elif entity_type == "deal":
            row = (await db.execute(
                select(SalesDeal).where(SalesDeal.id == entity_id, SalesDeal.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if row:
                return row.title
        elif entity_type == "customer":
            row = (await db.execute(
                select(SalesCustomer).where(SalesCustomer.id == entity_id, SalesCustomer.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if row:
                return row.company or row.name
        elif entity_type == "proposal":
            row = (await db.execute(
                select(SalesProposal).where(SalesProposal.id == entity_id, SalesProposal.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if row:
                return row.title
        return str(entity_id)[:8]

    @classmethod
    async def _validate_entity(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        entity_type: str,
        entity_id: UUID,
    ) -> None:
        cls._assert_entity_type(entity_type)
        label = await cls._entity_label(db, tenant_id, entity_type, entity_id)
        if label == str(entity_id)[:8]:
            raise HTTPException(status_code=404, detail=f"{entity_type.title()} not found")

    @classmethod
    async def _link_count(cls, db: AsyncSession, buyer_id: UUID) -> int:
        q = select(func.count()).select_from(BuyerEntityLink).where(BuyerEntityLink.buyer_id == buyer_id)
        return (await db.execute(q)).scalar_one()

    @classmethod
    async def _record_status_change(
        cls,
        db: AsyncSession,
        buyer: Buyer,
        from_status: str | None,
        to_status: str,
        changed_by: str | None,
        note: str | None = None,
    ) -> None:
        history = BuyerStatusHistory(
            tenant_id=buyer.tenant_id,
            buyer_id=buyer.id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            changed_by=changed_by,
        )
        activity = BuyerActivity(
            tenant_id=buyer.tenant_id,
            buyer_id=buyer.id,
            type="status_change",
            title=f"Status changed to {to_status.replace('_', ' ').title()}",
            description=note,
            metadata_json={"from_status": from_status, "to_status": to_status},
            created_by=changed_by,
        )
        db.add_all([history, activity])

    # ─── Dashboard ───────────────────────────────────────────────────────────

    @classmethod
    async def dashboard(cls, db: AsyncSession, tenant_id: UUID | None) -> BuyerDashboardResponse:
        q = select(Buyer)
        if tenant_id is not None:
            q = q.where(Buyer.tenant_id == tenant_id)
        buyers = (await db.execute(q)).scalars().all()

        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        by_status: dict[str, int] = {}
        by_country: dict[str, int] = {}
        by_industry: dict[str, int] = {}
        new_this_month = 0
        active = 0

        for buyer in buyers:
            by_status[buyer.status] = by_status.get(buyer.status, 0) + 1
            if buyer.status == "active_buyer":
                active += 1
            if buyer.created_at >= month_start:
                new_this_month += 1
            if buyer.country:
                by_country[buyer.country] = by_country.get(buyer.country, 0) + 1
            if buyer.industry:
                by_industry[buyer.industry] = by_industry.get(buyer.industry, 0) + 1

        def top_items(d: dict[str, int], limit: int = 5) -> list[DistributionItem]:
            sorted_items = sorted(d.items(), key=lambda x: (-x[1], x[0]))[:limit]
            return [DistributionItem(label=k, count=v) for k, v in sorted_items]

        def all_items(d: dict[str, int]) -> list[DistributionItem]:
            sorted_items = sorted(d.items(), key=lambda x: (-x[1], x[0]))
            return [DistributionItem(label=k, count=v) for k, v in sorted_items]

        return BuyerDashboardResponse(
            total_buyers=len(buyers),
            active_buyers=active,
            new_buyers_this_month=new_this_month,
            top_industries=top_items(by_industry),
            top_countries=top_items(by_country),
            geographic_distribution=all_items(by_country),
            industry_distribution=all_items(by_industry),
            by_status=by_status,
        )

    # ─── Buyers CRUD ─────────────────────────────────────────────────────────

    @classmethod
    async def list_buyers(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        search: str | None = None,
        status: str | None = None,
        country: str | None = None,
        industry: str | None = None,
        tag: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[BuyerResponse], int]:
        q = select(Buyer)
        count_q = select(func.count()).select_from(Buyer)
        if tenant_id is not None:
            q = q.where(Buyer.tenant_id == tenant_id)
            count_q = count_q.where(Buyer.tenant_id == tenant_id)
        if status:
            cls._assert_status(status)
            q = q.where(Buyer.status == status)
            count_q = count_q.where(Buyer.status == status)
        if country:
            q = q.where(Buyer.country == country)
            count_q = count_q.where(Buyer.country == country)
        if industry:
            q = q.where(Buyer.industry == industry)
            count_q = count_q.where(Buyer.industry == industry)
        if tag:
            q = q.where(Buyer.tags.contains([tag]))
            count_q = count_q.where(Buyer.tags.contains([tag]))
        if search:
            term = f"%{search.strip()}%"
            filt = or_(
                Buyer.company_name.ilike(term),
                Buyer.contact_person.ilike(term),
                Buyer.email.ilike(term),
                Buyer.phone.ilike(term),
                Buyer.city.ilike(term),
            )
            q = q.where(filt)
            count_q = count_q.where(filt)

        total = (await db.execute(count_q)).scalar_one()
        rows = (await db.execute(
            q.order_by(Buyer.updated_at.desc()).offset(skip).limit(limit)
        )).scalars().all()

        items: list[BuyerResponse] = []
        for buyer in rows:
            link_count = await cls._link_count(db, buyer.id)
            items.append(cls._buyer_to_response(buyer, link_count))
        return items, total

    @classmethod
    async def get_buyer(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
    ) -> BuyerDetailResponse:
        buyer = await cls._load_buyer(db, buyer_id, tenant_id)
        links = (await db.execute(
            select(BuyerEntityLink).where(BuyerEntityLink.buyer_id == buyer.id)
        )).scalars().all()

        linked_leads: list[BuyerLinkedEntity] = []
        linked_deals: list[BuyerLinkedEntity] = []
        linked_customers: list[BuyerLinkedEntity] = []
        linked_proposals: list[BuyerLinkedEntity] = []

        for link in links:
            label = await cls._entity_label(db, buyer.tenant_id, link.entity_type, link.entity_id)
            entity = BuyerLinkedEntity(
                link_id=link.id,
                entity_type=link.entity_type,
                entity_id=link.entity_id,
                label=label,
                created_at=link.created_at,
            )
            if link.entity_type == "lead":
                linked_leads.append(entity)
            elif link.entity_type == "deal":
                linked_deals.append(entity)
            elif link.entity_type == "customer":
                linked_customers.append(entity)
            elif link.entity_type == "proposal":
                linked_proposals.append(entity)

        base = cls._buyer_to_response(buyer, len(links))
        return BuyerDetailResponse(
            **base.model_dump(),
            linked_leads=linked_leads,
            linked_deals=linked_deals,
            linked_customers=linked_customers,
            linked_proposals=linked_proposals,
        )

    @classmethod
    async def create_buyer(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        data: BuyerCreate,
        created_by: str | None = None,
    ) -> BuyerResponse:
        cls._assert_status(data.status)
        buyer = Buyer(
            tenant_id=tenant_id,
            company_name=data.company_name.strip(),
            contact_person=data.contact_person,
            country=data.country,
            city=data.city,
            industry=data.industry,
            website=data.website,
            email=data.email,
            phone=data.phone,
            telegram=data.telegram,
            whatsapp=data.whatsapp,
            wechat=data.wechat,
            annual_purchase_volume=data.annual_purchase_volume,
            product_categories=data.product_categories,
            notes=data.notes,
            tags=data.tags,
            status=data.status,
        )
        db.add(buyer)
        await db.flush()
        await cls._record_status_change(db, buyer, None, data.status, created_by, "Buyer created")
        await emit_domain_event(
            db,
            "tenant.buyer.created",
            tenant_id,
            payload={
                "buyer_id": str(buyer.id),
                "buyer_name": (buyer.contact_person or buyer.company_name or "").strip() or "Buyer",
                "company_name": buyer.company_name,
                "company": buyer.company_name,
                "country": buyer.country,
                "industry": buyer.industry,
                "source": "api",
            },
            actor_type="user" if created_by else "system",
            resource_type="buyer",
            resource_id=str(buyer.id),
            title=f"Buyer created: {buyer.company_name}",
            description="Durable buyer CRM record persisted",
        )
        await db.commit()
        await db.refresh(buyer)
        return cls._buyer_to_response(buyer, 0)

    @classmethod
    async def update_buyer(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
        data: BuyerUpdate,
        changed_by: str | None = None,
    ) -> BuyerResponse:
        buyer = await cls._load_buyer(db, buyer_id, tenant_id)
        old_status = buyer.status
        updates = data.model_dump(exclude_unset=True)
        if "status" in updates and updates["status"] is not None:
            cls._assert_status(updates["status"])
        if "company_name" in updates and updates["company_name"]:
            updates["company_name"] = updates["company_name"].strip()
        for key, value in updates.items():
            setattr(buyer, key, value)
        if "status" in updates and updates["status"] != old_status:
            await cls._record_status_change(
                db, buyer, old_status, updates["status"], changed_by,
            )
        await db.commit()
        await db.refresh(buyer)
        link_count = await cls._link_count(db, buyer.id)
        return cls._buyer_to_response(buyer, link_count)

    @classmethod
    async def delete_buyer(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
    ) -> None:
        buyer = await cls._load_buyer(db, buyer_id, tenant_id)
        await db.delete(buyer)
        await db.commit()

    # ─── Activities ──────────────────────────────────────────────────────────

    @classmethod
    async def list_activities(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[BuyerActivity], int]:
        await cls._load_buyer(db, buyer_id, tenant_id)
        q = select(BuyerActivity).where(BuyerActivity.buyer_id == buyer_id)
        count_q = select(func.count()).select_from(BuyerActivity).where(BuyerActivity.buyer_id == buyer_id)
        if tenant_id is not None:
            q = q.where(BuyerActivity.tenant_id == tenant_id)
            count_q = count_q.where(BuyerActivity.tenant_id == tenant_id)
        total = (await db.execute(count_q)).scalar_one()
        items = (await db.execute(
            q.order_by(BuyerActivity.activity_date.desc()).offset(skip).limit(limit)
        )).scalars().all()
        return list(items), total

    @classmethod
    async def create_activity(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
        data: BuyerActivityCreate,
        created_by: str | None = None,
    ) -> BuyerActivity:
        buyer = await cls._load_buyer(db, buyer_id, tenant_id)
        cls._assert_activity_type(data.type)
        activity = BuyerActivity(
            tenant_id=buyer.tenant_id,
            buyer_id=buyer.id,
            type=data.type,
            title=data.title.strip(),
            description=data.description,
            activity_date=data.activity_date or datetime.now(timezone.utc),
            created_by=created_by,
        )
        db.add(activity)
        await db.commit()
        await db.refresh(activity)
        return activity

    # ─── Notes ───────────────────────────────────────────────────────────────

    @classmethod
    async def list_notes(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[BuyerNote], int]:
        await cls._load_buyer(db, buyer_id, tenant_id)
        q = select(BuyerNote).where(BuyerNote.buyer_id == buyer_id)
        count_q = select(func.count()).select_from(BuyerNote).where(BuyerNote.buyer_id == buyer_id)
        if tenant_id is not None:
            q = q.where(BuyerNote.tenant_id == tenant_id)
            count_q = count_q.where(BuyerNote.tenant_id == tenant_id)
        total = (await db.execute(count_q)).scalar_one()
        items = (await db.execute(
            q.order_by(BuyerNote.created_at.desc()).offset(skip).limit(limit)
        )).scalars().all()
        return list(items), total

    @classmethod
    async def create_note(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
        data: BuyerNoteCreate,
        created_by: str | None = None,
    ) -> BuyerNote:
        buyer = await cls._load_buyer(db, buyer_id, tenant_id)
        note = BuyerNote(
            tenant_id=buyer.tenant_id,
            buyer_id=buyer.id,
            content=data.content.strip(),
            created_by=created_by,
        )
        db.add(note)
        activity = BuyerActivity(
            tenant_id=buyer.tenant_id,
            buyer_id=buyer.id,
            type="note",
            title="Note added",
            description=data.content.strip()[:500],
            created_by=created_by,
        )
        db.add(activity)
        await db.commit()
        await db.refresh(note)
        return note

    @classmethod
    async def delete_note(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        note_id: UUID,
        tenant_id: UUID | None,
    ) -> None:
        await cls._load_buyer(db, buyer_id, tenant_id)
        q = select(BuyerNote).where(BuyerNote.id == note_id, BuyerNote.buyer_id == buyer_id)
        if tenant_id is not None:
            q = q.where(BuyerNote.tenant_id == tenant_id)
        note = (await db.execute(q)).scalar_one_or_none()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        await db.delete(note)
        await db.commit()

    # ─── Status history ──────────────────────────────────────────────────────

    @classmethod
    async def list_status_history(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[BuyerStatusHistory], int]:
        await cls._load_buyer(db, buyer_id, tenant_id)
        q = select(BuyerStatusHistory).where(BuyerStatusHistory.buyer_id == buyer_id)
        count_q = select(func.count()).select_from(BuyerStatusHistory).where(
            BuyerStatusHistory.buyer_id == buyer_id
        )
        if tenant_id is not None:
            q = q.where(BuyerStatusHistory.tenant_id == tenant_id)
            count_q = count_q.where(BuyerStatusHistory.tenant_id == tenant_id)
        total = (await db.execute(count_q)).scalar_one()
        items = (await db.execute(
            q.order_by(BuyerStatusHistory.changed_at.desc()).offset(skip).limit(limit)
        )).scalars().all()
        return list(items), total

    # ─── Entity links ────────────────────────────────────────────────────────

    @classmethod
    async def list_links(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
    ) -> list[BuyerLinkedEntity]:
        buyer = await cls._load_buyer(db, buyer_id, tenant_id)
        links = (await db.execute(
            select(BuyerEntityLink).where(BuyerEntityLink.buyer_id == buyer.id)
        )).scalars().all()
        result: list[BuyerLinkedEntity] = []
        for link in links:
            label = await cls._entity_label(db, buyer.tenant_id, link.entity_type, link.entity_id)
            result.append(BuyerLinkedEntity(
                link_id=link.id,
                entity_type=link.entity_type,
                entity_id=link.entity_id,
                label=label,
                created_at=link.created_at,
            ))
        return result

    @classmethod
    async def create_link(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
        data: BuyerEntityLinkCreate,
        created_by: str | None = None,
    ) -> BuyerLinkedEntity:
        buyer = await cls._load_buyer(db, buyer_id, tenant_id)
        await cls._validate_entity(db, buyer.tenant_id, data.entity_type, data.entity_id)

        existing = (await db.execute(
            select(BuyerEntityLink).where(
                BuyerEntityLink.buyer_id == buyer.id,
                BuyerEntityLink.entity_type == data.entity_type,
                BuyerEntityLink.entity_id == data.entity_id,
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Link already exists")

        link = BuyerEntityLink(
            tenant_id=buyer.tenant_id,
            buyer_id=buyer.id,
            entity_type=data.entity_type,
            entity_id=data.entity_id,
        )
        label = await cls._entity_label(db, buyer.tenant_id, data.entity_type, data.entity_id)
        activity = BuyerActivity(
            tenant_id=buyer.tenant_id,
            buyer_id=buyer.id,
            type="link",
            title=f"Linked to {data.entity_type}: {label}",
            metadata_json={"entity_type": data.entity_type, "entity_id": str(data.entity_id)},
            created_by=created_by,
        )
        db.add_all([link, activity])
        await db.commit()
        await db.refresh(link)
        return BuyerLinkedEntity(
            link_id=link.id,
            entity_type=link.entity_type,
            entity_id=link.entity_id,
            label=label,
            created_at=link.created_at,
        )

    @classmethod
    async def delete_link(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        link_id: UUID,
        tenant_id: UUID | None,
    ) -> None:
        await cls._load_buyer(db, buyer_id, tenant_id)
        q = select(BuyerEntityLink).where(
            BuyerEntityLink.id == link_id,
            BuyerEntityLink.buyer_id == buyer_id,
        )
        if tenant_id is not None:
            q = q.where(BuyerEntityLink.tenant_id == tenant_id)
        link = (await db.execute(q)).scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        await db.delete(link)
        await db.commit()

    # ─── Timeline ────────────────────────────────────────────────────────────

    @classmethod
    async def timeline(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
        limit: int = 100,
    ) -> BuyerTimelineResponse:
        await cls._load_buyer(db, buyer_id, tenant_id)
        activities, _ = await cls.list_activities(db, buyer_id, tenant_id, limit=limit)
        notes, _ = await cls.list_notes(db, buyer_id, tenant_id, limit=limit)
        history, _ = await cls.list_status_history(db, buyer_id, tenant_id, limit=limit)

        items: list[BuyerTimelineItem] = []
        for act in activities:
            if act.type == "note":
                continue
            items.append(BuyerTimelineItem(
                id=act.id,
                kind="activity",
                title=act.title,
                description=act.description,
                occurred_at=act.activity_date,
                meta={"type": act.type, **(act.metadata_json or {})},
            ))
        for note in notes:
            items.append(BuyerTimelineItem(
                id=note.id,
                kind="note",
                title="Note",
                description=note.content,
                occurred_at=note.created_at,
                meta={"created_by": note.created_by},
            ))
        for entry in history:
            if entry.from_status is None:
                continue
            items.append(BuyerTimelineItem(
                id=entry.id,
                kind="status_change",
                title=f"Status: {entry.from_status} → {entry.to_status}",
                description=entry.note,
                occurred_at=entry.changed_at,
                meta={"from_status": entry.from_status, "to_status": entry.to_status},
            ))

        items.sort(key=lambda x: x.occurred_at, reverse=True)
        items = items[:limit]
        return BuyerTimelineResponse(items=items, total=len(items))
