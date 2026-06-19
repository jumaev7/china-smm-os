"""Pilot Client Onboarding v1 — guided admin workflow (read-only aggregation)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer_portal_account import CustomerPortalAccount
from app.models.factory_partner_application import FactoryPartnerApplication
from app.models.factory_platform_profile import FactoryPlatformProfile
from app.models.factory_profile import FactoryCatalogProduct
from app.models.subscription import Subscription
from app.models.tenant import TenantUser
from app.services.factory_partner_portal_service import FactoryPartnerPortalService
from app.services.factory_profile_service import FactoryProfileService
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

MARKER = "[Pilot Onboarding]"

CHECKLIST_STEPS: tuple[tuple[str, str], ...] = (
    ("application_submitted", "Application submitted"),
    ("application_approved", "Application approved"),
    ("client_created", "CRM client created"),
    ("tenant_created", "Tenant created"),
    ("portal_account_created", "Portal account created"),
    ("subscription_created", "Subscription created"),
    ("admin_user_created", "Admin user created"),
    ("factory_profile_completed", "Factory profile completed"),
    ("product_catalog_added", "Product catalog added"),
    ("billing_ready", "Billing ready"),
    ("pilot_ready", "Pilot ready"),
)

TOTAL_STEPS = len(CHECKLIST_STEPS)

_ACTION_ORDER: tuple[tuple[str, str, str], ...] = (
    ("approve_application", "Approve application", "Review and approve the factory partner application."),
    ("create_client", "Create client", "Create CRM client profile from approved application."),
    ("create_tenant", "Create tenant", "Provision isolated SaaS tenant for the factory."),
    ("create_portal_account", "Create portal account", "Enable customer portal access for the factory."),
    ("create_subscription", "Create subscription", "Assign billing plan — manual action on Billing page."),
    ("create_admin_user", "Create admin user", "Add tenant owner or manager user account."),
    ("open_factory_profile", "Open factory profile", "Complete company profile and catalog in Factory Platform."),
    ("open_billing", "Open billing", "Review subscription status and billing readiness."),
)

_PROFILE_MIN_SCORE = 50


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


class PilotOnboardingService:
    @staticmethod
    def _safety_notice() -> str:
        return (
            "Guided onboarding only — no automatic approval, tenant creation, "
            "subscription creation, or user creation."
        )

    @staticmethod
    async def _load_application(db: AsyncSession, application_id: UUID) -> FactoryPartnerApplication:
        app = await db.get(FactoryPartnerApplication, application_id)
        if not app:
            raise HTTPException(status_code=404, detail="Application not found")
        return app

    @staticmethod
    async def _portal_account(
        db: AsyncSession,
        app: FactoryPartnerApplication,
    ) -> CustomerPortalAccount | None:
        if app.created_client_id:
            result = await db.execute(
                select(CustomerPortalAccount)
                .where(CustomerPortalAccount.company_id == app.created_client_id)
                .order_by(CustomerPortalAccount.created_at.desc())
                .limit(1),
            )
            row = result.scalar_one_or_none()
            if row:
                return row
        result = await db.execute(
            select(CustomerPortalAccount)
            .where(CustomerPortalAccount.factory_partner_application_id == app.id)
            .order_by(CustomerPortalAccount.created_at.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _owner_user(db: AsyncSession, tenant_id: UUID | None) -> TenantUser | None:
        if not tenant_id:
            return None
        result = await db.execute(
            select(TenantUser)
            .where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.role == "owner",
                TenantUser.status == "active",
            )
            .limit(1),
        )
        owner = result.scalar_one_or_none()
        if owner:
            return owner
        result = await db.execute(
            select(TenantUser)
            .where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.status == "active",
            )
            .order_by(TenantUser.created_at.asc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _active_subscription(
        db: AsyncSession,
        tenant_id: UUID | None,
    ) -> Subscription | None:
        if not tenant_id:
            return None
        sub, _plan = await SubscriptionService._active_subscription(db, tenant_id)
        if sub:
            return sub
        result = await db.execute(
            select(Subscription)
            .where(Subscription.tenant_id == tenant_id)
            .order_by(Subscription.created_at.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _factory_profile(
        db: AsyncSession,
        tenant_id: UUID | None,
    ) -> FactoryPlatformProfile | None:
        if not tenant_id:
            return None
        result = await db.execute(
            select(FactoryPlatformProfile).where(FactoryPlatformProfile.tenant_id == tenant_id),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _product_count(db: AsyncSession, tenant_id: UUID | None) -> int:
        if not tenant_id:
            return 0
        return int(
            await db.scalar(
                select(func.count())
                .select_from(FactoryCatalogProduct)
                .where(FactoryCatalogProduct.tenant_id == tenant_id),
            ) or 0,
        )

    @staticmethod
    def _route_hint(action: str, app: FactoryPartnerApplication) -> str:
        tenant_q = f"?tenant_id={app.tenant_id}" if app.tenant_id else ""
        routes = {
            "approve_application": f"/factory-partners?application={app.id}",
            "create_client": f"/factory-partners?application={app.id}",
            "create_tenant": f"/factory-partners?application={app.id}",
            "create_portal_account": f"/factory-partners?application={app.id}",
            "create_subscription": f"/billing{tenant_q}",
            "create_admin_user": f"/tenant-users{tenant_q}",
            "open_factory_profile": f"/factory-platform{tenant_q}",
            "open_billing": f"/billing{tenant_q}",
        }
        return routes.get(action, "/pilot-onboarding")

    @staticmethod
    async def _evaluate(
        db: AsyncSession,
        app: FactoryPartnerApplication,
    ) -> dict[str, Any]:
        portal = await PilotOnboardingService._portal_account(db, app)
        subscription = await PilotOnboardingService._active_subscription(db, app.tenant_id)
        owner = await PilotOnboardingService._owner_user(db, app.tenant_id)
        profile = await PilotOnboardingService._factory_profile(db, app.tenant_id)
        product_count = await PilotOnboardingService._product_count(db, app.tenant_id)

        profile_score = 0
        profile_complete = False
        if profile and app.tenant_id:
            try:
                score_data = await FactoryProfileService.profile_score(db, app.tenant_id)
                profile_score = int(score_data.get("profile_score") or 0)
                profile_complete = profile_score >= _PROFILE_MIN_SCORE
            except Exception as exc:
                logger.info("%s profile score skip app=%s err=%s", MARKER, app.id, exc)
                profile_complete = bool(
                    profile.company_name
                    and (profile.company_description or profile.contact_email),
                )

        submitted = app.status != "draft" or app.submitted_at is not None
        approved = app.status == "approved"
        client_created = app.created_client_id is not None
        tenant_created = app.tenant_id is not None
        portal_created = portal is not None
        subscription_created = subscription is not None
        admin_created = owner is not None
        catalog_added = product_count > 0
        billing_ready = subscription is not None and subscription.status in {"trial", "active"}

        step_values = {
            "application_submitted": submitted,
            "application_approved": approved,
            "client_created": client_created,
            "tenant_created": tenant_created,
            "portal_account_created": portal_created,
            "subscription_created": subscription_created,
            "admin_user_created": admin_created,
            "factory_profile_completed": profile_complete,
            "product_catalog_added": catalog_added,
            "billing_ready": billing_ready,
        }
        pre_pilot_complete = all(step_values.values())
        step_values["pilot_ready"] = pre_pilot_complete

        completed_count = sum(1 for v in step_values.values() if v)
        readiness_score = _clamp(int(round(completed_count / TOTAL_STEPS * 100)))

        checklist: list[dict[str, Any]] = []
        for step, label in CHECKLIST_STEPS:
            completed = step_values[step]
            details = None
            completed_at = None
            if step == "application_submitted" and app.submitted_at:
                completed_at = app.submitted_at
            elif step == "application_approved" and app.reviewed_at:
                completed_at = app.reviewed_at
            elif step == "factory_profile_completed" and profile:
                details = f"Profile score {profile_score}"
            elif step == "product_catalog_added" and product_count:
                details = f"{product_count} catalog item(s)"
            elif step == "billing_ready" and subscription:
                details = f"Status: {subscription.status}"
            checklist.append({
                "step": step,
                "label": label,
                "completed": completed,
                "completed_at": completed_at,
                "details": details,
            })

        blockers: list[dict[str, Any]] = []
        if app.status == "rejected":
            blockers.append({
                "blocker": "application_rejected",
                "label": "Application rejected",
                "severity": "critical",
                "message": "Application was rejected — reopen review in Factory Partners admin.",
            })
        elif not approved and app.status in {"submitted", "under_review", "draft"}:
            blockers.append({
                "blocker": "application_not_approved",
                "label": "Application not approved",
                "severity": "critical",
                "message": "Approve the factory application before provisioning tenant resources.",
            })
        if approved and not tenant_created:
            blockers.append({
                "blocker": "tenant",
                "label": "Missing tenant",
                "severity": "critical",
                "message": "Create tenant manually from approved application.",
            })
        if tenant_created and not subscription_created:
            blockers.append({
                "blocker": "subscription",
                "label": "Missing subscription",
                "severity": "critical",
                "message": "Create subscription on Billing page — no automatic billing setup.",
            })
        if client_created and not portal_created:
            blockers.append({
                "blocker": "portal_account",
                "label": "Missing portal account",
                "severity": "warning",
                "message": "Create customer portal account for factory partner access.",
            })
        if tenant_created and not admin_created:
            blockers.append({
                "blocker": "admin_user",
                "label": "Missing admin user",
                "severity": "critical",
                "message": "Add tenant owner user before pilot launch.",
            })
        if tenant_created and not profile_complete:
            blockers.append({
                "blocker": "company_profile",
                "label": "Incomplete company profile",
                "severity": "warning",
                "message": f"Factory profile score {profile_score} — complete profile in Factory Platform.",
            })
        if tenant_created and not catalog_added:
            blockers.append({
                "blocker": "products",
                "label": "Missing product catalog",
                "severity": "warning",
                "message": "Add at least one product to the factory catalog.",
            })
        if subscription_created and not billing_ready:
            blockers.append({
                "blocker": "billing",
                "label": "Billing not ready",
                "severity": "critical",
                "message": f"Subscription status is {subscription.status if subscription else 'missing'} — activate or assign plan.",
            })

        if app.status == "rejected":
            onboarding_status = "blocked"
        elif app.status == "draft" and not submitted:
            onboarding_status = "not_started"
        elif step_values["pilot_ready"]:
            onboarding_status = "completed"
        elif readiness_score >= 90 and not blockers:
            onboarding_status = "ready"
        elif blockers:
            onboarding_status = "blocked"
        else:
            onboarding_status = "in_progress"

        actions: list[dict[str, Any]] = []
        availability = {
            "approve_application": app.status in {"submitted", "under_review"},
            "create_client": approved and not client_created,
            "create_tenant": approved and not tenant_created,
            "create_portal_account": approved and client_created and not portal_created,
            "create_subscription": tenant_created and not subscription_created,
            "create_admin_user": tenant_created and not admin_created,
            "open_factory_profile": tenant_created,
            "open_billing": tenant_created,
        }
        for action, label, description in _ACTION_ORDER:
            actions.append({
                "action": action,
                "label": label,
                "description": description,
                "available": availability.get(action, False),
                "route_hint": PilotOnboardingService._route_hint(action, app),
                "manual_only": True,
            })

        next_best = next((a for a in actions if a["available"]), None)

        return {
            "application_id": app.id,
            "company": app.company_name,
            "application_status": app.status,
            "status": onboarding_status,
            "readiness_score": readiness_score,
            "blockers": blockers,
            "next_best_action": next_best,
            "checklist": checklist,
            "available_actions": actions,
            "tenant_id": app.tenant_id,
            "client_id": app.created_client_id,
            "country": app.country,
            "industry": app.industry,
            "submitted_at": app.submitted_at,
            "reviewed_at": app.reviewed_at,
            "updated_at": app.updated_at,
            "completed_count": completed_count,
        }

    @staticmethod
    async def integration_checks(db: AsyncSession) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        async def _probe(module: str, coro: Any, message: str) -> None:
            try:
                await coro
                checks.append({"module": module, "status": "ok", "message": message, "details": {}})
            except Exception as exc:
                checks.append({
                    "module": module,
                    "status": "degraded",
                    "message": str(exc)[:200],
                    "details": {},
                })

        await _probe(
            "factory_partner_portal",
            FactoryPartnerPortalService.summary_widget(db),
            "Factory Partner applications reachable",
        )
        await _probe(
            "pilot_onboarding",
            PilotOnboardingService._list_application_rows(db, limit=1),
            "Pilot onboarding applications reachable",
        )
        return checks

    @staticmethod
    async def _list_application_rows(
        db: AsyncSession,
        *,
        status: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[FactoryPartnerApplication], int]:
        query = select(FactoryPartnerApplication).order_by(
            FactoryPartnerApplication.updated_at.desc(),
        )
        count_q = select(func.count()).select_from(FactoryPartnerApplication)

        if status:
            query = query.where(FactoryPartnerApplication.status == status)
            count_q = count_q.where(FactoryPartnerApplication.status == status)

        if search:
            pattern = f"%{search.strip()}%"
            filt = FactoryPartnerApplication.company_name.ilike(pattern)
            query = query.where(filt)
            count_q = count_q.where(filt)

        total = int(await db.scalar(count_q) or 0)
        result = await db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        apps, total = await PilotOnboardingService._list_application_rows(db, limit=500)
        counts = {
            "not_started": 0,
            "in_progress": 0,
            "blocked": 0,
            "ready": 0,
            "completed": 0,
        }
        scores: list[int] = []
        pilot_ready = 0
        pending_approval = 0

        for app in apps:
            ev = await PilotOnboardingService._evaluate(db, app)
            counts[ev["status"]] = counts.get(ev["status"], 0) + 1
            scores.append(ev["readiness_score"])
            if ev["checklist"][-1]["completed"]:
                pilot_ready += 1
            if app.status in {"submitted", "under_review"}:
                pending_approval += 1

        avg = _clamp(int(round(sum(scores) / len(scores)))) if scores else 0

        return {
            "total_applications": total,
            **counts,
            "average_readiness_score": avg,
            "pilot_ready_count": pilot_ready,
            "pending_approval": pending_approval,
            "integration_checks": await PilotOnboardingService.integration_checks(db),
            "safety_notice": PilotOnboardingService._safety_notice(),
        }

    @staticmethod
    async def list_applications(
        db: AsyncSession,
        *,
        status: str | None = None,
        search: str | None = None,
        onboarding_status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        apps, total = await PilotOnboardingService._list_application_rows(
            db, status=status, search=search, skip=0, limit=500,
        )
        items: list[dict[str, Any]] = []
        for app in apps:
            ev = await PilotOnboardingService._evaluate(db, app)
            summary = {
                "application_id": ev["application_id"],
                "company": ev["company"],
                "status": ev["status"],
                "application_status": ev["application_status"],
                "readiness_score": ev["readiness_score"],
                "blockers": ev["blockers"],
                "next_best_action": ev["next_best_action"],
                "tenant_id": ev["tenant_id"],
                "client_id": ev["client_id"],
                "updated_at": ev["updated_at"],
            }
            if onboarding_status and ev["status"] != onboarding_status:
                continue
            items.append(summary)

        page = items[skip : skip + limit]
        return {"items": page, "total": len(items) if onboarding_status else total}

    @staticmethod
    async def get_application(db: AsyncSession, application_id: UUID) -> dict[str, Any]:
        app = await PilotOnboardingService._load_application(db, application_id)
        return await PilotOnboardingService._evaluate(db, app)

    @staticmethod
    async def checklist(db: AsyncSession, application_id: UUID) -> dict[str, Any]:
        ev = await PilotOnboardingService.get_application(db, application_id)
        return {
            "application_id": ev["application_id"],
            "company": ev["company"],
            "readiness_score": ev["readiness_score"],
            "checklist": ev["checklist"],
            "completed_count": ev["completed_count"],
            "total_steps": TOTAL_STEPS,
        }

    @staticmethod
    async def blockers(db: AsyncSession, application_id: UUID) -> dict[str, Any]:
        ev = await PilotOnboardingService.get_application(db, application_id)
        blockers = ev["blockers"]
        return {
            "application_id": ev["application_id"],
            "company": ev["company"],
            "blockers": blockers,
            "blocker_count": len(blockers),
        }

    @staticmethod
    async def actions(db: AsyncSession, application_id: UUID) -> dict[str, Any]:
        ev = await PilotOnboardingService.get_application(db, application_id)
        return {
            "application_id": ev["application_id"],
            "company": ev["company"],
            "actions": ev["available_actions"],
            "next_best_action": ev["next_best_action"],
        }

    @staticmethod
    async def refresh(db: AsyncSession, application_id: UUID) -> dict[str, Any]:
        ev = await PilotOnboardingService.get_application(db, application_id)
        return {
            "application_id": ev["application_id"],
            "company": ev["company"],
            "status": ev["status"],
            "readiness_score": ev["readiness_score"],
            "blockers": ev["blockers"],
            "next_best_action": ev["next_best_action"],
            "refreshed_at": _utc_now(),
            "message": "Onboarding state refreshed — manual admin actions only.",
        }

    @staticmethod
    async def summary_widget(db: AsyncSession) -> dict[str, Any]:
        overview = await PilotOnboardingService.overview(db)
        apps, _ = await PilotOnboardingService._list_application_rows(
            db, limit=1,
        )
        latest_name = apps[0].company_name if apps else None
        if not latest_name:
            pending = await db.execute(
                select(FactoryPartnerApplication.company_name)
                .where(FactoryPartnerApplication.status.in_(("submitted", "under_review")))
                .order_by(FactoryPartnerApplication.submitted_at.desc().nullslast())
                .limit(1),
            )
            latest_name = pending.scalar_one_or_none()

        return {
            "total_tracked": overview["total_applications"],
            "in_progress": overview["in_progress"],
            "blocked": overview["blocked"],
            "pilot_ready": overview["pilot_ready_count"],
            "average_readiness_score": overview["average_readiness_score"],
            "pending_approval": overview["pending_approval"],
            "latest_company_name": latest_name,
            "safety_notice": PilotOnboardingService._safety_notice(),
        }

    @staticmethod
    async def executive_overview(db: AsyncSession, *, limit: int = 8) -> dict[str, Any]:
        overview = await PilotOnboardingService.overview(db)
        apps, _ = await PilotOnboardingService._list_application_rows(db, limit=100)
        tracked: list[dict[str, Any]] = []
        for app in apps:
            ev = await PilotOnboardingService._evaluate(db, app)
            if ev["status"] in {"in_progress", "blocked", "ready"}:
                tracked.append({
                    "application_id": str(ev["application_id"]),
                    "company": ev["company"],
                    "status": ev["status"],
                    "readiness_score": ev["readiness_score"],
                    "blocker_count": len(ev["blockers"]),
                    "next_action": (ev["next_best_action"] or {}).get("action"),
                })
        tracked.sort(key=lambda x: (-x["readiness_score"], x["company"]))
        return {
            **overview,
            "launch_candidates": tracked[:limit],
            "safety_notice": PilotOnboardingService._safety_notice(),
        }

    @staticmethod
    async def _application_for_tenant(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> FactoryPartnerApplication | None:
        result = await db.execute(
            select(FactoryPartnerApplication)
            .where(FactoryPartnerApplication.tenant_id == tenant_id)
            .limit(1),
        )
        app = result.scalar_one_or_none()
        if app:
            return app
        from app.models.tenant import Tenant

        tenant = await db.get(Tenant, tenant_id)
        if tenant and tenant.factory_partner_application_id:
            return await db.get(FactoryPartnerApplication, tenant.factory_partner_application_id)
        profile = await PilotOnboardingService._factory_profile(db, tenant_id)
        if profile:
            result = await db.execute(
                select(FactoryPartnerApplication)
                .where(FactoryPartnerApplication.created_client_id == profile.company_id)
                .limit(1),
            )
            return result.scalar_one_or_none()
        return None

    @staticmethod
    async def tenant_onboarding_status(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> dict[str, Any] | None:
        app = await PilotOnboardingService._application_for_tenant(db, tenant_id)
        if not app:
            return None
        ev = await PilotOnboardingService._evaluate(db, app)
        return {
            "application_id": ev["application_id"],
            "company": ev["company"],
            "status": ev["status"],
            "readiness_score": ev["readiness_score"],
            "blocker_count": len(ev["blockers"]),
            "pilot_ready": ev["checklist"][-1]["completed"],
        }

    @staticmethod
    async def billing_readiness_for_tenant(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        subscription = await PilotOnboardingService._active_subscription(db, tenant_id)
        onboarding = await PilotOnboardingService.tenant_onboarding_status(db, tenant_id)
        billing_ready = subscription is not None and subscription.status in {"trial", "active"}
        return {
            "tenant_id": tenant_id,
            "billing_ready": billing_ready,
            "subscription_status": subscription.status if subscription else None,
            "pilot_onboarding_status": (onboarding or {}).get("status"),
            "readiness_score": (onboarding or {}).get("readiness_score"),
            "pilot_ready": (onboarding or {}).get("pilot_ready", False),
        }
