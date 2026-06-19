"""Factory Partner Portal v1 — self-service onboarding (manual review only)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.factory_partner_application import (
    APPLICATION_STATUSES,
    FactoryPartnerApplication,
)
from app.schemas.client import BUSINESS_CATEGORIES, ClientCreate
from app.schemas.factory_partner_portal import (
    COMMISSION_MODELS,
    FactoryPartnerApplyRequest,
    FactoryPartnerApplicationUpdate,
)
from app.services.client_service import ClientService

logger = logging.getLogger(__name__)

MARKER = "[Factory Partner Portal]"

_PENDING_STATUSES = frozenset({"submitted", "under_review"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(app: FactoryPartnerApplication) -> dict[str, Any]:
    return {
        "id": app.id,
        "company_name": app.company_name,
        "country": app.country,
        "city": app.city,
        "contact_name": app.contact_name,
        "contact_phone": app.contact_phone,
        "contact_wechat": app.contact_wechat,
        "contact_whatsapp": app.contact_whatsapp,
        "contact_email": app.contact_email,
        "website": app.website,
        "industry": app.industry,
        "product_categories": list(app.product_categories or []),
        "company_description": app.company_description,
        "cooperation_terms_accepted": bool(app.cooperation_terms_accepted),
        "commission_model": app.commission_model,
        "target_markets": list(app.target_markets or []),
        "documents": list(app.documents or []),
        "status": app.status,
        "submitted_at": app.submitted_at,
        "reviewed_at": app.reviewed_at,
        "created_client_id": app.created_client_id,
        "tenant_id": app.tenant_id,
        "created_at": app.created_at,
        "updated_at": app.updated_at,
    }


def _map_business_category(industry: str | None) -> str:
    if not industry:
        return "other"
    key = industry.strip().lower().replace(" ", "_")
    if key in BUSINESS_CATEGORIES:
        return key
    return "other"


def _contact_notes(app: FactoryPartnerApplication) -> str:
    lines = [
        f"{MARKER} Application {app.id}",
        f"Status: {app.status}",
    ]
    if app.contact_name:
        lines.append(f"Contact: {app.contact_name}")
    if app.contact_email:
        lines.append(f"Email: {app.contact_email}")
    if app.contact_phone:
        lines.append(f"Phone: {app.contact_phone}")
    if app.contact_wechat:
        lines.append(f"WeChat: {app.contact_wechat}")
    if app.contact_whatsapp:
        lines.append(f"WhatsApp: {app.contact_whatsapp}")
    if app.country or app.city:
        lines.append(f"Location: {app.city or ''} {app.country or ''}".strip())
    if app.commission_model:
        lines.append(f"Commission model: {app.commission_model}")
    if app.target_markets:
        lines.append(f"Target markets: {', '.join(app.target_markets)}")
    return "\n".join(lines)


class FactoryPartnerPortalService:
    @staticmethod
    async def _load(db: AsyncSession, application_id: UUID) -> FactoryPartnerApplication:
        result = await db.execute(
            select(FactoryPartnerApplication).where(FactoryPartnerApplication.id == application_id),
        )
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=404, detail="Application not found")
        return app

    @staticmethod
    async def list_applications(
        db: AsyncSession,
        *,
        status: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        query = select(FactoryPartnerApplication).order_by(
            FactoryPartnerApplication.updated_at.desc(),
        )
        count_q = select(func.count()).select_from(FactoryPartnerApplication)

        if status:
            if status not in APPLICATION_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid status")
            query = query.where(FactoryPartnerApplication.status == status)
            count_q = count_q.where(FactoryPartnerApplication.status == status)

        if search:
            pattern = f"%{search.strip()}%"
            filt = FactoryPartnerApplication.company_name.ilike(pattern)
            query = query.where(filt)
            count_q = count_q.where(filt)

        total = int(await db.scalar(count_q) or 0)
        result = await db.execute(query.offset(skip).limit(limit))
        items = [_serialize(a) for a in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def get_application(db: AsyncSession, application_id: UUID) -> dict[str, Any]:
        app = await FactoryPartnerPortalService._load(db, application_id)
        return _serialize(app)

    @staticmethod
    async def apply(db: AsyncSession, data: FactoryPartnerApplyRequest) -> dict[str, Any]:
        if data.commission_model and data.commission_model not in COMMISSION_MODELS:
            raise HTTPException(status_code=400, detail="Invalid commission model")

        app = FactoryPartnerApplication(
            company_name=data.company_name.strip(),
            country=data.country,
            city=data.city,
            contact_name=data.contact_name,
            contact_phone=data.contact_phone,
            contact_wechat=data.contact_wechat,
            contact_whatsapp=data.contact_whatsapp,
            contact_email=data.contact_email,
            website=data.website,
            industry=data.industry,
            product_categories=data.product_categories or [],
            company_description=data.company_description,
            cooperation_terms_accepted=data.cooperation_terms_accepted,
            commission_model=data.commission_model,
            target_markets=data.target_markets or [],
            documents=[d.model_dump() for d in data.documents],
            status="draft",
        )
        db.add(app)
        await db.commit()
        await db.refresh(app)
        logger.info("%s apply: id=%s company=%s", MARKER, app.id, app.company_name)
        return _serialize(app)

    @staticmethod
    async def update_application(
        db: AsyncSession,
        application_id: UUID,
        data: FactoryPartnerApplicationUpdate,
    ) -> dict[str, Any]:
        app = await FactoryPartnerPortalService._load(db, application_id)
        payload = data.model_dump(exclude_unset=True)

        if "status" in payload:
            new_status = payload.pop("status")
            if new_status not in APPLICATION_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid status")
            if app.status in ("approved", "rejected") and new_status != app.status:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot change status of finalized application",
                )
            if new_status == "under_review" and app.status not in ("submitted", "under_review"):
                raise HTTPException(
                    status_code=400,
                    detail="Only submitted applications can move to under_review",
                )
            app.status = new_status

        if app.status not in ("draft", "submitted", "under_review"):
            if payload:
                raise HTTPException(
                    status_code=400,
                    detail="Only draft or in-review applications can be edited",
                )
        elif app.status == "submitted" and payload.keys() - {"status"}:
            raise HTTPException(
                status_code=400,
                detail="Submitted applications cannot be edited except status",
            )

        if "commission_model" in payload and payload["commission_model"]:
            if payload["commission_model"] not in COMMISSION_MODELS:
                raise HTTPException(status_code=400, detail="Invalid commission model")

        if "documents" in payload and payload["documents"] is not None:
            payload["documents"] = [
                d if isinstance(d, dict) else d.model_dump() for d in payload["documents"]
            ]

        for key, value in payload.items():
            setattr(app, key, value)

        app.updated_at = _utc_now()
        await db.commit()
        await db.refresh(app)
        return _serialize(app)

    @staticmethod
    async def submit(db: AsyncSession, application_id: UUID) -> dict[str, Any]:
        app = await FactoryPartnerPortalService._load(db, application_id)
        if app.status != "draft":
            raise HTTPException(status_code=400, detail="Only draft applications can be submitted")
        if not app.cooperation_terms_accepted:
            raise HTTPException(status_code=400, detail="Cooperation terms must be accepted")
        if not (app.company_name or "").strip():
            raise HTTPException(status_code=400, detail="Company name is required")

        now = _utc_now()
        app.status = "submitted"
        app.submitted_at = now
        app.updated_at = now
        await db.commit()
        await db.refresh(app)
        logger.info("%s submit: id=%s", MARKER, app.id)
        return {
            "application": _serialize(app),
            "message": "Application submitted for manual review. No automatic approval.",
        }

    @staticmethod
    async def approve(db: AsyncSession, application_id: UUID) -> dict[str, Any]:
        app = await FactoryPartnerPortalService._load(db, application_id)
        if app.status not in _PENDING_STATUSES:
            raise HTTPException(
                status_code=400,
                detail="Only submitted or under_review applications can be approved",
            )
        now = _utc_now()
        app.status = "approved"
        app.reviewed_at = now
        app.updated_at = now
        await db.commit()
        await db.refresh(app)
        logger.info("%s approve: id=%s (manual only)", MARKER, app.id)
        return {
            "application": _serialize(app),
            "message": "Application approved. Create client manually when ready.",
        }

    @staticmethod
    async def reject(db: AsyncSession, application_id: UUID) -> dict[str, Any]:
        app = await FactoryPartnerPortalService._load(db, application_id)
        if app.status not in _PENDING_STATUSES:
            raise HTTPException(
                status_code=400,
                detail="Only submitted or under_review applications can be rejected",
            )
        now = _utc_now()
        app.status = "rejected"
        app.reviewed_at = now
        app.updated_at = now
        await db.commit()
        await db.refresh(app)
        logger.info("%s reject: id=%s", MARKER, app.id)
        return {
            "application": _serialize(app),
            "message": "Application rejected.",
        }

    @staticmethod
    async def create_client_from_application(
        db: AsyncSession,
        application_id: UUID,
    ) -> dict[str, Any]:
        """Admin-only explicit action — never called automatically."""
        app = await FactoryPartnerPortalService._load(db, application_id)
        if app.status != "approved":
            raise HTTPException(
                status_code=400,
                detail="Client can only be created from approved applications",
            )
        if app.created_client_id:
            raise HTTPException(
                status_code=400,
                detail="Client already created for this application",
            )

        categories = app.product_categories or []
        products_services = ", ".join(categories) if categories else None
        client_data = ClientCreate(
            company_name=app.company_name,
            source_language="zh",
            business_category=_map_business_category(app.industry),
            content_style="professional",
            notes=_contact_notes(app),
            business_description=app.company_description,
            products_services=products_services,
            target_audience=", ".join(app.target_markets or []) or None,
            cta_phone=app.contact_phone,
            cta_website=app.website,
            brand_name=app.company_name,
        )
        client = await ClientService.create(db, client_data)
        app.created_client_id = client.id
        if app.tenant_id:
            client.tenant_id = app.tenant_id
        app.updated_at = _utc_now()
        await db.commit()
        await db.refresh(app)
        logger.info(
            "%s create-client: application=%s client=%s",
            MARKER, app.id, client.id,
        )
        return {
            "application_id": app.id,
            "client_id": client.id,
            "company_name": client.company_name,
            "message": "Client profile created from application. No automatic publishing or sales actions.",
        }

    @staticmethod
    async def summary_widget(db: AsyncSession) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for st in APPLICATION_STATUSES:
            counts[st] = int(
                await db.scalar(
                    select(func.count())
                    .select_from(FactoryPartnerApplication)
                    .where(FactoryPartnerApplication.status == st),
                ) or 0,
            )

        latest_r = await db.execute(
            select(FactoryPartnerApplication.company_name)
            .where(FactoryPartnerApplication.status.in_(tuple(_PENDING_STATUSES)))
            .order_by(FactoryPartnerApplication.submitted_at.desc().nullslast())
            .limit(1),
        )
        latest = latest_r.scalar_one_or_none()

        return {
            "pending_review": counts.get("submitted", 0) + counts.get("under_review", 0),
            "submitted": counts.get("submitted", 0),
            "under_review": counts.get("under_review", 0),
            "approved": counts.get("approved", 0),
            "rejected": counts.get("rejected", 0),
            "draft": counts.get("draft", 0),
            "latest_company_name": latest,
        }

    @staticmethod
    async def executive_pending(
        db: AsyncSession,
        *,
        limit: int = 10,
    ) -> dict[str, Any]:
        result = await db.execute(
            select(FactoryPartnerApplication)
            .where(FactoryPartnerApplication.status.in_(tuple(_PENDING_STATUSES)))
            .order_by(FactoryPartnerApplication.submitted_at.desc().nullslast())
            .limit(limit),
        )
        items = [
            {
                "id": a.id,
                "company_name": a.company_name,
                "country": a.country,
                "status": a.status,
                "submitted_at": a.submitted_at,
                "industry": a.industry,
            }
            for a in result.scalars().all()
        ]
        widget = await FactoryPartnerPortalService.summary_widget(db)
        return {"pending": items, "counts": widget}
