"""Tenant-scoped Advertising Intelligence APIs.

Prefix: /advertising. Read-only toward ad providers — this surface NEVER
creates, edits, pauses, deletes, or changes budgets on provider campaigns, ad
groups, ads, or creatives. The only writes are:
  * mock account registration (local/dev),
  * internal linkage (link/unlink a provider campaign to an internal marketing
    campaign, or a creative to internal content) — these touch OUR linkage
    tables only,
  * provider imports / metric refreshes, which READ from the provider and store
    the results locally without mutating provider state.

Tenant is always derived from auth; cross-tenant access resolves to 404.
``AdvertisingError`` is mapped to HTTP via ``to_http()``.

Structural reads, overview, performance, pacing, attribution, diagnostics,
freshness, anomalies, configuration and linkage are served by ``read_service``.
The provider-facing import / metric-refresh / reconciliation / recommendation
services are authored separately and imported defensively so the app boots even
before those modules land; endpoints that depend on an unavailable service
return a clean 503.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.advertising import (
    AccountCapabilityResponse,
    AccountListResponse,
    AdCampaignResponse,
    AdGroupListResponse,
    AdGroupResponse,
    AdListResponse,
    AdResponse,
    AdvertisingAccountResponse,
    AdvertisingAnomalyListResponse,
    AdvertisingAnomalyResponse,
    AdvertisingConfigurationResponse,
    AdvertisingFreshnessResponse,
    AdvertisingOverviewResponse,
    AdvertisingRecommendationListResponse,
    AttributionCoverageResponse,
    CampaignAttributionResponse,
    CampaignListResponse,
    CampaignPerformanceResponse,
    CreativeDiagnosticsResponse,
    CreativeListResponse,
    CreativeResponse,
    DeliveryDiagnosticsResponse,
    ImportRunResponse,
    LinkCampaignRequest,
    LinkContentRequest,
    LinkResponse,
    PacingResponse,
    ReconciliationResponse,
    RegisterMockAccountRequest,
)
from app.services.advertising_intelligence import read_service
from app.services.advertising_intelligence.errors import (
    AdProviderUnavailableError,
    AdvertisingError,
)
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/advertising", tags=["advertising"])


# ---------------------------------------------------------------------------
# Defensive service imports (provider-facing services authored separately)
# ---------------------------------------------------------------------------


def _optional_import(name: str):
    try:
        module = __import__(
            f"app.services.advertising_intelligence.{name}", fromlist=[name]
        )
        return module
    except Exception:  # noqa: BLE001 - not authored yet / import-time error
        return None


import_service = _optional_import("import_service")
metric_ingestion_service = _optional_import("metric_ingestion_service")
conversion_reconciliation = _optional_import("conversion_reconciliation")
recommendation_service = _optional_import("recommendation_service")


def _require_service(module, label: str):
    if module is None:
        raise AdProviderUnavailableError(
            f"The '{label}' service is not available yet.",
            details={"service": label},
        )
    return module


async def _guarded(coro, *, label: str):
    try:
        return await run_guarded(coro, label=label)
    except AdvertisingError as exc:
        raise exc.to_http() from exc


def _as_dict(result) -> dict:
    """Normalize a service result (dataclass / pydantic / ORM / dict) to a dict."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        try:
            return result.dict()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(result, "__dict__"):
        return {k: v for k, v in vars(result).items() if not k.startswith("_")}
    return dict(result)


def _import_run_dict(run, account_id: UUID, *, kind: str) -> dict:
    return {
        "import_run_id": getattr(run, "id", getattr(run, "import_run_id", account_id)),
        "account_id": getattr(run, "advertising_account_id", getattr(run, "account_id", account_id)),
        "provider": getattr(run, "provider", None),
        "kind": getattr(run, "kind", kind),
        "status": getattr(run, "status", "unknown"),
        "campaigns_imported": getattr(run, "campaigns_imported", getattr(run, "entities_created", 0)) or 0,
        "ad_groups_imported": getattr(run, "ad_groups_imported", 0) or 0,
        "ads_imported": getattr(run, "ads_imported", 0) or 0,
        "creatives_imported": getattr(run, "creatives_imported", 0) or 0,
        "metrics_updated": getattr(run, "metrics_updated", getattr(run, "snapshots_created", 0)) or 0,
        "failure_code": getattr(run, "failure_code", None),
        "requested_at": getattr(run, "requested_at", None),
        "completed_at": getattr(run, "completed_at", None),
        "read_only": True,
    }


