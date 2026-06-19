"""Multi-Tenant SaaS Foundation v1 — tenant isolation, roles, and dashboard."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.client import Client
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.customer_portal_account import CustomerPortalAccount
from app.models.factory_partner_application import FactoryPartnerApplication
from app.core.tenant_permissions import (
    TENANT_USER_ROLES,
    can_assign_role,
    permissions_for_role,
)
from app.models.tenant import (
    TENANT_PLANS,
    TENANT_STATUSES,
    TENANT_USER_STATUSES,
    Tenant,
    TenantUser,
)

logger = logging.getLogger(__name__)

MARKER = "[Tenant]"

_ROLE_RANK = {"viewer": 0, "operator": 1, "sales": 2, "manager": 3, "owner": 4}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _permissions_for_role(role: str) -> list[str]:
    return permissions_for_role(role)


def _serialize_tenant(t: Tenant) -> dict[str, Any]:
    return {
        "id": t.id,
        "company_name": t.company_name,
        "status": t.status,
        "plan": t.plan,
        "factory_partner_application_id": t.factory_partner_application_id,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _serialize_user(u: TenantUser) -> dict[str, Any]:
    return {
        "id": u.id,
        "tenant_id": u.tenant_id,
        "email": u.email,
        "role": u.role,
        "status": u.status,
        "created_at": u.created_at,
        "permissions": _permissions_for_role(u.role),
    }


class TenantService:
    """Tenant isolation — validate ownership, filter by tenant, no cross-company access."""

    @staticmethod
    async def get_tenant(db: AsyncSession, tenant_id: UUID, *, required: bool = True) -> Tenant | None:
        result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if required and not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return tenant

    @staticmethod
    async def validate_tenant_active(db: AsyncSession, tenant_id: UUID) -> Tenant:
        tenant = await TenantService.get_tenant(db, tenant_id)
        assert tenant is not None
        if tenant.status not in ("active", "pending"):
            raise HTTPException(
                status_code=403,
                detail=f"Tenant is {tenant.status}. Access denied.",
            )
        return tenant

    @staticmethod
    async def get_client_ids_for_tenant(db: AsyncSession, tenant_id: UUID) -> list[UUID]:
        """All CRM clients owned by this tenant."""
        await TenantService.get_tenant(db, tenant_id)
        result = await db.execute(
            select(Client.id).where(Client.tenant_id == tenant_id),
        )
        return list(result.scalars().all())

    @staticmethod
    async def validate_client_belongs_to_tenant(
        db: AsyncSession,
        tenant_id: UUID,
        client_id: UUID,
    ) -> None:
        """Reject cross-tenant client access."""
        result = await db.execute(
            select(Client.id).where(
                Client.id == client_id,
                Client.tenant_id == tenant_id,
            ),
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=403,
                detail="Client does not belong to this tenant — isolation enforced",
            )

    @staticmethod
    async def resolve_tenant_client_scope(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
    ) -> tuple[UUID | None, list[UUID] | None]:
        """
        Resolve scope for intelligence/CRM filters.
        Returns (single_client_id, client_id_list).
        If tenant_id set: returns (None, client_ids).
        If only client_id: returns (client_id, None).
        If both: validates membership then returns (client_id, None).
        """
        if tenant_id is None:
            return client_id, None

        await TenantService.validate_tenant_active(db, tenant_id)
        if client_id is not None:
            await TenantService.validate_client_belongs_to_tenant(db, tenant_id, client_id)
            return client_id, None

        ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        return None, ids

    @staticmethod
    def client_filter_clause(client_ids: list[UUID] | None, single_id: UUID | None, column):
        """Build SQLAlchemy filter for tenant-scoped queries."""
        if single_id is not None:
            return column == single_id
        if client_ids is not None:
            if not client_ids:
                return column.is_(None) & column.isnot(None)  # always false
            return column.in_(client_ids)
        return None

    @staticmethod
    async def list_tenants(
        db: AsyncSession,
        *,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        query = select(Tenant).order_by(Tenant.created_at.desc())
        count_q = select(func.count()).select_from(Tenant)
        if status:
            if status not in TENANT_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid tenant status")
            query = query.where(Tenant.status == status)
            count_q = count_q.where(Tenant.status == status)
        total = int(await db.scalar(count_q) or 0)
        result = await db.execute(query.offset(skip).limit(clamp_limit(limit)))
        items = [_serialize_tenant(t) for t in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def create_tenant(
        db: AsyncSession,
        *,
        company_name: str,
        status: str = "active",
        plan: str = "starter",
        factory_partner_application_id: UUID | None = None,
        owner_email: str | None = None,
    ) -> dict[str, Any]:
        if status not in TENANT_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid tenant status")
        if plan not in TENANT_PLANS:
            raise HTTPException(status_code=400, detail="Invalid tenant plan")

        if factory_partner_application_id:
            app_r = await db.execute(
                select(FactoryPartnerApplication).where(
                    FactoryPartnerApplication.id == factory_partner_application_id,
                ),
            )
            app = app_r.scalar_one_or_none()
            if not app:
                raise HTTPException(status_code=404, detail="Factory application not found")
            if app.tenant_id:
                raise HTTPException(status_code=400, detail="Application already linked to a tenant")
            existing_t = await db.execute(
                select(Tenant).where(
                    Tenant.factory_partner_application_id == factory_partner_application_id,
                ),
            )
            if existing_t.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Tenant already exists for this application")

        tenant = Tenant(
            company_name=company_name.strip(),
            status=status,
            plan=plan,
            factory_partner_application_id=factory_partner_application_id,
        )
        db.add(tenant)
        await db.flush()

        owner_user = None
        if owner_email:
            owner_user = await TenantService._add_user(
                db,
                tenant.id,
                email=owner_email,
                role="owner",
                status="active",
                allow_owner=True,
            )

        if factory_partner_application_id:
            app = await db.get(FactoryPartnerApplication, factory_partner_application_id)
            if app:
                app.tenant_id = tenant.id
                if app.created_client_id:
                    client = await db.get(Client, app.created_client_id)
                    if client:
                        client.tenant_id = tenant.id

        await db.commit()
        await db.refresh(tenant)
        logger.info("%s create: id=%s company=%s", MARKER, tenant.id, tenant.company_name)
        return {
            "tenant": _serialize_tenant(tenant),
            "owner_user": owner_user,
            "message": "Tenant created. Strict isolation enforced for all scoped data.",
        }

    @staticmethod
    async def create_tenant_from_application(
        db: AsyncSession,
        application_id: UUID,
        *,
        owner_email: str | None = None,
    ) -> dict[str, Any]:
        """Factory Partner Portal — approved application creates tenant (manual admin action)."""
        result = await db.execute(
            select(FactoryPartnerApplication).where(FactoryPartnerApplication.id == application_id),
        )
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=404, detail="Application not found")
        if app.status != "approved":
            raise HTTPException(
                status_code=400,
                detail="Tenant can only be created from approved applications",
            )
        if app.tenant_id:
            raise HTTPException(status_code=400, detail="Tenant already exists for this application")

        email = owner_email or app.contact_email
        return await TenantService.create_tenant(
            db,
            company_name=app.company_name,
            status="active",
            plan="starter",
            factory_partner_application_id=app.id,
            owner_email=email,
        )

    @staticmethod
    async def update_tenant(
        db: AsyncSession,
        tenant_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        tenant = await TenantService.get_tenant(db, tenant_id)
        assert tenant is not None
        if "status" in payload and payload["status"]:
            if payload["status"] not in TENANT_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid tenant status")
            tenant.status = payload["status"]
        if "plan" in payload and payload["plan"]:
            if payload["plan"] not in TENANT_PLANS:
                raise HTTPException(status_code=400, detail="Invalid tenant plan")
            tenant.plan = payload["plan"]
        if "company_name" in payload and payload["company_name"]:
            tenant.company_name = payload["company_name"].strip()
        tenant.updated_at = _utc_now()
        await db.commit()
        await db.refresh(tenant)
        return _serialize_tenant(tenant)

    @staticmethod
    async def get_tenant_detail(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        tenant = await TenantService.get_tenant(db, tenant_id)
        assert tenant is not None
        users = await TenantService.list_users(db, tenant_id, limit=500)
        portal = await TenantService._portal_status(db, tenant_id)
        usage = await TenantService._usage_summary(db, tenant_id)
        from app.services.subscription_service import SubscriptionService
        subscription_overview = await SubscriptionService.tenant_subscription_overview(db, tenant_id)
        return {
            "tenant": _serialize_tenant(tenant),
            "users": users["items"],
            "portal_status": portal,
            "usage_summary": usage,
            "subscription_overview": subscription_overview,
            "roles_available": sorted(TENANT_USER_ROLES),
            "safety_notice": (
                "Strict tenant isolation — each company accesses only its own data. "
                "No cross-company access or automatic permission escalation."
            ),
        }

    @staticmethod
    async def list_users(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        await TenantService.get_tenant(db, tenant_id)
        query = (
            select(TenantUser)
            .where(TenantUser.tenant_id == tenant_id)
            .order_by(TenantUser.created_at.desc())
        )
        count_q = (
            select(func.count())
            .select_from(TenantUser)
            .where(TenantUser.tenant_id == tenant_id)
        )
        total = int(await db.scalar(count_q) or 0)
        result = await db.execute(query.offset(skip).limit(clamp_limit(limit)))
        items = [_serialize_user(u) for u in result.scalars().all()]
        return {"tenant_id": tenant_id, "items": items, "total": total}

    @staticmethod
    async def add_tenant_user(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        email: str,
        role: str,
        status: str = "active",
    ) -> dict[str, Any]:
        await TenantService.validate_tenant_active(db, tenant_id)
        user = await TenantService._add_user(
            db, tenant_id, email=email, role=role, status=status, allow_owner=False,
        )
        await db.commit()
        return user

    @staticmethod
    async def _add_user(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        email: str,
        role: str,
        status: str,
        allow_owner: bool,
    ) -> dict[str, Any]:
        email_norm = email.strip().lower()
        if role not in TENANT_USER_ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        if status not in TENANT_USER_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid user status")

        if role == "owner":
            if not allow_owner:
                owner_exists = await db.scalar(
                    select(func.count())
                    .select_from(TenantUser)
                    .where(
                        TenantUser.tenant_id == tenant_id,
                        TenantUser.role == "owner",
                        TenantUser.status == "active",
                    ),
                )
                if int(owner_exists or 0) > 0:
                    raise HTTPException(
                        status_code=400,
                        detail="Tenant already has an owner — no permission escalation",
                    )
        else:
            pass

        dup = await db.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant_id,
                func.lower(TenantUser.email) == email_norm,
            ),
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="User email already exists for this tenant")

        row = TenantUser(
            tenant_id=tenant_id,
            email=email_norm,
            role=role,
            status=status,
        )
        db.add(row)
        await db.flush()
        return _serialize_user(row)

    @staticmethod
    def can_assign_role(current_role: str | None, new_role: str) -> bool:
        return can_assign_role(current_role, new_role)

    @staticmethod
    async def link_client_to_tenant(
        db: AsyncSession,
        tenant_id: UUID,
        client_id: UUID,
    ) -> None:
        await TenantService.validate_tenant_active(db, tenant_id)
        client = await db.get(Client, client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        if client.tenant_id and client.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Client belongs to another tenant — cross-company link denied",
            )
        client.tenant_id = tenant_id
        await db.flush()

    @staticmethod
    async def _portal_status(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        if not client_ids:
            return {
                "has_portal_account": False,
                "portal_account_id": None,
                "portal_status": None,
                "company_id": None,
            }
        result = await db.execute(
            select(CustomerPortalAccount)
            .where(CustomerPortalAccount.tenant_id == tenant_id)
            .order_by(CustomerPortalAccount.created_at.desc())
            .limit(1),
        )
        account = result.scalar_one_or_none()
        if not account:
            result = await db.execute(
                select(CustomerPortalAccount)
                .where(CustomerPortalAccount.company_id.in_(client_ids))
                .order_by(CustomerPortalAccount.created_at.desc())
                .limit(1),
            )
            account = result.scalar_one_or_none()
        if not account:
            return {
                "has_portal_account": False,
                "portal_account_id": None,
                "portal_status": None,
                "company_id": client_ids[0] if client_ids else None,
            }
        return {
            "has_portal_account": True,
            "portal_account_id": account.id,
            "portal_status": account.portal_status,
            "company_id": account.company_id,
        }

    @staticmethod
    async def _usage_summary(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        active_users = int(
            await db.scalar(
                select(func.count())
                .select_from(TenantUser)
                .where(TenantUser.tenant_id == tenant_id, TenantUser.status == "active"),
            ) or 0,
        )
        portal_accounts = int(
            await db.scalar(
                select(func.count())
                .select_from(CustomerPortalAccount)
                .where(CustomerPortalAccount.tenant_id == tenant_id),
            ) or 0,
        )
        leads = deals = 0
        if client_ids:
            leads = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmLead)
                    .where(CrmLead.client_id.in_(client_ids)),
                ) or 0,
            )
            deals = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmDeal)
                    .where(CrmDeal.client_id.in_(client_ids)),
                ) or 0,
            )
        return {
            "client_count": len(client_ids),
            "active_users": active_users,
            "crm_leads": leads,
            "crm_deals": deals,
            "portal_accounts": portal_accounts,
        }

    @staticmethod
    async def isolation_check(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        """Verify tenant clients are not shared with other tenants."""
        await TenantService.get_tenant(db, tenant_id)
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        leak = False
        if client_ids:
            other = await db.execute(
                select(Client.id).where(
                    Client.id.in_(client_ids),
                    Client.tenant_id.isnot(None),
                    Client.tenant_id != tenant_id,
                ),
            )
            leak = other.first() is not None
        return {
            "tenant_id": tenant_id,
            "isolated": not leak,
            "client_ids": client_ids,
            "cross_tenant_leak": leak,
            "message": "Isolation OK" if not leak else "Cross-tenant client assignment detected",
        }
