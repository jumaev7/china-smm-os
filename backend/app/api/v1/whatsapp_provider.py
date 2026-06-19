"""WhatsApp Provider v1 — provider registry and connection testing (no message sending)."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.whatsapp_provider import (
    WhatsAppProviderConfigurationsResponse,
    WhatsAppProviderHealthResponse,
    WhatsAppProviderRegisterRequest,
    WhatsAppProviderRegisterResponse,
    WhatsAppProviderTestConnectionRequest,
    WhatsAppProviderTestConnectionResponse,
    WhatsAppProvidersResponse,
)
from app.services.whatsapp_provider_service import WhatsAppProviderService

router = APIRouter(prefix="/whatsapp-provider", tags=["whatsapp-provider"])


@router.get("/providers", response_model=WhatsAppProvidersResponse)
async def list_providers(db: AsyncSession = Depends(get_db)):
    return await WhatsAppProviderService.list_providers(db)


@router.get("/configurations", response_model=WhatsAppProviderConfigurationsResponse)
async def list_configurations(
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await WhatsAppProviderService.list_configurations(db, tenant_id=tenant_id)


@router.get("/health", response_model=WhatsAppProviderHealthResponse)
async def provider_health(db: AsyncSession = Depends(get_db)):
    return await WhatsAppProviderService.provider_health(db)


@router.post("/test-connection", response_model=WhatsAppProviderTestConnectionResponse)
async def test_connection(
    body: WhatsAppProviderTestConnectionRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WhatsAppProviderService.test_connection(
            db,
            provider_id=body.provider_id,
            config_json=body.config_json,
        ),
        label="whatsapp_provider.test-connection",
    )


@router.post("/register-provider", response_model=WhatsAppProviderRegisterResponse)
async def register_provider(
    body: WhatsAppProviderRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WhatsAppProviderService.register_provider(
            db,
            provider_name=body.provider_name,
            provider_type=body.provider_type,
            tenant_id=body.tenant_id,
            phone_number=body.phone_number,
            business_account_id=body.business_account_id,
            config_json=body.config_json,
        ),
        label="whatsapp_provider.register-provider",
    )
