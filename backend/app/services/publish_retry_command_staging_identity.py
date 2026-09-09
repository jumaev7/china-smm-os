"""Staging identity guard for retry-command fake execution (Phase 3C.1C-D2-B2a).

Fake execution requires POSITIVE staging identity. All of the following must hold:

1. APP_ENV == \"staging\" exactly
2. PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND == \"fake\"
3. PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED == true
4. SELECT current_database() == china_smm_os_staging (authoritative)
5. Database name is NOT the production denylist entry china_smm_os

Hostname alone is never authoritative. Parsed DATABASE_URL may be used for
early preflight only — never as the sole identity proof.

This module does not create commands, evaluate eligibility, call executors,
or mutate business state. Successful verification returns an immutable
capability object required by staging fake factory / eligibility / fixtures.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Final, Iterable
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

REQUIRED_APP_ENV: Final[str] = "staging"
REQUIRED_BACKEND: Final[str] = "fake"
REQUIRED_DATABASE_NAME: Final[str] = "china_smm_os_staging"
PRODUCTION_DATABASE_DENYLIST: Final[frozenset[str]] = frozenset({"china_smm_os"})

# Provider secrets that must be empty when fake backend is requested.
PROVIDER_SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "TELEGRAM_BOT_TOKEN",
    "META_APP_SECRET",
)

# Soft-check only (documented limitation): S3/R2 creds may be shared locally.
S3_SOFT_CHECK_ENV_NAMES: Final[tuple[str, ...]] = (
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
)


class StagingIdentityError(RuntimeError):
    """Fail-closed staging identity / fake-execution denial."""

    def __init__(self, reason: str, *, detail: str | None = None) -> None:
        self.reason = reason
        self.detail = detail
        message = reason if detail is None else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class VerifiedRetryCommandStagingContext:
    """Immutable capability proving staging fake execution is authorized.

    Construction is restricted to ``RetryCommandStagingIdentityGuard``.
    Presence of this object is the only authority for staging fake factory,
    staging eligibility policy, and staging fixture builders.
    """

    app_env: str
    execution_backend: str
    fake_execution_allowed: bool
    current_database: str
    # Private capability token — not meaningful outside this module.
    _capability_token: str

    def __post_init__(self) -> None:
        if self._capability_token != _CAPABILITY_TOKEN:
            raise StagingIdentityError(
                "invalid_capability_token",
                detail="VerifiedRetryCommandStagingContext must come from the identity guard",
            )


# Opaque token minted only by the guard below.
_CAPABILITY_TOKEN: Final[str] = "retry-command-staging-capability-v1"


def parse_database_name_from_url(database_url: str | None) -> str | None:
    """Best-effort DATABASE_URL path parse for early preflight only.

    NOT authoritative. Prefer SELECT current_database() after connect.
    """
    if not database_url:
        return None
    raw = str(database_url).strip()
    if not raw:
        return None
    # SQLAlchemy URLs may use postgresql+asyncpg://…
    normalized = raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    normalized = normalized.replace("postgres+asyncpg://", "postgresql://", 1)
    try:
        parsed = urlparse(normalized)
    except Exception:  # noqa: BLE001
        return None
    path = (parsed.path or "").lstrip("/")
    if not path:
        return None
    # Drop query/options if present in path segment.
    return path.split("?", 1)[0].split("/", 1)[0] or None


def _normalize_app_env(raw: str | None) -> str:
    return str(raw or "").strip()


def _normalize_backend(raw: str | None) -> str:
    return str(raw or "").strip().lower()


def _is_populated_secret(value: Any) -> bool:
    if value is None:
        return False
    text_value = str(value).strip()
    if not text_value:
        return False
    # Treat obvious placeholders as empty for local examples.
    lowered = text_value.lower()
    if lowered in {"changeme", "change-me", "your-token", "xxx", "null", "none"}:
        return False
    return True


def collect_populated_provider_secrets(
    *,
    environ: dict[str, str] | None = None,
    settings_obj: Any | None = None,
) -> list[str]:
    """Return names of provider secrets that are unexpectedly populated.

    Never returns secret values — names only.
    """
    env = environ if environ is not None else os.environ
    cfg = settings_obj if settings_obj is not None else settings
    populated: list[str] = []
    for name in PROVIDER_SECRET_ENV_NAMES:
        settings_val = getattr(cfg, name, None)
        env_val = env.get(name)
        if _is_populated_secret(settings_val) or _is_populated_secret(env_val):
            populated.append(name)
    return populated


def collect_populated_s3_soft_secrets(
    *,
    environ: dict[str, str] | None = None,
    settings_obj: Any | None = None,
) -> list[str]:
    """Soft S3/R2 credential presence (names only). Not a hard failure alone."""
    env = environ if environ is not None else os.environ
    cfg = settings_obj if settings_obj is not None else settings
    populated: list[str] = []
    for name in S3_SOFT_CHECK_ENV_NAMES:
        settings_val = getattr(cfg, name, None)
        env_val = env.get(name)
        if _is_populated_secret(settings_val) or _is_populated_secret(env_val):
            populated.append(name)
    return populated


async def query_current_database(
    connectable: AsyncSession | AsyncConnection | AsyncEngine,
) -> str:
    """Authoritative DB identity: SELECT current_database()."""
    if isinstance(connectable, AsyncEngine):
        async with connectable.connect() as conn:
            result = await conn.execute(text("SELECT current_database()"))
            name = result.scalar_one()
    elif isinstance(connectable, AsyncConnection):
        result = await connectable.execute(text("SELECT current_database()"))
        name = result.scalar_one()
    else:
        result = await connectable.execute(text("SELECT current_database()"))
        name = result.scalar_one()
    return str(name)


class RetryCommandStagingIdentityGuard:
    """Verify staging identity and mint VerifiedRetryCommandStagingContext.

    Responsibilities only:
    - normalize/check APP_ENV
    - verify fake ack flag
    - verify requested execution backend
    - connect/query current_database()
    - production DB denylist
    - optional provider-secret absence validation
    """

    @classmethod
    def preflight_settings(
        cls,
        *,
        app_env: str | None = None,
        execution_backend: str | None = None,
        fake_execution_allowed: bool | None = None,
        database_url: str | None = None,
        require_backend_fake: bool = True,
        check_provider_secrets: bool = True,
        settings_obj: Any | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        """Early fail-closed checks BEFORE DB connect (URL parse is non-authoritative)."""
        cfg = settings_obj if settings_obj is not None else settings
        env_name = _normalize_app_env(
            app_env if app_env is not None else getattr(cfg, "APP_ENV", None),
        )
        backend = _normalize_backend(
            execution_backend
            if execution_backend is not None
            else getattr(cfg, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", None),
        )
        ack = (
            fake_execution_allowed
            if fake_execution_allowed is not None
            else bool(getattr(cfg, "PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED", False))
        )
        url = (
            database_url
            if database_url is not None
            else getattr(cfg, "DATABASE_URL", None)
        )

        if env_name != REQUIRED_APP_ENV:
            raise StagingIdentityError(
                "app_env_not_staging",
                detail=f"APP_ENV must be exactly {REQUIRED_APP_ENV!r}",
            )
        if require_backend_fake and backend != REQUIRED_BACKEND:
            raise StagingIdentityError(
                "backend_not_fake",
                detail=f"backend must be {REQUIRED_BACKEND!r} (got {backend!r})",
            )
        if not ack:
            raise StagingIdentityError(
                "fake_execution_ack_false",
                detail="PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED must be true",
            )

        parsed_name = parse_database_name_from_url(str(url) if url else None)
        if parsed_name in PRODUCTION_DATABASE_DENYLIST:
            raise StagingIdentityError(
                "database_url_production_denylist",
                detail=f"DATABASE_URL path names production DB {parsed_name!r}",
            )
        if parsed_name is not None and parsed_name != REQUIRED_DATABASE_NAME:
            # Early preflight only — authoritative check still requires current_database().
            raise StagingIdentityError(
                "database_url_not_staging",
                detail=(
                    f"DATABASE_URL path must be {REQUIRED_DATABASE_NAME!r} "
                    f"(got {parsed_name!r}; authoritative proof still requires "
                    "SELECT current_database())"
                ),
            )

        if check_provider_secrets:
            populated = collect_populated_provider_secrets(
                environ=environ,
                settings_obj=cfg,
            )
            if populated:
                raise StagingIdentityError(
                    "provider_secrets_populated",
                    detail=(
                        "Refuse fake execution while provider secrets are set: "
                        + ", ".join(populated)
                    ),
                )
            soft = collect_populated_s3_soft_secrets(
                environ=environ,
                settings_obj=cfg,
            )
            if soft:
                logger.warning(
                    "[RetryCommandStagingIdentity] S3/R2 credential env vars are "
                    "populated (%s); hard-fail limited to provider secrets "
                    "(TELEGRAM_BOT_TOKEN, META_APP_SECRET). Verify this is not "
                    ".env.production.",
                    ", ".join(soft),
                )

    @classmethod
    async def verify(
        cls,
        connectable: AsyncSession | AsyncConnection | AsyncEngine,
        *,
        app_env: str | None = None,
        execution_backend: str | None = None,
        fake_execution_allowed: bool | None = None,
        database_url: str | None = None,
        require_backend_fake: bool = True,
        check_provider_secrets: bool = True,
        settings_obj: Any | None = None,
        environ: dict[str, str] | None = None,
        skip_url_preflight: bool = False,
    ) -> VerifiedRetryCommandStagingContext:
        """Authoritative staging identity verification.

        Returns VerifiedRetryCommandStagingContext on success; raises
        StagingIdentityError on any mismatch (fail closed).
        """
        cfg = settings_obj if settings_obj is not None else settings
        if not skip_url_preflight:
            cls.preflight_settings(
                app_env=app_env,
                execution_backend=execution_backend,
                fake_execution_allowed=fake_execution_allowed,
                database_url=database_url,
                require_backend_fake=require_backend_fake,
                check_provider_secrets=check_provider_secrets,
                settings_obj=cfg,
                environ=environ,
            )
        else:
            # Still enforce env/ack/backend/secrets without URL parse.
            cls.preflight_settings(
                app_env=app_env,
                execution_backend=execution_backend,
                fake_execution_allowed=fake_execution_allowed,
                database_url=f"postgresql://local/{REQUIRED_DATABASE_NAME}",
                require_backend_fake=require_backend_fake,
                check_provider_secrets=check_provider_secrets,
                settings_obj=cfg,
                environ=environ,
            )

        env_name = _normalize_app_env(
            app_env if app_env is not None else getattr(cfg, "APP_ENV", None),
        )
        backend = _normalize_backend(
            execution_backend
            if execution_backend is not None
            else getattr(cfg, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", None),
        )
        ack = (
            fake_execution_allowed
            if fake_execution_allowed is not None
            else bool(getattr(cfg, "PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED", False))
        )

        # Wrong APP_ENV with staging DB must still fail (defense in depth).
        if env_name != REQUIRED_APP_ENV:
            raise StagingIdentityError("app_env_not_staging")

        current_db = await query_current_database(connectable)
        if current_db in PRODUCTION_DATABASE_DENYLIST:
            raise StagingIdentityError(
                "current_database_production_denylist",
                detail=f"current_database()={current_db!r}",
            )
        if current_db != REQUIRED_DATABASE_NAME:
            raise StagingIdentityError(
                "current_database_not_staging",
                detail=(
                    f"expected {REQUIRED_DATABASE_NAME!r}, "
                    f"got current_database()={current_db!r}"
                ),
            )

        if require_backend_fake and backend != REQUIRED_BACKEND:
            raise StagingIdentityError("backend_not_fake")
        if not ack:
            raise StagingIdentityError("fake_execution_ack_false")

        return VerifiedRetryCommandStagingContext(
            app_env=env_name,
            execution_backend=backend,
            fake_execution_allowed=True,
            current_database=current_db,
            _capability_token=_CAPABILITY_TOKEN,
        )


def assert_verified_staging_context(
    context: Any,
    *,
    what: str = "staging operation",
) -> VerifiedRetryCommandStagingContext:
    """Type/capability gate used by factories and policies."""
    if not isinstance(context, VerifiedRetryCommandStagingContext):
        raise StagingIdentityError(
            "missing_staging_capability",
            detail=f"{what} requires VerifiedRetryCommandStagingContext",
        )
    if context._capability_token != _CAPABILITY_TOKEN:
        raise StagingIdentityError("invalid_capability_token")
    if context.app_env != REQUIRED_APP_ENV:
        raise StagingIdentityError("app_env_not_staging")
    if context.current_database != REQUIRED_DATABASE_NAME:
        raise StagingIdentityError("current_database_not_staging")
    if context.current_database in PRODUCTION_DATABASE_DENYLIST:
        raise StagingIdentityError("current_database_production_denylist")
    if not context.fake_execution_allowed:
        raise StagingIdentityError("fake_execution_ack_false")
    return context
