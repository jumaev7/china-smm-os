from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/china_smm_os"
    DB_POOL_SIZE: int = 15
    DB_MAX_OVERFLOW: int = 15
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    # Cap concurrent nested ASGI health probes (each probe opens its own DB session).
    DB_PROBE_CONCURRENCY: int = 4
    # Background health snapshots probe dozens of routes — opt in outside local/dev.
    HEALTH_SNAPSHOT_ENABLED: bool = False
    # Pilot readiness route probes spawn nested API calls; keep them off locally unless explicit.
    ROUTE_PROBING_ENABLED: bool = False

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    # Storage
    USE_S3: bool = False
    MEDIA_LOCAL_PATH: str = "./media_storage"
    # Base URL used to build media URLs returned to the frontend.
    # In Docker, set to http://localhost:8000 (or your public domain).
    MEDIA_BASE_URL: str = "http://localhost:8000"
    S3_BUCKET: str = "china-smm-os"
    S3_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""

    # App
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me"
    ADMIN_SECRET_KEY: str = ""
    TENANT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ADMIN_LOGIN_RATE_MAX_ATTEMPTS: int = 10
    ADMIN_LOGIN_RATE_WINDOW_SEC: int = 900
    ADMIN_LOGIN_LOCKOUT_THRESHOLD: int = 5
    ADMIN_LOGIN_LOCKOUT_MINUTES: int = 15
    CORS_ORIGINS: str = "http://localhost:3000"
    # Set DEMO_MODE=true to test AI generation flow without a real OpenAI key.
    # Returns realistic placeholder captions. Never use in production.
    DEMO_MODE: bool = False

    # Telegram Bot Integration
    # Get token from @BotFather. Set TELEGRAM_ADMIN_ID to your Telegram user ID
    # (get it from @userinfobot) to restrict who can send content.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_ID: str = ""  # comma-separated user IDs, empty = accept all
    # When True, Telegram groups without explicit workflow_mode use admin_controlled_buffer
    TELEGRAM_GROUP_DEFAULT_BUFFER: bool = True
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_INGESTION_ENABLED: bool = True
    # Base URL for client-facing review links (frontend origin)
    PUBLIC_APP_URL: str = "http://localhost:3000"

    # Scheduled auto-publish worker
    SCHEDULED_PUBLISH_ENABLED: bool = True
    # Durable automation scheduler worker (separate process)
    AUTOMATION_SCHEDULER_ENABLED: bool = True
    AUTOMATION_SCHEDULER_POLL_SECONDS: float = 2.0
    AUTOMATION_SCHEDULER_BATCH_SIZE: int = 10
    AUTOMATION_SCHEDULER_LEASE_SECONDS: int = 300
    # Timezone label for Telegram client-review preview schedule line
    # Admin bootstrap (development only — no default credentials in code)
    ADMIN_BOOTSTRAP_EMAIL: str = ""
    ADMIN_BOOTSTRAP_PASSWORD: str = ""

    # WhatsApp Business API (Meta Cloud API) — optional; demo mode works without credentials
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = ""
    WHATSAPP_APP_SECRET: str = ""

    # Meta Graph API — Facebook Login + Instagram Business (publishing connection)
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/publishing/meta/oauth/callback"
    META_GRAPH_API_VERSION: str = "v21.0"
    META_OAUTH_SCOPES: str = (
        "pages_show_list,pages_read_engagement,instagram_basic,business_management,"
        "pages_manage_posts,instagram_content_publish"
    )
    # Opt-in gate for real Facebook Page posts (verification smoke + manual live tests).
    ENABLE_FACEBOOK_LIVE_SMOKE: bool = False

    @property
    def admin_secret_key(self) -> str:
        return self.ADMIN_SECRET_KEY or self.SECRET_KEY

    @property
    def tenant_secret_key(self) -> str:
        return self.TENANT_SECRET_KEY or self.SECRET_KEY

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
