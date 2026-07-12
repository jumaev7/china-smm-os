from contextlib import asynccontextmanager
import logging
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy import func, select

from app.core.app_state import mark_app_started
from app.core.config import settings
from app.core.database import create_tables, AsyncSessionLocal, ensure_dev_schema_patches
from app.core.api_auth_context import ApiAuthMiddleware
from app.core.perf_middleware import RequestTimingMiddleware
from app.api.router import api_router
from app.api.public.review import router as public_review_router
from app.api.public.redirect import router as public_redirect_router
from app.api.public.landing import router as public_landing_router
from app.api.webhooks.whatsapp import router as whatsapp_webhook_router
from app.services.scheduled_publish_service import ScheduledPublishService
from app.services.health_snapshot_service import HealthSnapshotService
from app.services.schema_guard import SchemaGuard
from app.services.startup_health_service import StartupHealthService
from app.services.event_handlers.registration import register_event_bus_subscribers

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _log_database_target() -> None:
    raw = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(raw)
    logger.info(
        "[DB] DATABASE_URL target: host=%s port=%s db=%s user=%s",
        parsed.hostname or "unknown",
        parsed.port or 5432,
        (parsed.path or "").lstrip("/") or "unknown",
        parsed.username or "unknown",
    )


async def _log_startup_row_counts() -> None:
    from app.models.client import Client
    from app.models.content import ContentItem

    async with AsyncSessionLocal() as db:
        client_count = (await db.execute(select(func.count()).select_from(Client))).scalar()
        content_count = (await db.execute(select(func.count()).select_from(ContentItem))).scalar()
    logger.info("[DB] startup client count: %s", client_count)
    logger.info("[DB] startup content count: %s", content_count)


@asynccontextmanager
async def lifespan(app: FastAPI):
    mark_app_started()
    register_event_bus_subscribers()
    _log_database_target()
    # Create tables on startup (use Alembic in production)
    if settings.APP_ENV == "development":
        await create_tables()
        await ensure_dev_schema_patches()
        SchemaGuard.clear_cache()
        async with AsyncSessionLocal() as db:
            from app.services.sales_crm_seed import seed_sales_crm_demo
            from app.services.buyer_crm_seed import seed_buyer_crm_demo
            from app.services.business_matching_seed import seed_business_matching_demo
            await seed_sales_crm_demo(db)
            await seed_buyer_crm_demo(db)
            await seed_business_matching_demo(db)
    async with AsyncSessionLocal() as db:
        await StartupHealthService.run(db)
    await _log_startup_row_counts()
    # Ensure local media directory exists
    if not settings.USE_S3:
        Path(settings.MEDIA_LOCAL_PATH).mkdir(parents=True, exist_ok=True)
    await ScheduledPublishService.start()
    if settings.HEALTH_SNAPSHOT_ENABLED:
        await HealthSnapshotService.start()
    else:
        logger.info("[Health Snapshot] disabled (HEALTH_SNAPSHOT_ENABLED=false)")
    yield
    await HealthSnapshotService.stop()
    await ScheduledPublishService.stop()


app = FastAPI(
    title="China SMM OS",
    description="Internal AI assistant for managing social media of Chinese companies in Uzbekistan",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(ApiAuthMiddleware)
app.add_middleware(RequestTimingMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded media files locally
if not settings.USE_S3:
    media_path = Path(settings.MEDIA_LOCAL_PATH)
    media_path.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

# API routes
app.include_router(api_router)
app.include_router(whatsapp_webhook_router, prefix="/api/webhooks")
app.include_router(public_review_router, prefix="/public")
app.include_router(public_landing_router, prefix="/public")
app.include_router(public_redirect_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
