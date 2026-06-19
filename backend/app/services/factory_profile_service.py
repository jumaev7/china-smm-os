"""Factory Platform v2 — company profile, catalog, certificates, export markets, performance."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.endpoint_guard import safe_section
from app.models.factory_partner_application import FactoryPartnerApplication
from app.models.factory_platform_profile import FactoryPlatformProfile
from app.models.factory_profile import (
    FactoryCatalogProduct,
    FactoryCertificate,
    FactoryExportMarket,
    FactoryMediaAsset,
)
from app.models.media import MediaFile
from app.models.product import Product
from app.services.factory_platform_service import FactoryPlatformService, _as_str_list

logger = logging.getLogger(__name__)

MARKER = "[Factory Profile]"

_PROFILE_FIELDS = (
    "company_name",
    "brand_name",
    "description",
    "country",
    "city",
    "address",
    "website",
    "contact_email",
    "contact_phone",
    "founded_year",
    "employee_count",
)

_DEMO_CERTIFICATES = (
    ("CE Mark", "CE", "European Notified Body"),
    ("ISO 9001", "ISO9001", "International Organization for Standardization"),
    ("ISO 14001", "ISO14001", "International Organization for Standardization"),
    ("HACCP", "HACCP", "Food Safety Authority"),
    ("FDA Registration", "FDA", "U.S. Food and Drug Administration"),
)

_READINESS_ITEMS: tuple[tuple[str, str, int], ...] = (
    ("company_name", "Company name", 10),
    ("company_description", "Company description", 10),
    ("logo", "Logo", 10),
    ("factory_photos", "Factory photos", 10),
    ("factory_video", "Factory video", 5),
    ("product_catalog", "Product catalog", 15),
    ("certificates", "Certificates", 15),
    ("export_markets", "Export markets", 15),
    ("contact_information", "Contact information", 10),
)

_DEFAULT_REUSABLE_MODULES = ["customer_portal", "buyer_acquisition", "smm"]

_PDF_MIMES = frozenset({
    "application/pdf",
})
_MAX_PDF_BYTES = 50 * 1024 * 1024


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _cert_expired(expiry: date | None) -> bool:
    if expiry is None:
        return False
    return expiry < _utc_today()


class FactoryProfileService:
    """Tenant-scoped factory workspace profile — read-only aggregation, no CRM writes."""

    @staticmethod
    def _safety_notice() -> str:
        return "Read-only factory workspace — no messaging, outreach, CRM writes, or auto verification."

    @staticmethod
    async def _ensure_v2_data(db: AsyncSession, scope: dict[str, Any]) -> FactoryPlatformProfile:
        profile = await FactoryPlatformService._get_or_seed_profile(db, scope)
        tenant_id = scope["tenant_id"]
        changed = False

        if not profile.brand_name and profile.company_name:
            profile.brand_name = profile.company_name
            changed = True

        if profile.company_description and not getattr(profile, "description", None):
            pass

        app_r = await db.execute(
            select(FactoryPartnerApplication)
            .where(
                (FactoryPartnerApplication.tenant_id == tenant_id)
                | (FactoryPartnerApplication.created_client_id == scope["company_id"]),
            )
            .order_by(FactoryPartnerApplication.updated_at.desc())
            .limit(1),
        )
        app = app_r.scalar_one_or_none()
        if app and app.status == "approved" and profile.verification_status == "unverified":
            profile.verification_status = "pending"
            changed = True

        cat_count = await db.scalar(
            select(func.count())
            .select_from(FactoryCatalogProduct)
            .where(FactoryCatalogProduct.tenant_id == tenant_id),
        ) or 0
        if cat_count == 0:
            await FactoryProfileService._seed_catalog(db, scope, profile, app)
            changed = True

        cert_count = await db.scalar(
            select(func.count())
            .select_from(FactoryCertificate)
            .where(FactoryCertificate.tenant_id == tenant_id),
        ) or 0
        if cert_count == 0:
            await FactoryProfileService._seed_certificates(db, tenant_id)
            changed = True

        market_count = await db.scalar(
            select(func.count())
            .select_from(FactoryExportMarket)
            .where(FactoryExportMarket.tenant_id == tenant_id),
        ) or 0
        if market_count == 0:
            await FactoryProfileService._seed_export_markets(db, scope, profile)
            changed = True

        if changed:
            await db.commit()
            await db.refresh(profile)

        return profile

    @staticmethod
    async def _seed_catalog(
        db: AsyncSession,
        scope: dict[str, Any],
        profile: FactoryPlatformProfile,
        app: FactoryPartnerApplication | None,
    ) -> None:
        tenant_id = scope["tenant_id"]
        company_id = scope["company_id"]
        markets = _as_str_list(profile.markets) or _as_str_list(profile.export_regions)
        categories = _as_str_list(profile.product_categories)

        product_r = await db.execute(
            select(Product)
            .where(Product.client_id == company_id)
            .order_by(Product.created_at.desc())
            .limit(12),
        )
        products = product_r.scalars().all()

        if products:
            for idx, prod in enumerate(products):
                db.add(FactoryCatalogProduct(
                    tenant_id=tenant_id,
                    product_name=prod.name,
                    category=prod.category or (categories[0] if categories else None),
                    description=prod.description,
                    target_markets=markets[:5] if markets else [],
                    status="active" if prod.active else "draft",
                ))
            return

        seed_names = categories or (
            _as_str_list(app.product_categories if app else None) or ["Export Product Line"]
        )
        for idx, name in enumerate(seed_names[:6]):
            db.add(FactoryCatalogProduct(
                tenant_id=tenant_id,
                product_name=name if isinstance(name, str) else str(name),
                category=categories[idx % len(categories)] if categories else "General",
                description=f"Factory catalog item — {name}",
                target_markets=markets[:3] if markets else ["Global"],
                status="active" if idx == 0 else "draft",
            ))

    @staticmethod
    async def _seed_certificates(db: AsyncSession, tenant_id: UUID) -> None:
        today = _utc_today()
        for name, cert_type, authority in _DEMO_CERTIFICATES[:3]:
            db.add(FactoryCertificate(
                tenant_id=tenant_id,
                certificate_name=name,
                certificate_type=cert_type,
                issuing_authority=authority,
                expiry_date=date(today.year + 2, 12, 31),
            ))

    @staticmethod
    async def _seed_export_markets(
        db: AsyncSession,
        scope: dict[str, Any],
        profile: FactoryPlatformProfile,
    ) -> None:
        tenant_id = scope["tenant_id"]
        countries = _as_str_list(profile.export_regions) or _as_str_list(profile.markets)
        if not countries:
            countries = ["Germany", "United States", "Russia"]

        for idx, country in enumerate(countries[:8]):
            db.add(FactoryExportMarket(
                tenant_id=tenant_id,
                country=country,
                market_score=max(40, 88 - idx * 7),
                active_buyers=max(0, 5 - idx),
                opportunities=max(1, 4 - idx // 2),
            ))

    @staticmethod
    def _serialize_company_profile(profile: FactoryPlatformProfile) -> dict[str, Any]:
        return {
            "company_name": profile.company_name,
            "brand_name": profile.brand_name,
            "description": profile.company_description,
            "country": profile.country,
            "city": profile.city,
            "address": profile.address,
            "website": profile.website,
            "contact_email": profile.contact_email,
            "contact_phone": profile.contact_phone,
            "founded_year": profile.founded_year,
            "employee_count": profile.employee_count,
            "industry": profile.industry,
            "logo_url": profile.logo_url,
            "factory_video_url": profile.factory_video_url,
            "updated_at": profile.updated_at,
        }

    @staticmethod
    def _serialize_catalog_product(row: FactoryCatalogProduct) -> dict[str, Any]:
        return {
            "product_id": row.id,
            "product_name": row.product_name,
            "category": row.category,
            "description": row.description,
            "target_markets": _as_str_list(row.target_markets),
            "image_url": row.image_url,
            "moq": row.moq,
            "price_min": float(row.price_min) if row.price_min is not None else None,
            "price_max": float(row.price_max) if row.price_max is not None else None,
            "currency": row.currency or "USD",
            "export_available": bool(row.export_available),
            "status": row.status,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _serialize_certificate(row: FactoryCertificate) -> dict[str, Any]:
        expired = _cert_expired(row.expiry_date)
        return {
            "certificate_id": row.id,
            "certificate_name": row.certificate_name,
            "certificate_type": row.certificate_type,
            "issuing_authority": row.issuing_authority,
            "certificate_number": row.certificate_number,
            "issue_date": row.issue_date,
            "expiry_date": row.expiry_date,
            "document_url": row.document_url,
            "is_expired": expired,
        }

    @staticmethod
    async def _media_counts(db: AsyncSession, tenant_id: UUID) -> dict[str, int]:
        rows = (
            await db.execute(
                select(FactoryMediaAsset.media_type, func.count())
                .where(FactoryMediaAsset.tenant_id == tenant_id)
                .group_by(FactoryMediaAsset.media_type),
            )
        ).all()
        counts = {row[0]: int(row[1]) for row in rows}
        return {
            "image": counts.get("image", 0),
            "video": counts.get("video", 0),
            "pdf_catalog": counts.get("pdf_catalog", 0),
        }

    @staticmethod
    async def _compute_readiness_breakdown(
        db: AsyncSession,
        tenant_id: UUID,
        profile: FactoryPlatformProfile,
    ) -> dict[str, Any]:
        media_counts = await FactoryProfileService._media_counts(db, tenant_id)
        products = (
            await db.execute(
                select(FactoryCatalogProduct).where(FactoryCatalogProduct.tenant_id == tenant_id),
            )
        ).scalars().all()
        active_products = [
            p for p in products
            if p.status == "active" and (p.export_available is None or p.export_available)
        ]
        certificates = (
            await db.execute(
                select(FactoryCertificate).where(FactoryCertificate.tenant_id == tenant_id),
            )
        ).scalars().all()
        valid_certs = [c for c in certificates if not _cert_expired(c.expiry_date)]
        markets = (
            await db.execute(
                select(FactoryExportMarket).where(FactoryExportMarket.tenant_id == tenant_id),
            )
        ).scalars().all()

        checks: dict[str, bool] = {
            "company_name": bool(profile.company_name and profile.company_name.strip()),
            "company_description": bool(profile.company_description and profile.company_description.strip()),
            "logo": bool(profile.logo_url),
            "factory_photos": media_counts["image"] > 0,
            "factory_video": bool(profile.factory_video_url) or media_counts["video"] > 0,
            "product_catalog": len(active_products) > 0,
            "certificates": len(valid_certs) > 0,
            "export_markets": len(markets) > 0,
            "contact_information": bool(profile.contact_email and profile.contact_phone),
        }

        actions: dict[str, str] = {
            "company_name": "Add your official company name in Company Profile.",
            "company_description": "Write a clear factory description for international buyers.",
            "logo": "Upload a company logo in Media Center or set logo URL.",
            "factory_photos": "Upload factory photos in Media Center.",
            "factory_video": "Add a factory tour video in Media Center.",
            "product_catalog": "Create at least one active export-ready product.",
            "certificates": "Upload ISO, CE, SGS, FDA, or HALAL certificates.",
            "export_markets": "Add target export markets (Uzbekistan, Kazakhstan, UAE, etc.).",
            "contact_information": "Add contact email and phone for buyer inquiries.",
        }

        breakdown: list[dict[str, Any]] = []
        missing_items: list[str] = []
        recommended_actions: list[str] = []
        total = 0

        for key, label, max_score in _READINESS_ITEMS:
            complete = checks.get(key, False)
            score = max_score if complete else 0
            total += score
            item = {
                "key": key,
                "label": label,
                "score": score,
                "max_score": max_score,
                "complete": complete,
                "recommended_action": None if complete else actions.get(key),
            }
            breakdown.append(item)
            if not complete:
                missing_items.append(key)
                if actions.get(key):
                    recommended_actions.append(actions[key])

        profile_pts = sum(
            b["score"] for b in breakdown
            if b["key"] in ("company_name", "company_description", "logo", "factory_photos", "factory_video", "contact_information")
        )
        product_pts = next((b["score"] for b in breakdown if b["key"] == "product_catalog"), 0)
        cert_pts = next((b["score"] for b in breakdown if b["key"] == "certificates"), 0)
        market_pts = next((b["score"] for b in breakdown if b["key"] == "export_markets"), 0)
        media_pts = sum(
            b["score"] for b in breakdown if b["key"] in ("logo", "factory_photos", "factory_video")
        )

        return {
            "profile_score": min(100, total),
            "components": {
                "profile": profile_pts,
                "products": product_pts,
                "certificates": cert_pts,
                "export_markets": market_pts,
                "media": media_pts,
            },
            "breakdown": breakdown,
            "missing_items": missing_items,
            "recommended_actions": recommended_actions[:8],
        }

    @staticmethod
    def _profile_field_score(profile: FactoryPlatformProfile) -> tuple[int, list[str]]:
        data = FactoryProfileService._serialize_company_profile(profile)
        filled = sum(1 for key in _PROFILE_FIELDS if data.get(key) not in (None, "", []))
        missing = [f for f in _PROFILE_FIELDS if data.get(f) in (None, "", [])]
        score = int(round((filled / len(_PROFILE_FIELDS)) * 25))
        return score, missing

    @staticmethod
    async def _compute_scores(
        db: AsyncSession,
        tenant_id: UUID,
        profile: FactoryPlatformProfile,
    ) -> dict[str, Any]:
        readiness = await FactoryProfileService._compute_readiness_breakdown(db, tenant_id, profile)
        components = readiness["components"]
        return {
            "profile_score": readiness["profile_score"],
            "components": {
                "profile": components.get("profile", 0),
                "products": components.get("products", 0),
                "certificates": components.get("certificates", 0),
                "export_markets": components.get("export_markets", 0),
            },
            "breakdown": readiness["breakdown"],
            "missing_items": readiness["missing_items"],
            "recommended_actions": readiness["recommended_actions"],
        }

    @staticmethod
    async def profile(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        profile = await FactoryProfileService._ensure_v2_data(db, scope)
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "profile": FactoryProfileService._serialize_company_profile(profile),
            "errors": [],
            "safety_notice": FactoryProfileService._safety_notice(),
        }

    @staticmethod
    async def catalog(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        await FactoryProfileService._ensure_v2_data(db, scope)

        rows = (
            await db.execute(
                select(FactoryCatalogProduct)
                .where(FactoryCatalogProduct.tenant_id == tenant_id)
                .order_by(FactoryCatalogProduct.updated_at.desc()),
            )
        ).scalars().all()

        items = [FactoryProfileService._serialize_catalog_product(row) for row in rows]
        status_counts = {s: 0 for s in ("active", "draft", "archived")}
        for row in rows:
            if row.status in status_counts:
                status_counts[row.status] += 1

        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "items": items,
            "total": len(items),
            "active_count": status_counts["active"],
            "draft_count": status_counts["draft"],
            "archived_count": status_counts["archived"],
            "errors": [],
        }

    @staticmethod
    async def certificates(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        await FactoryProfileService._ensure_v2_data(db, scope)

        rows = (
            await db.execute(
                select(FactoryCertificate)
                .where(FactoryCertificate.tenant_id == tenant_id)
                .order_by(FactoryCertificate.expiry_date.asc().nulls_last()),
            )
        ).scalars().all()

        items = []
        valid_count = 0
        expired_count = 0
        for row in rows:
            item = FactoryProfileService._serialize_certificate(row)
            if item["is_expired"]:
                expired_count += 1
            else:
                valid_count += 1
            items.append(item)

        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "items": items,
            "total": len(items),
            "valid_count": valid_count,
            "expired_count": expired_count,
            "errors": [],
        }

    @staticmethod
    async def export_markets(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        company_id = scope["company_id"]
        await FactoryProfileService._ensure_v2_data(db, scope)
        errors: list[str] = []

        rows = (
            await db.execute(
                select(FactoryExportMarket)
                .where(FactoryExportMarket.tenant_id == tenant_id)
                .order_by(FactoryExportMarket.market_score.desc()),
            )
        ).scalars().all()

        acquisition_data = await safe_section(
            "buyer_acquisition",
            FactoryProfileService._enrich_markets_from_acquisition(
                db, tenant_id=tenant_id, client_id=company_id, markets=rows,
            ),
            default=None,
            errors=errors,
            db=db,
        )
        if acquisition_data:
            rows = acquisition_data

        items = [
            {
                "market_id": row.id,
                "country": row.country,
                "market_score": row.market_score,
                "active_buyers": row.active_buyers,
                "opportunities": row.opportunities,
            }
            for row in rows
        ]

        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "items": items,
            "total": len(items),
            "errors": errors,
        }

    @staticmethod
    async def _enrich_markets_from_acquisition(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        client_id: UUID,
        markets: list[FactoryExportMarket],
    ) -> list[FactoryExportMarket]:
        from app.services.buyer_acquisition_service import BuyerAcquisitionService

        insights = await BuyerAcquisitionService.insights(
            db, client_id=client_id, tenant_id=tenant_id, limit=50,
        )
        country_buyers: dict[str, int] = {}
        for buyer in insights.get("top_buyers") or []:
            country = (buyer.get("country") or "").strip()
            if country:
                country_buyers[country.lower()] = country_buyers.get(country.lower(), 0) + 1

        opp_data = await BuyerAcquisitionService.list_opportunities(
            db, client_id=client_id, tenant_id=tenant_id, limit=50,
        )
        country_opps: dict[str, int] = {}
        for opp in opp_data.get("items") or []:
            country = (opp.get("country") or "").strip()
            if country:
                country_opps[country.lower()] = country_opps.get(country.lower(), 0) + 1

        for market in markets:
            key = market.country.lower()
            buyers = country_buyers.get(key, market.active_buyers)
            opps = country_opps.get(key, market.opportunities)
            if buyers != market.active_buyers or opps != market.opportunities:
                market.active_buyers = buyers
                market.opportunities = opps
                market.market_score = min(100, market.market_score + min(10, buyers * 2 + opps))

        return markets

    @staticmethod
    async def profile_score(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        profile = await FactoryProfileService._ensure_v2_data(db, scope)
        scores = await FactoryProfileService._compute_scores(db, tenant_id, profile)
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            **scores,
            "errors": [],
        }

    @staticmethod
    async def profile_readiness(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        profile = await FactoryProfileService._ensure_v2_data(db, scope)
        scores = await FactoryProfileService._compute_scores(db, tenant_id, profile)
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            **scores,
            "errors": [],
        }

    @staticmethod
    async def performance(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        from app.services.buyer_acquisition_service import BuyerAcquisitionService
        from app.services.marketplace_service import MarketplaceService

        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        company_id = scope["company_id"]
        profile = await FactoryProfileService._ensure_v2_data(db, scope)
        errors: list[str] = []

        scores = await FactoryProfileService._compute_scores(db, tenant_id, profile)
        profile_score = scores["profile_score"]

        acquisition = await safe_section(
            "buyer_acquisition",
            BuyerAcquisitionService.overview(db, client_id=company_id, tenant_id=tenant_id),
            default={},
            errors=errors,
            db=db,
        )
        total_buyers = int(acquisition.get("total_buyers") or 0)
        marketplace_opps = int(acquisition.get("marketplace_opportunities") or 0)
        network_opps = int(acquisition.get("network_opportunities") or 0)
        active_opportunities = marketplace_opps + network_opps

        marketplace = await safe_section(
            "marketplace",
            MarketplaceService.overview(db, tenant_id=tenant_id),
            default={},
            errors=errors,
            db=db,
        )
        open_opps = int(marketplace.get("open_opportunities") or 0)
        marketplace_visibility = min(
            100,
            profile_score // 2 + min(40, open_opps * 5) + min(20, total_buyers),
        )

        buyer_acquisition_score = min(
            100,
            int(acquisition.get("strategic_buyers") or 0) * 8
            + int(acquisition.get("high_potential_buyers") or 0) * 5
            + min(30, total_buyers * 2),
        )

        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "total_buyers": total_buyers,
            "active_opportunities": active_opportunities,
            "marketplace_visibility": marketplace_visibility,
            "buyer_acquisition_score": buyer_acquisition_score,
            "profile_score": profile_score,
            "errors": errors,
            "safety_notice": FactoryProfileService._safety_notice(),
        }

    @staticmethod
    async def verification_status(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        profile = await FactoryProfileService._ensure_v2_data(db, scope)
        scores = await FactoryProfileService._compute_scores(db, tenant_id, profile)

        requirements_met: list[str] = []
        requirements_missing: list[str] = []
        components = scores["components"]

        if components["profile"] >= 18:
            requirements_met.append("company_profile_complete")
        else:
            requirements_missing.append("company_profile_complete")

        if components["products"] >= 10:
            requirements_met.append("product_catalog_active")
        else:
            requirements_missing.append("product_catalog_active")

        if components["certificates"] >= 10:
            requirements_met.append("certificates_on_file")
        else:
            requirements_missing.append("certificates_on_file")

        if components["export_markets"] >= 10:
            requirements_met.append("export_markets_defined")
        else:
            requirements_missing.append("export_markets_defined")

        status = profile.verification_status or "unverified"
        if status == "unverified" and len(requirements_met) >= 3:
            status = "pending"

        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "verification_status": status,
            "profile_score": scores["profile_score"],
            "requirements_met": requirements_met,
            "requirements_missing": requirements_missing,
            "errors": [],
            "safety_notice": "Verification is manual only — no automatic verification.",
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        if tenant_id is None:
            workspaces = await FactoryPlatformService.list_workspaces(db, limit=1)
            items = workspaces.get("items") or []
            if not items:
                return {
                    "profile_score": 0,
                    "catalog_score": 0,
                    "certificate_score": 0,
                    "export_market_score": 0,
                    "media_score": 0,
                    "total_buyers": 0,
                    "active_opportunities": 0,
                    "marketplace_visibility": 0,
                    "buyer_acquisition_score": 0,
                    "verification_status": "unverified",
                    "company_name": None,
                    "missing_items": [],
                    "top_recommended_action": None,
                    "errors": [],
                    "safety_notice": FactoryProfileService._safety_notice(),
                }
            tenant_id = items[0]["tenant_id"]

        perf = await FactoryProfileService.performance(db, tenant_id)
        ver = await FactoryProfileService.verification_status(db, tenant_id)
        score_data = await FactoryProfileService.profile_score(db, tenant_id)
        components = score_data.get("components") or {}
        recommended = score_data.get("recommended_actions") or []
        return {
            "profile_score": perf["profile_score"],
            "catalog_score": components.get("products", 0),
            "certificate_score": components.get("certificates", 0),
            "export_market_score": components.get("export_markets", 0),
            "media_score": int((components.get("profile", 0)) * 0.4),
            "total_buyers": perf["total_buyers"],
            "active_opportunities": perf["active_opportunities"],
            "marketplace_visibility": perf["marketplace_visibility"],
            "buyer_acquisition_score": perf["buyer_acquisition_score"],
            "verification_status": ver["verification_status"],
            "company_name": perf["tenant"]["company_name"],
            "missing_items": score_data.get("missing_items") or [],
            "top_recommended_action": recommended[0] if recommended else None,
            "errors": perf.get("errors") or [],
            "safety_notice": FactoryProfileService._safety_notice(),
        }

    @staticmethod
    async def executive_overview(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        widget = await FactoryProfileService.summary_widget(db, tenant_id=tenant_id)
        if tenant_id is None:
            workspaces = await FactoryPlatformService.list_workspaces(db, limit=1)
            items = workspaces.get("items") or []
            tenant_id = items[0]["tenant_id"] if items else None

        readiness: dict[str, Any] = {}
        if tenant_id:
            score_data = await FactoryProfileService.profile_score(db, tenant_id)
            readiness = {
                "profile_score": score_data["profile_score"],
                "components": score_data["components"],
                "missing_items": score_data["missing_items"][:limit],
            }

        return {
            "performance": widget,
            "readiness": readiness,
            "safety_notice": FactoryProfileService._safety_notice(),
        }

    @staticmethod
    async def factory_snapshot(
        db: AsyncSession,
        *,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        profile_data = await FactoryProfileService.profile(db, tenant_id)
        score_data = await FactoryProfileService.profile_score(db, tenant_id)
        perf = await FactoryProfileService.performance(db, tenant_id)
        ver = await FactoryProfileService.verification_status(db, tenant_id)
        return {
            "company_name": profile_data["profile"]["company_name"],
            "brand_name": profile_data["profile"].get("brand_name"),
            "profile_score": score_data["profile_score"],
            "components": score_data["components"],
            "verification_status": ver["verification_status"],
            "total_buyers": perf["total_buyers"],
            "active_opportunities": perf["active_opportunities"],
            "safety_notice": FactoryProfileService._safety_notice(),
        }

    @staticmethod
    async def readiness_indicators(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        if tenant_id is None and client_id is not None:
            from app.models.client import Client
            client = await db.get(Client, client_id)
            if client and client.tenant_id:
                tenant_id = client.tenant_id

        if tenant_id is None:
            return {
                "profile_score": 0,
                "components": {},
                "verification_status": "unverified",
                "indicators": [],
                "safety_notice": FactoryProfileService._safety_notice(),
            }

        score_data = await FactoryProfileService.profile_score(db, tenant_id)
        ver = await FactoryProfileService.verification_status(db, tenant_id)
        components = score_data["components"]
        indicators = [
            {
                "label": "Company Profile",
                "score": components.get("profile", 0),
                "max": 25,
                "status": "ready" if components.get("profile", 0) >= 18 else "needs_work",
            },
            {
                "label": "Product Catalog",
                "score": components.get("products", 0),
                "max": 25,
                "status": "ready" if components.get("products", 0) >= 10 else "needs_work",
            },
            {
                "label": "Certificates",
                "score": components.get("certificates", 0),
                "max": 25,
                "status": "ready" if components.get("certificates", 0) >= 10 else "needs_work",
            },
            {
                "label": "Export Markets",
                "score": components.get("export_markets", 0),
                "max": 25,
                "status": "ready" if components.get("export_markets", 0) >= 10 else "needs_work",
            },
        ]
        return {
            "profile_score": score_data["profile_score"],
            "components": components,
            "verification_status": ver["verification_status"],
            "indicators": indicators,
            "missing_items": score_data["missing_items"][:8],
            "safety_notice": FactoryProfileService._safety_notice(),
        }

    @staticmethod
    async def integration_probe(db: AsyncSession, *, tenant_id: UUID | None = None) -> dict[str, Any]:
        """Lightweight probe for revenue forecast / system integrations."""
        try:
            widget = await FactoryProfileService.summary_widget(db, tenant_id=tenant_id)
            return {
                "ok": True,
                "profile_score": widget.get("profile_score", 0),
                "verification_status": widget.get("verification_status", "unverified"),
            }
        except Exception as exc:
            logger.warning("%s integration probe failed: %s", MARKER, exc)
            return {"ok": False, "error": str(exc)[:200]}

    # ─── Profile / catalog / certificate / market / media management ─────────

    @staticmethod
    async def update_profile(
        db: AsyncSession,
        tenant_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        profile = await FactoryProfileService._ensure_v2_data(db, scope)

        field_map = {
            "description": "company_description",
        }
        for key, value in payload.items():
            if value is None:
                continue
            attr = field_map.get(key, key)
            if hasattr(profile, attr):
                setattr(profile, attr, value)
        if payload.get("company_name"):
            profile.company_name = payload["company_name"]

        await db.commit()
        await db.refresh(profile)
        return await FactoryProfileService.profile(db, tenant_id)

    @staticmethod
    async def create_catalog_product(
        db: AsyncSession,
        tenant_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        row = FactoryCatalogProduct(
            tenant_id=tenant_id,
            product_name=payload["product_name"],
            category=payload.get("category"),
            description=payload.get("description"),
            target_markets=payload.get("target_markets") or [],
            image_url=payload.get("image_url"),
            moq=payload.get("moq"),
            price_min=payload.get("price_min"),
            price_max=payload.get("price_max"),
            currency=payload.get("currency") or "USD",
            export_available=payload.get("export_available", True),
            status=payload.get("status") or "draft",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "item": FactoryProfileService._serialize_catalog_product(row),
        }

    @staticmethod
    async def update_catalog_product(
        db: AsyncSession,
        tenant_id: UUID,
        product_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        row = await db.get(FactoryCatalogProduct, product_id)
        if not row or row.tenant_id != tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Catalog product not found")
        for key, value in payload.items():
            if value is not None and hasattr(row, key):
                setattr(row, key, value)
        await db.commit()
        await db.refresh(row)
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "item": FactoryProfileService._serialize_catalog_product(row),
        }

    @staticmethod
    async def delete_catalog_product(
        db: AsyncSession,
        tenant_id: UUID,
        product_id: UUID,
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        row = await db.get(FactoryCatalogProduct, product_id)
        if not row or row.tenant_id != tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Catalog product not found")
        await db.delete(row)
        await db.commit()
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "deleted": True,
            "product_id": product_id,
        }

    @staticmethod
    async def create_certificate(
        db: AsyncSession,
        tenant_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        row = FactoryCertificate(
            tenant_id=tenant_id,
            certificate_name=payload["certificate_name"],
            certificate_type=payload["certificate_type"],
            issuing_authority=payload.get("issuing_authority"),
            certificate_number=payload.get("certificate_number"),
            issue_date=payload.get("issue_date"),
            expiry_date=payload.get("expiry_date"),
            document_url=payload.get("document_url"),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "item": FactoryProfileService._serialize_certificate(row),
        }

    @staticmethod
    async def update_certificate(
        db: AsyncSession,
        tenant_id: UUID,
        certificate_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        row = await db.get(FactoryCertificate, certificate_id)
        if not row or row.tenant_id != tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Certificate not found")
        for key, value in payload.items():
            if value is not None and hasattr(row, key):
                setattr(row, key, value)
        await db.commit()
        await db.refresh(row)
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "item": FactoryProfileService._serialize_certificate(row),
        }

    @staticmethod
    async def delete_certificate(
        db: AsyncSession,
        tenant_id: UUID,
        certificate_id: UUID,
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        row = await db.get(FactoryCertificate, certificate_id)
        if not row or row.tenant_id != tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Certificate not found")
        await db.delete(row)
        await db.commit()
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "deleted": True,
            "certificate_id": certificate_id,
        }

    @staticmethod
    async def create_export_market(
        db: AsyncSession,
        tenant_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        row = FactoryExportMarket(
            tenant_id=tenant_id,
            country=payload["country"],
            market_score=int(payload.get("market_score") or 50),
            active_buyers=int(payload.get("active_buyers") or 0),
            opportunities=int(payload.get("opportunities") or 0),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "item": {
                "market_id": row.id,
                "country": row.country,
                "market_score": row.market_score,
                "active_buyers": row.active_buyers,
                "opportunities": row.opportunities,
            },
        }

    @staticmethod
    async def update_export_market(
        db: AsyncSession,
        tenant_id: UUID,
        market_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        row = await db.get(FactoryExportMarket, market_id)
        if not row or row.tenant_id != tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Export market not found")
        for key, value in payload.items():
            if value is not None and hasattr(row, key):
                setattr(row, key, value)
        await db.commit()
        await db.refresh(row)
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "item": {
                "market_id": row.id,
                "country": row.country,
                "market_score": row.market_score,
                "active_buyers": row.active_buyers,
                "opportunities": row.opportunities,
            },
        }

    @staticmethod
    async def delete_export_market(
        db: AsyncSession,
        tenant_id: UUID,
        market_id: UUID,
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        row = await db.get(FactoryExportMarket, market_id)
        if not row or row.tenant_id != tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Export market not found")
        await db.delete(row)
        await db.commit()
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "deleted": True,
            "market_id": market_id,
        }

    @staticmethod
    def _media_url(asset: FactoryMediaAsset, media_file: MediaFile | None) -> str | None:
        from app.core.storage import storage
        if media_file:
            return storage.get_url(media_file.storage_path)
        if asset.storage_path:
            return storage.get_url(asset.storage_path)
        return None

    @staticmethod
    def _serialize_media(asset: FactoryMediaAsset, media_file: MediaFile | None = None) -> dict[str, Any]:
        return {
            "media_id": asset.id,
            "media_type": asset.media_type,
            "title": asset.title,
            "description": asset.description,
            "url": FactoryProfileService._media_url(asset, media_file),
            "original_filename": asset.original_filename,
            "reusable_modules": _as_str_list(asset.reusable_modules) or _DEFAULT_REUSABLE_MODULES,
            "created_at": asset.created_at,
        }

    @staticmethod
    async def list_media(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        rows = (
            await db.execute(
                select(FactoryMediaAsset)
                .where(FactoryMediaAsset.tenant_id == tenant_id)
                .order_by(FactoryMediaAsset.created_at.desc()),
            )
        ).scalars().all()
        items = []
        image_count = video_count = pdf_count = 0
        for row in rows:
            mf = await db.get(MediaFile, row.media_file_id) if row.media_file_id else None
            item = FactoryProfileService._serialize_media(row, mf)
            items.append(item)
            if row.media_type == "image":
                image_count += 1
            elif row.media_type == "video":
                video_count += 1
            elif row.media_type == "pdf_catalog":
                pdf_count += 1
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "items": items,
            "total": len(items),
            "image_count": image_count,
            "video_count": video_count,
            "pdf_count": pdf_count,
            "errors": [],
        }

    @staticmethod
    async def upload_media(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        file,
        media_type: str,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        from fastapi import HTTPException, UploadFile
        from app.core.storage import storage
        from app.services.media_service import MediaService

        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        company_id = scope["company_id"]

        media_file_id = None
        storage_path = None
        original_filename = file.filename

        if media_type == "pdf_catalog":
            mime = (file.content_type or "").lower().split(";")[0].strip()
            if mime not in _PDF_MIMES and not (file.filename or "").lower().endswith(".pdf"):
                raise HTTPException(status_code=415, detail="PDF catalog requires application/pdf")
            data = await file.read()
            if len(data) > _MAX_PDF_BYTES:
                raise HTTPException(status_code=413, detail="PDF too large (max 50 MB)")
            storage_path = await storage.save_file(
                data,
                filename=file.filename or "catalog.pdf",
                folder=f"factory/{tenant_id}/pdf",
            )
        elif media_type in ("image", "video"):
            mf = await MediaService.upload(db, company_id, file)
            media_file_id = mf.id
            storage_path = mf.storage_path
            if media_type == "image" and not scope["client"].logo_url:
                profile = await FactoryProfileService._ensure_v2_data(db, scope)
                url = storage.get_url(mf.storage_path)
                profile.logo_url = url
                await db.commit()
        else:
            raise HTTPException(status_code=400, detail="media_type must be image, video, or pdf_catalog")

        asset = FactoryMediaAsset(
            tenant_id=tenant_id,
            media_type=media_type,
            title=title or (file.filename if hasattr(file, "filename") else None),
            description=description,
            media_file_id=media_file_id,
            storage_path=storage_path if media_type == "pdf_catalog" else None,
            original_filename=original_filename,
            reusable_modules=_DEFAULT_REUSABLE_MODULES,
        )
        db.add(asset)
        if media_type == "video":
            profile = await FactoryProfileService._ensure_v2_data(db, scope)
            mf = await db.get(MediaFile, media_file_id) if media_file_id else None
            if mf:
                profile.factory_video_url = storage.get_url(mf.storage_path)
        await db.commit()
        await db.refresh(asset)
        mf = await db.get(MediaFile, asset.media_file_id) if asset.media_file_id else None
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "item": FactoryProfileService._serialize_media(asset, mf),
        }

    @staticmethod
    async def delete_media(
        db: AsyncSession,
        tenant_id: UUID,
        media_id: UUID,
    ) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        row = await db.get(FactoryMediaAsset, media_id)
        if not row or row.tenant_id != tenant_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Media asset not found")
        await db.delete(row)
        await db.commit()
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "deleted": True,
            "media_id": media_id,
        }

    @staticmethod
    async def reusable_media_for_modules(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        module: str,
    ) -> list[dict[str, Any]]:
        """Media filtered by reusable module — for Customer Portal, Buyer Acquisition, SMM."""
        data = await FactoryProfileService.list_media(db, tenant_id)
        return [
            item for item in data["items"]
            if module in (item.get("reusable_modules") or [])
        ]
