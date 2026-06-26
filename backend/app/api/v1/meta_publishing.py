from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.publishing import (
    MetaConnectionHealthResponse,
    MetaConnectionSummaryResponse,
    MetaOAuthStartResponse,
    MetaRefreshResponse,
    MetaDisconnectResponse,
)
from app.services.meta_connection_service import MetaConnectionService
from app.services.meta_oauth_service import MetaOAuthService

router = APIRouter(prefix="/publishing/meta", tags=["meta-publishing"])


@router.get("/oauth/start", response_model=MetaOAuthStartResponse)
async def meta_oauth_start():
    """Return Meta OAuth authorize URL (Facebook Login for Pages + Instagram Business)."""
    return MetaOAuthService.start_oauth()


@router.get("/oauth/callback")
async def meta_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """OAuth redirect handler — exchanges code, stores tokens, redirects to admin UI."""
    try:
        await MetaOAuthService.handle_callback(
            db,
            code=code,
            state=state,
            error=error,
            error_description=error_description,
        )
        return RedirectResponse(MetaOAuthService.frontend_redirect_url(success=True))
    except Exception as exc:
        message = getattr(exc, "detail", None) or str(exc)
        if isinstance(message, dict):
            message = message.get("message") or str(message)
        return RedirectResponse(MetaOAuthService.frontend_redirect_url(success=False, message=str(message)))


@router.post("/oauth/demo-connect", response_model=MetaConnectionSummaryResponse)
async def meta_oauth_demo_connect(db: AsyncSession = Depends(get_db)):
    """Demo-only Meta connect when OAuth credentials are not configured."""
    await MetaOAuthService.demo_connect(db)
    return await MetaConnectionService.get_connection_summary(db)


@router.get("/connection", response_model=MetaConnectionSummaryResponse)
async def meta_connection_summary(db: AsyncSession = Depends(get_db)):
    """Connected Meta account summary — health, permissions, token expiry (no secrets)."""
    return await MetaConnectionService.get_connection_summary(db)


@router.get("/health", response_model=MetaConnectionHealthResponse)
async def meta_connection_health(db: AsyncSession = Depends(get_db)):
    """Live token + permission health for connected Meta accounts."""
    summary = await MetaConnectionService.get_connection_summary(db)
    return {
        "oauth_configured": summary["oauth_configured"],
        "connected": summary["connected"],
        "health": summary["health"],
        "token_expired": summary["token_expired"],
        "expires_at": summary["expires_at"],
        "permissions": summary["permissions"],
        "missing_permissions": summary["missing_permissions"],
        "facebook": summary["facebook"],
        "instagram": summary["instagram"],
        "blockers": summary["blockers"],
        "publish_implementation": summary["publish_implementation"],
    }


@router.post("/refresh", response_model=MetaRefreshResponse)
async def meta_refresh_tokens(db: AsyncSession = Depends(get_db)):
    """Refresh Meta long-lived user token and page access token."""
    return await MetaConnectionService.refresh_tokens(db)


@router.post("/disconnect", response_model=MetaDisconnectResponse)
async def meta_disconnect(db: AsyncSession = Depends(get_db)):
    """Disconnect Meta — clears stored tokens and marks accounts disconnected."""
    return await MetaConnectionService.disconnect(db)
