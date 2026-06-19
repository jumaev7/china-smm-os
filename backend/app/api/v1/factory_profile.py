"""Factory Platform v2 — profile, catalog, certificates, export markets, performance, management."""
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.tenant_access import get_current_tenant_user, require_permission, require_tenant
from app.schemas.factory_profile import (
    FactoryCatalogProductCreate,
    FactoryCatalogProductUpdate,
    FactoryCatalogResponse,
    FactoryCertificateCreate,
    FactoryCertificateUpdate,
    FactoryCertificatesResponse,
    FactoryExportMarketCreate,
    FactoryExportMarketUpdate,
    FactoryExportMarketsResponse,
    FactoryMediaResponse,
    FactoryPerformanceResponse,
    FactoryPerformanceSummaryWidget,
    FactoryProfileReadinessResponse,
    FactoryProfileResponse,
    FactoryProfileScoreResponse,
    FactoryProfileUpdateRequest,
    FactoryVerificationStatusResponse,
)
from app.services.factory_profile_service import FactoryProfileService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/factory-platform", tags=["factory-platform"])


@router.get("/profile", response_model=FactoryProfileResponse)
async def factory_profile(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.profile(db, tenant_id),
        label="factory_profile.profile",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/catalog", response_model=FactoryCatalogResponse)
async def factory_catalog(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.catalog(db, tenant_id),
        label="factory_profile.catalog",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/certificates", response_model=FactoryCertificatesResponse)
async def factory_certificates(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.certificates(db, tenant_id),
        label="factory_profile.certificates",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/export-markets", response_model=FactoryExportMarketsResponse)
async def factory_export_markets(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.export_markets(db, tenant_id),
        label="factory_profile.export_markets",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/performance", response_model=FactoryPerformanceResponse)
async def factory_performance(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.performance(db, tenant_id),
        label="factory_profile.performance",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/profile-score", response_model=FactoryProfileScoreResponse)
async def factory_profile_score(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.profile_score(db, tenant_id),
        label="factory_profile.profile_score",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/verification-status", response_model=FactoryVerificationStatusResponse)
async def factory_verification_status(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.verification_status(db, tenant_id),
        label="factory_profile.verification_status",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/summary-widget", response_model=FactoryPerformanceSummaryWidget)
async def factory_performance_summary_widget(
    tenant_id: UUID | None = Query(None),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    scope_tenant = tenant_id or user.tenant_id
    require_tenant(scope_tenant, user)
    return await run_guarded(
        FactoryProfileService.summary_widget(db, tenant_id=scope_tenant),
        label="factory_profile.summary_widget",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/profile-readiness", response_model=FactoryProfileReadinessResponse)
async def factory_profile_readiness(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.profile_readiness(db, tenant_id),
        label="factory_profile.profile_readiness",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.patch("/profile", response_model=FactoryProfileResponse)
async def factory_profile_update(
    body: FactoryProfileUpdateRequest,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("company.profile.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.update_profile(db, tenant_id, body.model_dump(exclude_unset=True)),
        label="factory_profile.update_profile",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/catalog/products", status_code=201)
async def factory_catalog_product_create(
    body: FactoryCatalogProductCreate,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("products.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.create_catalog_product(db, tenant_id, body.model_dump()),
        label="factory_profile.create_product",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.patch("/catalog/products/{product_id}")
async def factory_catalog_product_update(
    product_id: UUID,
    body: FactoryCatalogProductUpdate,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("products.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.update_catalog_product(
            db, tenant_id, product_id, body.model_dump(exclude_unset=True),
        ),
        label="factory_profile.update_product",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.delete("/catalog/products/{product_id}")
async def factory_catalog_product_delete(
    product_id: UUID,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("products.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.delete_catalog_product(db, tenant_id, product_id),
        label="factory_profile.delete_product",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/certificates", status_code=201)
async def factory_certificate_create(
    body: FactoryCertificateCreate,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("company.profile.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.create_certificate(db, tenant_id, body.model_dump()),
        label="factory_profile.create_certificate",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.patch("/certificates/{certificate_id}")
async def factory_certificate_update(
    certificate_id: UUID,
    body: FactoryCertificateUpdate,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("company.profile.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.update_certificate(
            db, tenant_id, certificate_id, body.model_dump(exclude_unset=True),
        ),
        label="factory_profile.update_certificate",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.delete("/certificates/{certificate_id}")
async def factory_certificate_delete(
    certificate_id: UUID,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("company.profile.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.delete_certificate(db, tenant_id, certificate_id),
        label="factory_profile.delete_certificate",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/export-markets", status_code=201)
async def factory_export_market_create(
    body: FactoryExportMarketCreate,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("company.profile.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.create_export_market(db, tenant_id, body.model_dump()),
        label="factory_profile.create_export_market",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.patch("/export-markets/{market_id}")
async def factory_export_market_update(
    market_id: UUID,
    body: FactoryExportMarketUpdate,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("company.profile.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.update_export_market(
            db, tenant_id, market_id, body.model_dump(exclude_unset=True),
        ),
        label="factory_profile.update_export_market",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.delete("/export-markets/{market_id}")
async def factory_export_market_delete(
    market_id: UUID,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("company.profile.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.delete_export_market(db, tenant_id, market_id),
        label="factory_profile.delete_export_market",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/media", response_model=FactoryMediaResponse)
async def factory_media_list(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.list_media(db, tenant_id),
        label="factory_profile.list_media",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/media", status_code=201)
async def factory_media_upload(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    media_type: str = Form(..., description="image | video | pdf_catalog"),
    title: str | None = Form(None),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    user: CurrentTenantUser = Depends(require_permission("company.profile.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.upload_media(
            db, tenant_id, file=file, media_type=media_type, title=title, description=description,
        ),
        label="factory_profile.upload_media",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.delete("/media/{media_id}")
async def factory_media_delete(
    media_id: UUID,
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(require_permission("company.profile.manage")),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryProfileService.delete_media(db, tenant_id, media_id),
        label="factory_profile.delete_media",
        timeout=SCAN_TIMEOUT_SEC,
    )
