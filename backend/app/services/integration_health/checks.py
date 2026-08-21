"""Read-only provider health evaluators (no mutations)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.advertising import TenantAdvertisingAccount
from app.models.client import Client
from app.models.listening import TenantListeningSource
from app.models.publishing_account import PublishingAccount
from app.models.telegram_ingestion import TelegramWebhookEvent
from app.services.integration_health.taxonomy import (
    REASON_ACCOUNT_NOT_FOUND,
    REASON_APP_REVIEW_REQUIRED,
    REASON_AUTHORIZATION_REQUIRED,
    REASON_CAPABILITY_UNAVAILABLE,
    REASON_DISCONNECTED,
    REASON_EXPIRED_TOKEN,
    REASON_HEALTHY,
    REASON_INVALID_TOKEN,
    REASON_MISSING_OPTIONAL_SCOPE,
    REASON_MISSING_REQUIRED_SCOPE,
    REASON_MOCK_MODE,
    REASON_NEVER_CHECKED,
    REASON_NOT_CONFIGURED,
    REASON_PROVIDER_RATE_LIMITED,
    REASON_PROVIDER_UNREACHABLE,
    REASON_TRANSIENT_PROVIDER_ERROR,
    REASON_UNKNOWN,
    REASON_UNSUPPORTED,
    REASON_WEBHOOK_NOT_CONFIGURED,
    REASON_WEBHOOK_UNHEALTHY,
    STALE_AFTER_ADS_SECONDS,
    STALE_AFTER_LISTENING_SECONDS,
    STALE_AFTER_LOCAL_SECONDS,
    STALE_AFTER_REMOTE_SECONDS,
    STALE_AFTER_TELEGRAM_SECONDS,
    TRANSIENT_ESCALATION_THRESHOLD,
    TRANSIENT_WINDOW_SECONDS,
    map_account_status_to_reason,
    reason_meta,
)
from app.services.integration_health.types import CapabilityHealth, IntegrationHealthResult
from app.services.meta_graph_client import (
    LISTENING_FACEBOOK_READ_PERMISSIONS,
    MetaGraphError,
    debug_token,
    missing_connection_permissions,
    missing_facebook_publish_permissions,
    missing_instagram_publish_permissions,
    meta_oauth_configured,
    token_is_expired,
)
from app.utils.token_vault import decrypt_token

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _loads_permissions(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        import json
        data = json.loads(raw)
        return list(data) if isinstance(data, list) else []
    except Exception:
        return []


def _loads_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        import json
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _build_result(
    *,
    integration_id: str,
    platform: str,
    provider: str,
    tenant_id: UUID | None,
    client_id: UUID | None,
    account_name: str | None,
    reason_code: str,
    checked_at: datetime | None,
    last_success_at: datetime | None,
    stale_after_seconds: int,
    capabilities: list[CapabilityHealth] | None = None,
    source: str = "local",
    never_checked: bool = False,
    transient_failure_count: int = 0,
    status_override: str | None = None,
    severity_override: str | None = None,
    requires_action_override: bool | None = None,
    responsible_override: str | None = None,
    reason_override: str | None = None,
    next_step_override: str | None = None,
    deep_link: str | None = None,
) -> IntegrationHealthResult:
    meta = reason_meta(reason_code)
    status = status_override or meta["status"]
    now = _utc_now()
    stale = checked_at is None or (now - (
        checked_at if checked_at.tzinfo else checked_at.replace(tzinfo=timezone.utc)
    )).total_seconds() > stale_after_seconds

    # Never pretend healthy without a check, or when stale with prior healthy claim.
    if never_checked and status == "healthy":
        status = "unknown"
        reason_code = REASON_NEVER_CHECKED
        meta = reason_meta(reason_code)
    if stale and status == "healthy":
        status = "unknown"
        reason_code = REASON_NEVER_CHECKED if checked_at is None else "stale_check"
        meta = reason_meta(reason_code if reason_code != "stale_check" else "stale_check")

    return IntegrationHealthResult(
        integration_id=integration_id,
        platform=platform,
        provider=provider,
        tenant_id=str(tenant_id) if tenant_id else None,
        client_id=str(client_id) if client_id else None,
        account_name=account_name,
        status=status_override or status,
        severity=severity_override or meta["severity"],
        reason_code=reason_code,
        reason=reason_override or meta["explanation"],
        checked_at=checked_at,
        last_success_at=last_success_at,
        stale_after_seconds=stale_after_seconds,
        stale=stale,
        requires_operator_action=(
            requires_action_override
            if requires_action_override is not None
            else bool(meta["requires_operator_action"])
        ),
        responsible_party=responsible_override or meta["responsible_party"],
        recommended_next_step=next_step_override or meta["recommended_next_step"],
        deep_link=deep_link or f"/integrations?platform={platform}",
        capabilities=capabilities or [],
        source=source,
        never_checked=never_checked,
        transient_failure_count=transient_failure_count,
        safe_auto_recheck=bool(meta["safe_auto_recheck"]),
    )


async def evaluate_meta_account(
    account: PublishingAccount,
    *,
    live_check: bool,
    prior_diag: dict[str, Any] | None = None,
) -> IntegrationHealthResult:
    """Evaluate Facebook/Instagram publishing + listening capability health."""
    prior_diag = prior_diag or {}
    now = _utc_now()
    permissions = _loads_permissions(account.permissions_json)
    metadata = _loads_meta(account.account_metadata_json)
    is_demo = bool(metadata.get("demo"))
    expired = token_is_expired(account.expires_at)
    platform = account.platform
    provider = "meta"

    publish_missing = (
        missing_facebook_publish_permissions(permissions)
        if platform == "facebook"
        else missing_instagram_publish_permissions(permissions)
    )
    connection_missing = missing_connection_permissions(permissions)
    listening_missing = sorted(LISTENING_FACEBOOK_READ_PERMISSIONS - set(permissions))

    has_page = bool(account.facebook_page_id) if platform == "facebook" else True
    if platform == "instagram" and not account.instagram_business_account_id:
        has_page = False

    token_present = bool(account.access_token_encrypted)
    token_valid = token_present
    provider_error_class: str | None = None
    remote_ran = False
    transient = False

    if account.status == "disconnected":
        reason = REASON_DISCONNECTED
    elif account.status == "mock" or is_demo:
        reason = REASON_MOCK_MODE
    elif expired:
        reason = REASON_EXPIRED_TOKEN
        token_valid = False
    elif not token_present:
        reason = REASON_AUTHORIZATION_REQUIRED if account.status != "connected" else REASON_INVALID_TOKEN
    elif not has_page:
        reason = REASON_ACCOUNT_NOT_FOUND
    elif connection_missing or publish_missing:
        reason = REASON_MISSING_REQUIRED_SCOPE
    else:
        reason = REASON_HEALTHY

    # Live read-only probe (debug_token only).
    if (
        live_check
        and token_present
        and meta_oauth_configured()
        and not expired
        and not is_demo
        and account.status != "disconnected"
    ):
        remote_ran = True
        try:
            token = decrypt_token(account.access_token_encrypted or "")
            debug_data = await debug_token(token)
            if not debug_data.get("is_valid"):
                token_valid = False
                reason = REASON_INVALID_TOKEN
            else:
                live_perms = debug_data.get("scopes") or []
                if isinstance(live_perms, list) and live_perms:
                    permissions = sorted({str(p) for p in live_perms if p})
                    publish_missing = (
                        missing_facebook_publish_permissions(permissions)
                        if platform == "facebook"
                        else missing_instagram_publish_permissions(permissions)
                    )
                    connection_missing = missing_connection_permissions(permissions)
                    listening_missing = sorted(
                        LISTENING_FACEBOOK_READ_PERMISSIONS - set(permissions)
                    )
                    if connection_missing or publish_missing:
                        reason = REASON_MISSING_REQUIRED_SCOPE
                    elif reason == REASON_HEALTHY:
                        reason = REASON_HEALTHY
        except MetaGraphError as exc:
            provider_error_class = "meta_graph"
            if exc.status_code == 429 or exc.error_code in {4, 17, 32, 613}:
                reason = REASON_PROVIDER_RATE_LIMITED
                transient = True
            elif exc.is_timeout or exc.is_connection_error or exc.is_transient:
                reason = REASON_TRANSIENT_PROVIDER_ERROR
                transient = True
            else:
                reason = REASON_PROVIDER_UNREACHABLE
                transient = True
            logger.info(
                "Meta health probe classified reason=%s code=%s status=%s",
                reason,
                exc.error_code,
                exc.status_code,
            )
        except Exception as exc:
            provider_error_class = "unexpected"
            reason = REASON_TRANSIENT_PROVIDER_ERROR
            transient = True
            logger.warning("Meta health probe failed: %s", type(exc).__name__)

    # Capability split: publishing vs listening.
    if reason in (REASON_DISCONNECTED, REASON_EXPIRED_TOKEN, REASON_INVALID_TOKEN, REASON_AUTHORIZATION_REQUIRED):
        pub_cap = CapabilityHealth(
            name="publishing",
            status=reason_meta(reason)["status"],
            reason_code=reason,
            reason=reason_meta(reason)["explanation"],
            requires_operator_action=True,
        )
        listen_cap = CapabilityHealth(
            name="listening",
            status=reason_meta(reason)["status"],
            reason_code=reason,
            reason=reason_meta(reason)["explanation"],
            requires_operator_action=True,
        )
    elif reason == REASON_MOCK_MODE:
        pub_cap = CapabilityHealth(
            name="publishing",
            status="degraded",
            reason_code=REASON_MOCK_MODE,
            reason="Mock/demo publishing mode",
        )
        listen_cap = CapabilityHealth(
            name="listening",
            status="unknown",
            reason_code=REASON_UNSUPPORTED,
            reason="Listening not available in mock mode",
        )
    else:
        if publish_missing or connection_missing:
            pub_cap = CapabilityHealth(
                name="publishing",
                status="action_required",
                reason_code=REASON_MISSING_REQUIRED_SCOPE,
                reason=f"Missing required publish permissions: {', '.join(publish_missing or connection_missing)}",
                requires_operator_action=True,
            )
        elif not has_page:
            pub_cap = CapabilityHealth(
                name="publishing",
                status="action_required",
                reason_code=REASON_ACCOUNT_NOT_FOUND,
                reason="Page or Instagram Business account not linked",
                requires_operator_action=True,
            )
        elif reason in (REASON_TRANSIENT_PROVIDER_ERROR, REASON_PROVIDER_RATE_LIMITED, REASON_PROVIDER_UNREACHABLE):
            pub_cap = CapabilityHealth(
                name="publishing",
                status="degraded",
                reason_code=reason,
                reason=reason_meta(reason)["explanation"],
            )
        else:
            pub_cap = CapabilityHealth(
                name="publishing",
                status="healthy",
                reason_code=REASON_HEALTHY,
                reason="Publishing connection operational",
            )

        if listening_missing:
            listen_cap = CapabilityHealth(
                name="listening",
                status="action_required",
                reason_code=REASON_MISSING_OPTIONAL_SCOPE,
                reason=f"Missing Listening permissions: {', '.join(listening_missing)}",
                requires_operator_action=True,
            )
            # App Review note when scopes look granted but production may still need review —
            # we signal app_review when connection is otherwise healthy and listening scopes missing
            # is the only gap; if scopes are present we still note App Review may apply.
        else:
            listen_cap = CapabilityHealth(
                name="listening",
                status="degraded",
                reason_code=REASON_APP_REVIEW_REQUIRED,
                reason=(
                    "Listening scopes present; production Live mode may still require "
                    "Meta App Review / Advanced Access"
                ),
                requires_operator_action=True,
            )
            # If we have no evidence scopes are granted for listening endpoints in live mode,
            # keep degraded rather than claiming healthy.
            if not listening_missing and pub_cap.status == "healthy":
                # Prefer honest degraded for App Review uncertainty over false healthy.
                pass

        # Overall: do NOT mark whole integration broken for optional listening gap.
        if pub_cap.status == "healthy" and listen_cap.reason_code in (
            REASON_MISSING_OPTIONAL_SCOPE,
            REASON_APP_REVIEW_REQUIRED,
        ):
            if reason == REASON_HEALTHY:
                reason = REASON_MISSING_OPTIONAL_SCOPE if listening_missing else REASON_APP_REVIEW_REQUIRED

    # Transient suppression/escalation against prior diagnostic.
    transient_count = int(prior_diag.get("transient_failure_count") or 0)
    escalated = bool(prior_diag.get("escalated"))
    status_override = None
    requires_action_override = None
    responsible_override = None
    severity_override = None

    if transient:
        from app.services.integration_health.persistence import apply_transient_failure

        updated = apply_transient_failure(
            prior_diag,
            now=now,
            window_seconds=TRANSIENT_WINDOW_SECONDS,
            threshold=TRANSIENT_ESCALATION_THRESHOLD,
        )
        transient_count = int(updated["transient_failure_count"])
        escalated = bool(updated.get("escalated"))
        if not escalated:
            status_override = "degraded"
            requires_action_override = False
            responsible_override = "system"
            severity_override = "low"
        else:
            status_override = "unavailable"
            requires_action_override = False
            responsible_override = "provider"
            severity_override = "medium"
    elif reason == REASON_HEALTHY or (
        pub_cap.status == "healthy" and reason in (REASON_MISSING_OPTIONAL_SCOPE, REASON_APP_REVIEW_REQUIRED)
    ):
        transient_count = 0
        escalated = False

    last_success = None
    if reason in (REASON_HEALTHY, REASON_MISSING_OPTIONAL_SCOPE, REASON_APP_REVIEW_REQUIRED, REASON_MOCK_MODE):
        last_success = now if remote_ran or not live_check else _parse_prior_success(prior_diag)
        if live_check and not transient:
            last_success = now
    else:
        last_success = _parse_prior_success(prior_diag)

    result = _build_result(
        integration_id=str(account.id),
        platform=platform,
        provider=provider,
        tenant_id=account.tenant_id,
        client_id=None,
        account_name=account.account_name,
        reason_code=reason,
        checked_at=now if (live_check or not prior_diag.get("checked_at")) else _parse_prior_checked(prior_diag) or now,
        last_success_at=last_success,
        stale_after_seconds=STALE_AFTER_REMOTE_SECONDS if remote_ran else STALE_AFTER_LOCAL_SECONDS,
        capabilities=[pub_cap, listen_cap],
        source="remote" if remote_ran else "local",
        never_checked=False,
        transient_failure_count=transient_count,
        status_override=status_override,
        severity_override=severity_override,
        requires_action_override=requires_action_override,
        responsible_override=responsible_override,
        deep_link=f"/integrations?platform={platform}",
    )
    result.diagnostic = {
        "provider_error_class": provider_error_class,
        "escalated": escalated,
        "publish_missing": publish_missing,
        "listening_missing": listening_missing,
        "token_valid": token_valid,
    }
    return result


def _parse_prior_checked(diag: dict[str, Any]) -> datetime | None:
    raw = diag.get("checked_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_prior_success(diag: dict[str, Any]) -> datetime | None:
    raw = diag.get("last_success_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def evaluate_generic_publishing_account(
    account: PublishingAccount,
    *,
    prior_diag: dict[str, Any] | None = None,
) -> IntegrationHealthResult:
    """Local-only evaluation for telegram/tiktok/linkedin publishing rows."""
    prior_diag = prior_diag or {}
    now = _utc_now()
    reason = map_account_status_to_reason(account.status)
    never_checked = not prior_diag.get("checked_at") and account.platform != "telegram"

    # LinkedIn/TikTok: no live probe → unsupported remote health.
    if account.platform in ("linkedin", "tiktok") and account.status == "connected":
        reason = REASON_UNSUPPORTED
        caps = [
            CapabilityHealth(
                name="publishing",
                status="unknown",
                reason_code=REASON_UNSUPPORTED,
                reason="Live health probing not available for this platform yet",
            )
        ]
    else:
        caps = [
            CapabilityHealth(
                name="publishing",
                status=reason_meta(reason)["status"],
                reason_code=reason,
                reason=reason_meta(reason)["explanation"],
                requires_operator_action=bool(reason_meta(reason)["requires_operator_action"]),
            )
        ]

    return _build_result(
        integration_id=str(account.id),
        platform=account.platform,
        provider=account.platform,
        tenant_id=account.tenant_id,
        client_id=None,
        account_name=account.account_name,
        reason_code=reason,
        checked_at=now,
        last_success_at=now if reason == REASON_HEALTHY else _parse_prior_success(prior_diag),
        stale_after_seconds=STALE_AFTER_LOCAL_SECONDS,
        capabilities=caps,
        source="local",
        never_checked=never_checked and reason not in (REASON_DISCONNECTED, REASON_EXPIRED_TOKEN),
    )


async def evaluate_telegram_tenant(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    live_webhook: bool = False,
) -> list[IntegrationHealthResult]:
    """Telegram health from client associations + optional getWebhookInfo (read-only)."""
    now = _utc_now()
    results: list[IntegrationHealthResult] = []

    clients = list(
        (
            await db.scalars(
                select(Client).where(Client.tenant_id == tenant_id).order_by(Client.company_name)
            )
        ).all()
    )

    bot_configured = bool((settings.TELEGRAM_BOT_TOKEN or "").strip())
    webhook_url = None
    webhook_error = None
    if live_webhook and bot_configured:
        try:
            import httpx

            token = settings.TELEGRAM_BOT_TOKEN
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
                payload = resp.json() if resp.content else {}
                info = payload.get("result") if isinstance(payload, dict) else {}
                if isinstance(info, dict):
                    webhook_url = info.get("url") or None
                    webhook_error = info.get("last_error_message") or None
        except Exception as exc:
            logger.info("Telegram getWebhookInfo failed: %s", type(exc).__name__)
            webhook_error = "unreachable"

    # Recent durable queue failures (platform-global, scoped to admin elsewhere).
    cutoff = now - timedelta(days=2)
    failed_count = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(TelegramWebhookEvent)
                .where(
                    TelegramWebhookEvent.status == "failed",
                    TelegramWebhookEvent.updated_at >= cutoff,
                )
            )
        )
        or 0
    )

    if not clients:
        results.append(
            _build_result(
                integration_id=f"telegram:tenant:{tenant_id}",
                platform="telegram",
                provider="telegram",
                tenant_id=tenant_id,
                client_id=None,
                account_name="Telegram",
                reason_code=REASON_NOT_CONFIGURED,
                checked_at=now,
                last_success_at=None,
                stale_after_seconds=STALE_AFTER_TELEGRAM_SECONDS,
                capabilities=[
                    CapabilityHealth(
                        name="intake",
                        status="not_configured",
                        reason_code=REASON_NOT_CONFIGURED,
                        reason="No clients configured",
                    )
                ],
                source="remote" if live_webhook else "local",
            )
        )
        return results

    for client in clients:
        has_group = bool(client.telegram_group_id)
        has_publish = bool(client.telegram_publish_chat_id)
        reason = REASON_HEALTHY
        caps: list[CapabilityHealth] = []

        if not bot_configured:
            reason = REASON_NOT_CONFIGURED
            caps.append(
                CapabilityHealth(
                    name="bot",
                    status="action_required",
                    reason_code=REASON_NOT_CONFIGURED,
                    reason="Telegram bot token is not configured",
                    requires_operator_action=True,
                )
            )
        elif live_webhook and not webhook_url:
            reason = REASON_WEBHOOK_NOT_CONFIGURED
            caps.append(
                CapabilityHealth(
                    name="webhook",
                    status="action_required",
                    reason_code=REASON_WEBHOOK_NOT_CONFIGURED,
                    reason="Telegram webhook URL is empty",
                    requires_operator_action=True,
                )
            )
        elif webhook_error and webhook_error != "unreachable":
            reason = REASON_WEBHOOK_UNHEALTHY
            caps.append(
                CapabilityHealth(
                    name="webhook",
                    status="degraded",
                    reason_code=REASON_WEBHOOK_UNHEALTHY,
                    reason="Telegram reported a recent webhook delivery error",
                )
            )
        elif failed_count >= 5:
            reason = REASON_WEBHOOK_UNHEALTHY
            caps.append(
                CapabilityHealth(
                    name="queue",
                    status="degraded",
                    reason_code=REASON_WEBHOOK_UNHEALTHY,
                    reason=f"{failed_count} recent webhook processing failures",
                )
            )

        if not has_group:
            if reason == REASON_HEALTHY:
                reason = REASON_NOT_CONFIGURED
            caps.append(
                CapabilityHealth(
                    name="intake_group",
                    status="not_configured",
                    reason_code=REASON_NOT_CONFIGURED,
                    reason="No Telegram intake group linked on client",
                )
            )
        else:
            caps.append(
                CapabilityHealth(
                    name="intake_group",
                    status="healthy",
                    reason_code=REASON_HEALTHY,
                    reason="Intake group linked",
                )
            )

        caps.append(
            CapabilityHealth(
                name="publish_destination",
                status="healthy" if has_publish else "not_configured",
                reason_code=REASON_HEALTHY if has_publish else REASON_NOT_CONFIGURED,
                reason="Publish chat linked" if has_publish else "No publish destination chat",
            )
        )

        # Do not send messages; do not mutate webhook.
        results.append(
            _build_result(
                integration_id=f"telegram:client:{client.id}",
                platform="telegram",
                provider="telegram",
                tenant_id=tenant_id,
                client_id=client.id,
                account_name=client.company_name,
                reason_code=reason,
                checked_at=now,
                last_success_at=now if reason == REASON_HEALTHY else None,
                stale_after_seconds=STALE_AFTER_TELEGRAM_SECONDS,
                capabilities=caps,
                source="remote" if live_webhook else "local",
                deep_link=f"/clients?client_id={client.id}",
            )
        )
    return results


async def evaluate_advertising_accounts(
    db: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[IntegrationHealthResult]:
    """Advertising connector health from persisted state + adapter health_check (read-only)."""
    now = _utc_now()
    rows = list(
        (
            await db.scalars(
                select(TenantAdvertisingAccount)
                .where(TenantAdvertisingAccount.tenant_id == tenant_id)
                .order_by(TenantAdvertisingAccount.updated_at.desc())
            )
        ).all()
    )
    results: list[IntegrationHealthResult] = []
    if not rows:
        return results

    from app.services.advertising_platform.registry import get_adapter

    for row in rows:
        provider = (row.provider or "unknown").lower()
        conn = (row.connection_status or "unknown").lower()

        if provider == "mock":
            reason = REASON_UNSUPPORTED
            status_override = "unknown"
            next_step = "Mock advertising connector — not a live provider health signal."
        elif conn in ("disconnected", "revoked"):
            reason = REASON_DISCONNECTED
            status_override = None
            next_step = None
        elif conn == "expired":
            reason = REASON_EXPIRED_TOKEN
            status_override = None
            next_step = None
        elif conn == "permission_blocked":
            reason = REASON_MISSING_REQUIRED_SCOPE
            status_override = None
            next_step = None
        elif conn == "error":
            reason = REASON_CAPABILITY_UNAVAILABLE
            status_override = None
            next_step = None
        elif conn == "connected":
            reason = REASON_HEALTHY
            status_override = None
            next_step = None
        else:
            reason = REASON_UNKNOWN
            status_override = None
            next_step = None

        caps = [
            CapabilityHealth(
                name="import",
                status=reason_meta(reason)["status"],
                reason_code=reason,
                reason=reason_meta(reason)["explanation"],
                requires_operator_action=bool(reason_meta(reason)["requires_operator_action"]),
            )
        ]

        # Stale metrics signal (local).
        last_sync = getattr(row, "last_successful_sync_at", None) or getattr(
            row, "last_metrics_sync_at", None
        )
        if last_sync is None and conn == "connected" and provider != "mock":
            caps.append(
                CapabilityHealth(
                    name="metrics",
                    status="unknown",
                    reason_code=REASON_NEVER_CHECKED,
                    reason="No successful metrics refresh recorded",
                )
            )
        elif last_sync is not None:
            aware = last_sync if last_sync.tzinfo else last_sync.replace(tzinfo=timezone.utc)
            if (now - aware).total_seconds() > STALE_AFTER_ADS_SECONDS:
                caps.append(
                    CapabilityHealth(
                        name="metrics",
                        status="degraded",
                        reason_code=REASON_CAPABILITY_UNAVAILABLE,
                        reason="Advertising metrics appear stale",
                    )
                )
                if reason == REASON_HEALTHY:
                    reason = REASON_CAPABILITY_UNAVAILABLE

        # Adapter probe is local classification — never mutates provider.
        try:
            adapter = get_adapter(provider)
            health = await adapter.health_check(connection_status=conn)
            if getattr(health, "status", None) in ("unavailable", "error", "permission_blocked"):
                if reason == REASON_HEALTHY:
                    reason = REASON_CAPABILITY_UNAVAILABLE
        except Exception:
            logger.debug("Advertising adapter health_check skipped for %s", provider)

        results.append(
            _build_result(
                integration_id=str(row.id),
                platform=provider,
                provider=provider,
                tenant_id=tenant_id,
                client_id=None,
                account_name=getattr(row, "name", None) or getattr(row, "account_name", None),
                reason_code=reason,
                checked_at=now,
                last_success_at=last_sync if isinstance(last_sync, datetime) else None,
                stale_after_seconds=STALE_AFTER_ADS_SECONDS,
                capabilities=caps,
                source="local",
                status_override=status_override,
                next_step_override=next_step,
                deep_link="/advertising",
            )
        )
    return results


async def evaluate_listening_sources(
    db: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[IntegrationHealthResult]:
    """Listening health from durable source rows + linked publishing permissions."""
    now = _utc_now()
    sources = list(
        (
            await db.scalars(
                select(TenantListeningSource)
                .where(TenantListeningSource.tenant_id == tenant_id)
                .order_by(TenantListeningSource.updated_at.desc())
            )
        ).all()
    )
    results: list[IntegrationHealthResult] = []

    live_sources = [
        s for s in sources
        if (getattr(s, "capability_status", None) or "") == "live"
        or (getattr(s, "source_type", "") or "").startswith("facebook_page")
    ]

    if not live_sources:
        results.append(
            _build_result(
                integration_id=f"listening:tenant:{tenant_id}",
                platform="listening",
                provider="listening",
                tenant_id=tenant_id,
                client_id=None,
                account_name="Social Listening",
                reason_code=REASON_NOT_CONFIGURED,
                checked_at=now,
                last_success_at=None,
                stale_after_seconds=STALE_AFTER_LISTENING_SECONDS,
                capabilities=[
                    CapabilityHealth(
                        name="live_ingestion",
                        status="not_configured",
                        reason_code=REASON_NOT_CONFIGURED,
                        reason="No live Listening sources configured",
                    )
                ],
                source="local",
                deep_link="/listening",
            )
        )
        return results

    for source in live_sources:
        health = (source.health_status or "unknown").lower()
        client_id = None
        # Resolve client via project if present.
        project = getattr(source, "project", None)
        if project is not None:
            client_id = getattr(project, "client_id", None)

        if health in ("healthy", "healthy_zero"):
            reason = REASON_HEALTHY
        elif health in ("missing_scope",):
            reason = REASON_MISSING_REQUIRED_SCOPE
        elif health in ("token_expired_or_revoked",):
            reason = REASON_EXPIRED_TOKEN
        elif health in ("rate_limited",):
            reason = REASON_PROVIDER_RATE_LIMITED
        elif health in ("provider_unavailable",):
            reason = REASON_PROVIDER_UNREACHABLE
        elif health in ("paused",):
            reason = REASON_CAPABILITY_UNAVAILABLE
        else:
            reason = REASON_UNKNOWN

        last_success = getattr(source, "last_success_at", None)
        results.append(
            _build_result(
                integration_id=str(source.id),
                platform="listening",
                provider=source.source_type or "listening",
                tenant_id=tenant_id,
                client_id=client_id,
                account_name=getattr(source, "display_name", None) or source.source_type,
                reason_code=reason,
                checked_at=now,
                last_success_at=last_success,
                stale_after_seconds=STALE_AFTER_LISTENING_SECONDS,
                capabilities=[
                    CapabilityHealth(
                        name="ingestion",
                        status=reason_meta(reason)["status"],
                        reason_code=reason,
                        reason=reason_meta(reason)["explanation"],
                        requires_operator_action=bool(reason_meta(reason)["requires_operator_action"]),
                    ),
                    CapabilityHealth(
                        name="freshness",
                        status=(getattr(source, "freshness_status", None) or "unknown"),
                        reason_code=REASON_UNKNOWN,
                        reason=f"Freshness: {getattr(source, 'freshness_status', None) or 'unknown'}",
                    ),
                ],
                source="local",
                deep_link="/listening",
            )
        )
    return results
