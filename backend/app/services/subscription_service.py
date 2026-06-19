"""Subscription & Billing v1 — plan management, subscriptions, usage limits (no payment processing)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.subscription import (
    BILLING_CYCLES,
    INVOICE_STATUSES,
    SUBSCRIPTION_STATUSES,
    Invoice,
    Plan,
    Subscription,
)
from app.models.tenant import Tenant, TenantUser
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Subscription]"

_BUYER_STATUSES = frozenset({
    "qualified", "proposal", "negotiation", "hot", "won", "contacted",
})

DEFAULT_PLANS: list[dict[str, Any]] = [
    {
        "code": "free",
        "name": "Free",
        "monthly_price": 0,
        "yearly_price": 0,
        "max_users": 2,
        "max_leads": 50,
        "max_buyers": 10,
        "max_deals": 5,
        "features": ["crm", "basic_inbox"],
    },
    {
        "code": "professional",
        "name": "Professional",
        "monthly_price": 99,
        "yearly_price": 990,
        "max_users": 10,
        "max_leads": 500,
        "max_buyers": 100,
        "max_deals": 50,
        "features": ["crm", "inbox", "intelligence", "proposals", "buyer_finder"],
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "monthly_price": 299,
        "yearly_price": 2990,
        "max_users": None,
        "max_leads": None,
        "max_buyers": None,
        "max_deals": None,
        "features": ["all", "executive_copilot", "multi_agent", "priority_support"],
    },
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _float_val(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _utilization(current: int, limit: int | None) -> float | None:
    if limit is None or limit <= 0:
        return None
    return round(min(100.0, (current / limit) * 100), 1)


def _usage_metric(current: int, limit: int | None) -> dict[str, Any]:
    return {
        "current": current,
        "limit": limit,
        "utilization_pct": _utilization(current, limit),
    }


def _serialize_plan(plan: Plan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "name": plan.name,
        "code": plan.code,
        "monthly_price": _float_val(plan.monthly_price),
        "yearly_price": _float_val(plan.yearly_price),
        "max_users": plan.max_users,
        "max_leads": plan.max_leads,
        "max_buyers": plan.max_buyers,
        "max_deals": plan.max_deals,
        "features": plan.features or [],
        "created_at": plan.created_at,
    }


def _serialize_subscription(sub: Subscription, plan: Plan | None = None) -> dict[str, Any]:
    p = plan or sub.plan if hasattr(sub, "plan") and sub.plan else None
    return {
        "id": sub.id,
        "tenant_id": sub.tenant_id,
        "plan_id": sub.plan_id,
        "plan_name": p.name if p else None,
        "plan_code": p.code if p else None,
        "status": sub.status,
        "billing_cycle": sub.billing_cycle,
        "starts_at": sub.starts_at,
        "expires_at": sub.expires_at,
        "created_at": sub.created_at,
    }


def _serialize_invoice(inv: Invoice) -> dict[str, Any]:
    return {
        "id": inv.id,
        "tenant_id": inv.tenant_id,
        "subscription_id": inv.subscription_id,
        "amount": _float_val(inv.amount),
        "currency": inv.currency,
        "status": inv.status,
        "invoice_date": inv.invoice_date,
        "due_date": inv.due_date,
    }


class SubscriptionService:
    """Architecture-only billing — no payment providers, card storage, or auto-charges."""

    @staticmethod
    async def ensure_default_plans(db: AsyncSession) -> None:
        count = int(await db.scalar(select(func.count()).select_from(Plan)) or 0)
        if count > 0:
            return
        for spec in DEFAULT_PLANS:
            db.add(Plan(**spec))
        await db.commit()
        logger.info("%s seeded %d default plans", MARKER, len(DEFAULT_PLANS))

    @staticmethod
    async def list_plans(db: AsyncSession) -> dict[str, Any]:
        await SubscriptionService.ensure_default_plans(db)
        result = await db.execute(select(Plan).order_by(Plan.monthly_price))
        items = [_serialize_plan(p) for p in result.scalars().all()]
        return {"items": items, "total": len(items)}

    @staticmethod
    async def _get_plan_by_code(db: AsyncSession, code: str) -> Plan:
        await SubscriptionService.ensure_default_plans(db)
        result = await db.execute(select(Plan).where(Plan.code == code.lower()))
        plan = result.scalar_one_or_none()
        if not plan:
            raise HTTPException(status_code=404, detail=f"Plan not found: {code}")
        return plan

    @staticmethod
    async def list_subscriptions(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        query = (
            select(Subscription)
            .options(selectinload(Subscription.plan))
            .order_by(Subscription.created_at.desc())
        )
        count_q = select(func.count()).select_from(Subscription)
        if tenant_id:
            query = query.where(Subscription.tenant_id == tenant_id)
            count_q = count_q.where(Subscription.tenant_id == tenant_id)
        if status:
            if status not in SUBSCRIPTION_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid subscription status")
            query = query.where(Subscription.status == status)
            count_q = count_q.where(Subscription.status == status)
        total = int(await db.scalar(count_q) or 0)
        result = await db.execute(query.offset(skip).limit(clamp_limit(limit)))
        items = [_serialize_subscription(s) for s in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def list_invoices(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        query = select(Invoice).order_by(Invoice.invoice_date.desc())
        count_q = select(func.count()).select_from(Invoice)
        if tenant_id:
            query = query.where(Invoice.tenant_id == tenant_id)
            count_q = count_q.where(Invoice.tenant_id == tenant_id)
        if status:
            if status not in INVOICE_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid invoice status")
            query = query.where(Invoice.status == status)
            count_q = count_q.where(Invoice.status == status)
        total = int(await db.scalar(count_q) or 0)
        result = await db.execute(query.offset(skip).limit(clamp_limit(limit)))
        items = [_serialize_invoice(i) for i in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def _count_usage(db: AsyncSession, tenant_id: UUID) -> dict[str, int]:
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        users = int(
            await db.scalar(
                select(func.count())
                .select_from(TenantUser)
                .where(TenantUser.tenant_id == tenant_id, TenantUser.status == "active"),
            ) or 0,
        )
        leads = buyers = deals = 0
        if client_ids:
            leads = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmLead)
                    .where(CrmLead.client_id.in_(client_ids)),
                ) or 0,
            )
            buyers = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmLead)
                    .where(
                        CrmLead.client_id.in_(client_ids),
                        CrmLead.status.in_(_BUYER_STATUSES),
                    ),
                ) or 0,
            )
            deals = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmDeal)
                    .where(CrmDeal.client_id.in_(client_ids)),
                ) or 0,
            )
        return {"users": users, "leads": leads, "buyers": buyers, "deals": deals}

    @staticmethod
    async def _active_subscription(db: AsyncSession, tenant_id: UUID) -> tuple[Subscription | None, Plan | None]:
        result = await db.execute(
            select(Subscription)
            .options(selectinload(Subscription.plan))
            .where(
                Subscription.tenant_id == tenant_id,
                Subscription.status.in_(("trial", "active", "suspended")),
            )
            .order_by(Subscription.created_at.desc())
            .limit(1),
        )
        sub = result.scalar_one_or_none()
        if not sub:
            return None, None
        plan_r = await db.execute(select(Plan).where(Plan.id == sub.plan_id))
        plan = plan_r.scalar_one_or_none()
        return sub, plan

    @staticmethod
    async def _resolve_plan_for_tenant(db: AsyncSession, tenant_id: UUID) -> Plan:
        _, plan = await SubscriptionService._active_subscription(db, tenant_id)
        if plan:
            return plan
        return await SubscriptionService._get_plan_by_code(db, "free")

    @staticmethod
    async def usage(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        await TenantService.get_tenant(db, tenant_id)
        counts = await SubscriptionService._count_usage(db, tenant_id)
        plan = await SubscriptionService._resolve_plan_for_tenant(db, tenant_id)
        limits = {
            "users": plan.max_users,
            "leads": plan.max_leads,
            "buyers": plan.max_buyers,
            "deals": plan.max_deals,
        }
        return {
            "tenant_id": tenant_id,
            "users": _usage_metric(counts["users"], limits["users"]),
            "leads": _usage_metric(counts["leads"], limits["leads"]),
            "buyers": _usage_metric(counts["buyers"], limits["buyers"]),
            "deals": _usage_metric(counts["deals"], limits["deals"]),
        }

    @staticmethod
    async def summary(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        await TenantService.get_tenant(db, tenant_id)
        sub, plan = await SubscriptionService._active_subscription(db, tenant_id)
        usage_summary = await SubscriptionService.usage(db, tenant_id)
        if not sub or not plan:
            free_plan = await SubscriptionService._get_plan_by_code(db, "free")
            return {
                "plan": _serialize_plan(free_plan),
                "status": None,
                "next_renewal": None,
                "monthly_price": _float_val(free_plan.monthly_price),
                "usage_summary": usage_summary,
            }
        monthly_price = (
            _float_val(plan.yearly_price) / 12
            if sub.billing_cycle == "yearly"
            else _float_val(plan.monthly_price)
        )
        return {
            "plan": _serialize_plan(plan),
            "status": sub.status,
            "next_renewal": sub.expires_at,
            "monthly_price": round(monthly_price, 2),
            "usage_summary": usage_summary,
        }

    @staticmethod
    async def get_subscription(db: AsyncSession, subscription_id: UUID) -> Subscription:
        return await SubscriptionService._get_subscription(db, subscription_id)

    @staticmethod
    async def _get_subscription(db: AsyncSession, subscription_id: UUID) -> Subscription:
        result = await db.execute(
            select(Subscription).where(Subscription.id == subscription_id),
        )
        sub = result.scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return sub

    @staticmethod
    async def create_subscription(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        plan_code: str,
        billing_cycle: str = "monthly",
        status: str = "trial",
    ) -> dict[str, Any]:
        if billing_cycle not in BILLING_CYCLES:
            raise HTTPException(status_code=400, detail="Invalid billing cycle")
        if status not in SUBSCRIPTION_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid subscription status")

        await TenantService.get_tenant(db, tenant_id)
        plan = await SubscriptionService._get_plan_by_code(db, plan_code)

        existing = await db.execute(
            select(Subscription).where(
                Subscription.tenant_id == tenant_id,
                Subscription.status.in_(("trial", "active", "suspended")),
            ),
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="Tenant already has an active subscription. Cancel or suspend it first.",
            )

        now = _utc_now()
        if billing_cycle == "yearly":
            expires = now + timedelta(days=365)
            amount = _float_val(plan.yearly_price)
        else:
            expires = now + timedelta(days=30)
            amount = _float_val(plan.monthly_price)

        sub = Subscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            status=status,
            billing_cycle=billing_cycle,
            starts_at=now,
            expires_at=expires,
        )
        db.add(sub)
        await db.flush()

        invoice = Invoice(
            tenant_id=tenant_id,
            subscription_id=sub.id,
            amount=amount,
            currency="USD",
            status="draft",
            invoice_date=now,
            due_date=expires,
        )
        db.add(invoice)
        await db.commit()
        await db.refresh(sub)

        logger.info(
            "%s created subscription tenant=%s plan=%s status=%s",
            MARKER, tenant_id, plan_code, status,
        )
        return _serialize_subscription(sub, plan)

    @staticmethod
    async def activate_subscription(db: AsyncSession, subscription_id: UUID) -> dict[str, Any]:
        sub = await SubscriptionService._get_subscription(db, subscription_id)
        if sub.status == "cancelled":
            raise HTTPException(status_code=400, detail="Cannot activate a cancelled subscription")
        sub.status = "active"
        if sub.expires_at and sub.expires_at < _utc_now():
            delta = timedelta(days=365 if sub.billing_cycle == "yearly" else 30)
            sub.expires_at = _utc_now() + delta
        await db.commit()
        plan_r = await db.execute(select(Plan).where(Plan.id == sub.plan_id))
        plan = plan_r.scalar_one_or_none()
        logger.info("%s activated subscription=%s", MARKER, subscription_id)
        return _serialize_subscription(sub, plan)

    @staticmethod
    async def suspend_subscription(db: AsyncSession, subscription_id: UUID) -> dict[str, Any]:
        sub = await SubscriptionService._get_subscription(db, subscription_id)
        if sub.status in ("cancelled", "expired"):
            raise HTTPException(status_code=400, detail=f"Cannot suspend subscription in {sub.status} state")
        sub.status = "suspended"
        await db.commit()
        plan_r = await db.execute(select(Plan).where(Plan.id == sub.plan_id))
        plan = plan_r.scalar_one_or_none()
        logger.info("%s suspended subscription=%s", MARKER, subscription_id)
        return _serialize_subscription(sub, plan)

    @staticmethod
    async def cancel_subscription(db: AsyncSession, subscription_id: UUID) -> dict[str, Any]:
        sub = await SubscriptionService._get_subscription(db, subscription_id)
        sub.status = "cancelled"
        inv_result = await db.execute(
            select(Invoice).where(
                Invoice.subscription_id == subscription_id,
                Invoice.status.in_(("draft", "unpaid")),
            ),
        )
        for inv in inv_result.scalars().all():
            inv.status = "cancelled"
        await db.commit()
        plan_r = await db.execute(select(Plan).where(Plan.id == sub.plan_id))
        plan = plan_r.scalar_one_or_none()
        logger.info("%s cancelled subscription=%s", MARKER, subscription_id)
        return _serialize_subscription(sub, plan)

    @staticmethod
    async def tenant_subscription_overview(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        """Subscription overview for tenant detail panel."""
        billing = await SubscriptionService.summary(db, tenant_id)
        subs = await SubscriptionService.list_subscriptions(db, tenant_id=tenant_id, limit=5)
        return {
            "billing_summary": billing,
            "recent_subscriptions": subs["items"],
            "safety_notice": "Architecture only — no payment processing or automatic charges.",
        }

    @staticmethod
    async def executive_overview(db: AsyncSession) -> dict[str, Any]:
        await SubscriptionService.ensure_default_plans(db)
        active = int(
            await db.scalar(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.status == "active"),
            ) or 0,
        )
        trial = int(
            await db.scalar(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.status == "trial"),
            ) or 0,
        )
        subs_with_plans = await db.execute(
            select(Subscription, Plan)
            .join(Plan, Subscription.plan_id == Plan.id)
            .where(Subscription.status.in_(("trial", "active"))),
        )
        mrr = 0.0
        plan_dist: dict[str, int] = {}
        for sub, plan in subs_with_plans.all():
            plan_dist[plan.code] = plan_dist.get(plan.code, 0) + 1
            if sub.billing_cycle == "yearly":
                mrr += _float_val(plan.yearly_price) / 12
            else:
                mrr += _float_val(plan.monthly_price)

        return {
            "mrr": round(mrr, 2),
            "active_subscriptions": active,
            "trial_subscriptions": trial,
            "plan_distribution": plan_dist,
        }

    @staticmethod
    async def summary_widget(db: AsyncSession, *, tenant_id: UUID) -> dict[str, Any]:
        """Tenant-scoped billing widget — matches SubscriptionSummaryWidget schema."""
        summary = await SubscriptionService.summary(db, tenant_id)
        usage = summary.get("usage_summary")
        if not usage:
            usage = await SubscriptionService.usage(db, tenant_id)

        plan = summary.get("plan") or {}
        plan_code = str(plan.get("code") or "free")
        status = summary.get("status")
        monthly_price = float(summary.get("monthly_price") or 0.0)

        near_limit = 0
        for key in ("users", "leads", "buyers", "deals"):
            metric = usage.get(key) if isinstance(usage, dict) else None
            if (
                isinstance(metric, dict)
                and metric.get("utilization_pct") is not None
                and metric["utilization_pct"] >= 80
            ):
                near_limit = 1
                break

        return {
            "mrr": round(monthly_price, 2),
            "active_subscriptions": 1 if status == "active" else 0,
            "trial_subscriptions": 1 if status == "trial" else 0,
            "plan_distribution": {plan_code: 1},
            "tenants_near_limit": near_limit,
        }
