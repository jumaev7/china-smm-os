"""Tenant Authentication v1 — login, session, demo user."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.tenant_access import get_current_tenant_user
from app.schemas.auth import (
    AuthDemoUserResponse,
    AuthLoginRequest,
    AuthLoginResponse,
    AuthLogoutResponse,
    AuthMeResponse,
    AuthRefreshRequest,
    AuthRefreshResponse,
)
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthLoginResponse)
async def auth_login(body: AuthLoginRequest, db: AsyncSession = Depends(get_db)):
    return await TenantAuthService.login(db, email=body.email, password=body.password)


@router.post("/logout", response_model=AuthLogoutResponse)
async def auth_logout(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await TenantAuthService.logout(db, user)


@router.get("/me", response_model=AuthMeResponse)
async def auth_me(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await TenantAuthService.me(db, user)


@router.post("/refresh", response_model=AuthRefreshResponse)
async def auth_refresh(body: AuthRefreshRequest, db: AsyncSession = Depends(get_db)):
    return await TenantAuthService.refresh_session(db, body.refresh_token)


@router.post("/create-demo-user", response_model=AuthDemoUserResponse)
async def auth_create_demo_user(db: AsyncSession = Depends(get_db)):
    if settings.APP_ENV not in ("development", "test"):
        raise HTTPException(
            status_code=403,
            detail="Demo user bootstrap disabled — only available when APP_ENV=development or test",
        )
    return await TenantAuthService.create_demo_user(db)