# ===========================================================================
# Accounts
# ===========================================================================


@router.get("/accounts", response_model=AccountListResponse)
async def list_accounts_endpoint(
    provider: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await _guarded(
        read_service.list_accounts(
            db, user.tenant_id, provider=provider, status=status, limit=limit, offset=offset,
        ),
        label="advertising.list_accounts",
    )
    return AccountListResponse(
        items=[AdvertisingAccountResponse(**a) for a in items],
        total=total,
    )


@router.post("/accounts/register-mock", response_model=AdvertisingAccountResponse)
async def register_mock_account_endpoint(
    body: RegisterMockAccountRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a local/dev mock advertising account (tenant-scoped). Never
    contacts a live provider."""
    account = await _guarded(
        read_service.register_mock_account(
            db,
            user.tenant_id,
            provider=body.provider,
            name=body.name,
            currency=body.currency,
            timezone=body.timezone,
            external_account_id=body.external_account_id,
            created_by=user.id,
        ),
        label="advertising.register_mock_account",
    )
    await db.commit()
    return AdvertisingAccountResponse(**account)


@router.get("/accounts/{account_id}", response_model=AdvertisingAccountResponse)
async def get_account_endpoint(
    account_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    account = await _guarded(
        read_service.get_account(db, user.tenant_id, account_id),
        label="advertising.get_account",
    )
    return AdvertisingAccountResponse(**account)


@router.get("/accounts/{account_id}/capabilities", response_model=AccountCapabilityResponse)
async def get_account_capabilities_endpoint(
    account_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        read_service.account_capabilities(db, user.tenant_id, account_id),
        label="advertising.account_capabilities",
    )
    return AccountCapabilityResponse(**data)


@router.post("/accounts/{account_id}/import", response_model=ImportRunResponse)
async def import_account_endpoint(
    account_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """Import provider entities (campaigns/ad groups/ads/creatives). Reads from
    the provider only; provider state is never mutated."""
    await _guarded(
        read_service.get_account(db, user.tenant_id, account_id),
        label="advertising.import_account_exists",
    )
    svc = _require_service(import_service, "import_service")
    run = await _guarded(
        svc.import_account(db, user.tenant_id, account_id, requested_by=user.id),
        label="advertising.import_account",
    )
    await db.commit()
    return ImportRunResponse(**_import_run_dict(run, account_id, kind="import"))


@router.post("/accounts/{account_id}/refresh-metrics", response_model=ImportRunResponse)
async def refresh_account_metrics_endpoint(
    account_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """Refresh provider-reported metrics. Reads only; no provider mutation."""
    await _guarded(
        read_service.get_account(db, user.tenant_id, account_id),
        label="advertising.refresh_metrics_exists",
    )
    svc = _require_service(metric_ingestion_service, "metric_ingestion_service")
    run = await _guarded(
        svc.refresh_account_metrics(db, user.tenant_id, account_id, requested_by=user.id),
        label="advertising.refresh_account_metrics",
    )
    await db.commit()
    return ImportRunResponse(**_import_run_dict(run, account_id, kind="refresh_metrics"))


# ===========================================================================
# Campaigns
# ===========================================================================


@router.get("/campaigns", response_model=CampaignListResponse)
async def list_campaigns_endpoint(
    account_id: UUID | None = Query(None),
    status: str | None = Query(None),
    linked: bool | None = Query(None),
    marketing_campaign_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await _guarded(
        read_service.list_campaigns(
            db, user.tenant_id, account_id=account_id, status=status, linked=linked,
            marketing_campaign_id=marketing_campaign_id, limit=limit, offset=offset,
        ),
        label="advertising.list_campaigns",
    )
    return CampaignListResponse(
        items=[AdCampaignResponse(**c) for c in items],
        total=total,
    )


@router.get("/campaigns/{campaign_id}", response_model=AdCampaignResponse)
async def get_campaign_endpoint(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    campaign = await _guarded(
        read_service.get_campaign(db, user.tenant_id, campaign_id),
        label="advertising.get_campaign",
    )
    return AdCampaignResponse(**campaign)


@router.get("/campaigns/{campaign_id}/performance", response_model=CampaignPerformanceResponse)
async def get_campaign_performance_endpoint(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await _guarded(
        read_service.campaign_performance(db, user.tenant_id, campaign_id),
        label="advertising.campaign_performance",
    )
    return CampaignPerformanceResponse(**result)


@router.get("/campaigns/{campaign_id}/pacing", response_model=PacingResponse)
async def get_campaign_pacing_endpoint(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await _guarded(
        read_service.campaign_pacing(db, user.tenant_id, campaign_id),
        label="advertising.campaign_pacing",
    )
    return PacingResponse(**result)


@router.get("/campaigns/{campaign_id}/ad-groups", response_model=AdGroupListResponse)
async def list_campaign_ad_groups_endpoint(
    campaign_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await _guarded(
        read_service.get_campaign(db, user.tenant_id, campaign_id),
        label="advertising.ad_groups_campaign_exists",
    )
    items, total = await _guarded(
        read_service.list_ad_groups(
            db, user.tenant_id, campaign_id=campaign_id, limit=limit, offset=offset,
        ),
        label="advertising.list_ad_groups",
    )
    return AdGroupListResponse(
        items=[AdGroupResponse(**g) for g in items],
        total=total,
    )


@router.get("/campaigns/{campaign_id}/attribution", response_model=CampaignAttributionResponse)
async def get_campaign_attribution_endpoint(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await _guarded(
        read_service.campaign_attribution(db, user.tenant_id, campaign_id),
        label="advertising.campaign_attribution",
    )
    return CampaignAttributionResponse(**result)


@router.post("/campaigns/{campaign_id}/link", response_model=LinkResponse)
async def link_campaign_endpoint(
    campaign_id: UUID,
    body: LinkCampaignRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """Link a provider campaign to an internal marketing campaign. Mutates OUR
    linkage table only — never the provider."""
    result = await _guarded(
        read_service.link_campaign(
            db, user.tenant_id, campaign_id, body.internal_campaign_id, created_by=user.id,
        ),
        label="advertising.link_campaign",
    )
    await db.commit()
    return LinkResponse(**result)


@router.post("/campaigns/{campaign_id}/unlink", response_model=LinkResponse)
async def unlink_campaign_endpoint(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await _guarded(
        read_service.unlink_campaign(db, user.tenant_id, campaign_id),
        label="advertising.unlink_campaign",
    )
    await db.commit()
    return LinkResponse(**result)


# ===========================================================================
# Ad groups
# ===========================================================================


@router.get("/ad-groups/{ad_group_id}", response_model=AdGroupResponse)
async def get_ad_group_endpoint(
    ad_group_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    ad_group = await _guarded(
        read_service.get_ad_group(db, user.tenant_id, ad_group_id),
        label="advertising.get_ad_group",
    )
    return AdGroupResponse(**ad_group)


@router.get("/ad-groups/{ad_group_id}/ads", response_model=AdListResponse)
async def list_ad_group_ads_endpoint(
    ad_group_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await _guarded(
        read_service.get_ad_group(db, user.tenant_id, ad_group_id),
        label="advertising.ads_ad_group_exists",
    )
    items, total = await _guarded(
        read_service.list_ads(
            db, user.tenant_id, ad_group_id=ad_group_id, limit=limit, offset=offset,
        ),
        label="advertising.list_ads",
    )
    return AdListResponse(
        items=[AdResponse(**ad) for ad in items],
        total=total,
    )


@router.get("/ad-groups/{ad_group_id}/delivery", response_model=DeliveryDiagnosticsResponse)
async def get_ad_group_delivery_endpoint(
    ad_group_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await _guarded(
        read_service.ad_group_delivery(db, user.tenant_id, ad_group_id),
        label="advertising.ad_group_delivery",
    )
    return DeliveryDiagnosticsResponse(**result)


# ===========================================================================
# Ads
# ===========================================================================


@router.get("/ads/{ad_id}", response_model=AdResponse)
async def get_ad_endpoint(
    ad_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    ad = await _guarded(
        read_service.get_ad(db, user.tenant_id, ad_id),
        label="advertising.get_ad",
    )
    return AdResponse(**ad)


@router.get("/ads/{ad_id}/creative", response_model=CreativeResponse)
async def get_ad_creative_endpoint(
    ad_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    creative = await _guarded(
        read_service.get_creative_for_ad(db, user.tenant_id, ad_id),
        label="advertising.ad_creative",
    )
    return CreativeResponse(**creative)


# ===========================================================================
# Creatives
# ===========================================================================


@router.get("/creatives", response_model=CreativeListResponse)
async def list_creatives_endpoint(
    account_id: UUID | None = Query(None),
    fatigue_status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await _guarded(
        read_service.list_creatives(
            db, user.tenant_id, account_id=account_id, fatigue_status=fatigue_status,
            limit=limit, offset=offset,
        ),
        label="advertising.list_creatives",
    )
    return CreativeListResponse(
        items=[CreativeResponse(**c) for c in items],
        total=total,
    )


@router.get("/creatives/{creative_id}", response_model=CreativeResponse)
async def get_creative_endpoint(
    creative_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    creative = await _guarded(
        read_service.get_creative(db, user.tenant_id, creative_id),
        label="advertising.get_creative",
    )
    return CreativeResponse(**creative)


@router.get("/creatives/{creative_id}/diagnostics", response_model=CreativeDiagnosticsResponse)
async def get_creative_diagnostics_endpoint(
    creative_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await _guarded(
        read_service.creative_diagnostics(db, user.tenant_id, creative_id),
        label="advertising.creative_diagnostics",
    )
    return CreativeDiagnosticsResponse(**result)


@router.post("/creatives/{creative_id}/link-content", response_model=LinkResponse)
async def link_creative_content_endpoint(
    creative_id: UUID,
    body: LinkContentRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """Link a provider creative to internal content. Mutates OUR linkage table
    only — never the provider."""
    result = await _guarded(
        read_service.link_creative_content(
            db, user.tenant_id, creative_id, body.internal_content_id, created_by=user.id,
        ),
        label="advertising.link_creative_content",
    )
    await db.commit()
    return LinkResponse(**result)


@router.post("/creatives/{creative_id}/unlink-content", response_model=LinkResponse)
async def unlink_creative_content_endpoint(
    creative_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await _guarded(
        read_service.unlink_creative_content(db, user.tenant_id, creative_id),
        label="advertising.unlink_creative_content",
    )
    await db.commit()
    return LinkResponse(**result)


# ===========================================================================
# Overview / configuration / freshness / anomalies / providers
# ===========================================================================


@router.get("/overview", response_model=AdvertisingOverviewResponse)
async def get_overview_endpoint(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        read_service.advertising_overview(db, user.tenant_id),
        label="advertising.overview",
    )
    return AdvertisingOverviewResponse(**data)


@router.get("/configuration", response_model=AdvertisingConfigurationResponse)
async def get_configuration_endpoint(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    _ = user.tenant_id
    return AdvertisingConfigurationResponse(**read_service.configuration_payload())


@router.get("/providers", response_model=list[AccountCapabilityResponse])
async def get_providers_endpoint(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    _ = user.tenant_id
    return [AccountCapabilityResponse(**p) for p in read_service.provider_capabilities()]


@router.get("/freshness", response_model=AdvertisingFreshnessResponse)
async def get_freshness_endpoint(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        read_service.freshness_overview(db, user.tenant_id),
        label="advertising.freshness",
    )
    return AdvertisingFreshnessResponse(**data)


@router.get("/anomalies", response_model=AdvertisingAnomalyListResponse)
async def get_anomalies_endpoint(
    status: str | None = Query("open"),
    account_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await _guarded(
        read_service.list_anomalies(
            db, user.tenant_id, status=status, account_id=account_id, limit=limit, offset=offset,
        ),
        label="advertising.anomalies",
    )
    return AdvertisingAnomalyListResponse(
        items=[AdvertisingAnomalyResponse(**a) for a in items],
        total=total,
    )


# ===========================================================================
# Attribution / reconciliation / recommendations
# ===========================================================================


@router.get("/attribution", response_model=AttributionCoverageResponse)
async def get_attribution_coverage_endpoint(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        read_service.attribution_coverage(db, user.tenant_id),
        label="advertising.attribution_coverage",
    )
    return AttributionCoverageResponse(**data)


@router.get("/attribution/reconciliation", response_model=ReconciliationResponse)
async def get_attribution_reconciliation_endpoint(
    account_id: UUID | None = Query(None),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _require_service(conversion_reconciliation, "conversion_reconciliation")
    result = await _guarded(
        svc.reconcile(db, user.tenant_id, account_id=account_id),
        label="advertising.conversion_reconciliation",
    )
    return ReconciliationResponse(**_as_dict(result))


@router.get("/recommendations", response_model=AdvertisingRecommendationListResponse)
async def get_recommendations_endpoint(
    status: str | None = Query("open"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    svc = recommendation_service
    if svc is None or not hasattr(svc, "list_recommendations"):
        return AdvertisingRecommendationListResponse(items=[], total=0)
    items, total = await _guarded(
        svc.list_recommendations(
            db, user.tenant_id, status=status, limit=limit, offset=offset,
        ),
        label="advertising.recommendations",
    )
    return AdvertisingRecommendationListResponse(items=list(items), total=total)
