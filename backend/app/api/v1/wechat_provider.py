"""WeChat Provider v1 — provider registry and connection testing (no message sending)."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.wechat_provider import (
    WeChatProviderConfigurationsResponse,
    WeChatProviderHealthResponse,
    WeChatProviderRegisterRequest,
    WeChatProviderRegisterResponse,
    WeChatProviderTestConnectionRequest,
    WeChatProviderTestConnectionResponse,
    WeChatProvidersResponse,
)
from app.services.wechat_provider_service import WeChatProviderService

router = APIRouter(prefix="/wechat-provider", tags=["wechat-provider"])


@router.get("/providers", response_model=WeChatProvidersResponse)
async def list_providers(db: AsyncSession = Depends(get_db)):
    return await WeChatProviderService.list_providers(db)


@router.get("/configurations", response_model=WeChatProviderConfigurationsResponse)
async def list_configurations(
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await WeChatProviderService.list_configurations(db, tenant_id=tenant_id)


@router.get("/health", response_model=WeChatProviderHealthResponse)
async def provider_health(db: AsyncSession = Depends(get_db)):
    return await WeChatProviderService.provider_health(db)


@router.post("/test-connection", response_model=WeChatProviderTestConnectionResponse)
async def test_connection(
    body: WeChatProviderTestConnectionRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WeChatProviderService.test_connection(
            db,
            provider_id=body.provider_id,
            config_json=body.config_json,
        ),
        label="wechat_provider.test-connection",
    )


@router.post("/register-provider", response_model=WeChatProviderRegisterResponse)
async def register_provider(
    body: WeChatProviderRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WeChatProviderService.register_provider(
            db,
            provider_name=body.provider_name,
            provider_type=body.provider_type,
            tenant_id=body.tenant_id,
            config_json=body.config_json,
        ),
        label="wechat_provider.register-provider",
    )
