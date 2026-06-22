"""Admin client account provisioning — tenant, owner user, and demo workspace."""
from __future__ import annotations

import logging
import secrets
import string
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.models.tenant import TENANT_PLANS, Tenant
from app.schemas.client import BUSINESS_CATEGORIES
from app.services.admin_rbac_service import AdminRbacService, CurrentAdminUser
from app.services.auth_service import hash_password
from app.services.tenant_auth_service import TenantAuthService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)
MARKER = "[AdminClientProvision]"

LOCALE_TO_SOURCE = {"en": "en", "zh": "zh", "ru": "ru", "ko": "ko", "ja": "ja"}


def _generate_temporary_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _map_business_category(industry: str | None) -> str:
    if not industry:
        return "other"
    key = industry.strip().lower().replace(" ", "_")
    if key in BUSINESS_CATEGORIES:
        return key
    return "other"


def _build_client_notes(
    *,
    owner_name: str | None,
    wechat: str | None,
    whatsapp: str | None,
    country: str | None,
) -> str | None:
    lines: list[str] = [f"{MARKER} Admin-provisioned client account"]
    if owner_name:
        lines.append(f"Owner: {owner_name.strip()}")
    if wechat:
        lines.append(f"WeChat: {wechat.strip()}")
    if whatsapp:
        lines.append(f"WhatsApp: {whatsapp.strip()}")
    if country:
        lines.append(f"Country: {country.strip()}")
    return "\n".join(lines) if len(lines) > 1 else lines[0]


def _login_url() -> str:
    base = settings.cors_origins_list[0] if settings.cors_origins_list else "http://localhost:3000"
    return f"{base.rstrip('/')}/login"


class AdminClientProvisioningService:
    @staticmethod
    async def create_client_account(
        db: AsyncSession,
        admin: CurrentAdminUser,
        *,
        company_name: str,
        owner_email: str,
        owner_name: str | None = None,
        phone: str | None = None,
        wechat: str | None = None,
        whatsapp: str | None = None,
        country: str | None = None,
        industry: str | None = None,
        plan: str = "starter",
        locale: str = "en",
    ) -> dict[str, Any]:
        AdminRbacService.assert_permission(admin, "tenants.manage")

        company = company_name.strip()
        email_norm = owner_email.strip().lower()
        if not company:
            raise HTTPException(status_code=400, detail="company_name is required")
        if not email_norm:
            raise HTTPException(status_code=400, detail="owner_email is required")
        if plan not in TENANT_PLANS:
            raise HTTPException(status_code=400, detail="Invalid plan")
        source_language = LOCALE_TO_SOURCE.get(locale.strip().lower(), "en")

        dup_company = await db.execute(
            select(Tenant.id).where(func.lower(Tenant.company_name) == company.lower()),
        )
        if dup_company.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="A tenant with this company name already exists")

        existing_user = await TenantAuthService.load_user_by_email(db, email_norm)
        if existing_user:
            raise HTTPException(status_code=400, detail="Owner email is already registered")

        temp_password = _generate_temporary_password()

        result = await TenantService.create_tenant(
            db,
            company_name=company,
            status="active",
            plan=plan,
            owner_email=email_norm,
        )
        owner = result.get("owner_user")
        if not owner:
            raise HTTPException(status_code=500, detail="Failed to create owner user")

        user = await TenantAuthService.load_user_by_id(db, owner["id"])
        if not user:
            raise HTTPException(status_code=500, detail="Owner user record missing")
        user.password_hash = hash_password(temp_password)
        user.status = "active"
        await db.commit()

        tenant_id = UUID(str(result["tenant"]["id"]))
        client = Client(
            company_name=company,
            tenant_id=tenant_id,
            source_language=source_language,
            business_category=_map_business_category(industry),
            content_style="professional",
            status="active",
            brand_name=company,
            cta_phone=phone.strip() if phone else None,
            notes=_build_client_notes(
                owner_name=owner_name,
                wechat=wechat,
                whatsapp=whatsapp,
                country=country,
            ),
            target_audience=country.strip() if country else None,
        )
        db.add(client)
        await db.commit()

        from app.services.demo_tenant_seed_service import ensure_demo_tenant_data

        seed_counts = await ensure_demo_tenant_data(db, tenant_id)

        await AdminRbacService.record_audit(
            db,
            admin_user_id=admin.id,
            event_type="tenant_provisioning",
            action="create_client_account",
            resource_type="tenant",
            resource_id=str(tenant_id),
            details=f"company={company} owner={email_norm}",
        )

        logger.info(
            "%s created tenant=%s owner=%s seed=%s",
            MARKER,
            tenant_id,
            email_norm,
            seed_counts,
        )

        return {
            "tenant_id": str(tenant_id),
            "user_id": str(user.id),
            "client_id": str(client.id),
            "company_name": company,
            "login_email": email_norm,
            "temporary_password": temp_password,
            "login_url": _login_url(),
            "seed_counts": seed_counts,
            "message": "Client account created. Share login details securely — password is shown once.",
        }
