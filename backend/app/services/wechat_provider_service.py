"""WeChat Provider v1 — registry, configuration, connection testing, webhook framework (no auto-send)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wechat_provider import (
    WeChatProvider,
    WeChatProviderConfiguration,
    WeChatProviderWebhookEvent,
)
from app.services.wechat_adapter import list_adapter_providers

logger = logging.getLogger(__name__)

MARKER = "[WeChat Provider]"

DEFAULT_CAPABILITIES: dict[str, dict[str, bool]] = {
    "wecom_api": {
        "contact_sync": True,
        "conversation_sync": True,
        "message_send": False,
        "media_upload": True,
        "webhook_support": True,
    },
    "official_account_api": {
        "contact_sync": False,
        "conversation_sync": True,
        "message_send": False,
        "media_upload": True,
        "webhook_support": True,
    },
    "third_party_connector": {
        "contact_sync": True,
        "conversation_sync": True,
        "message_send": False,
        "media_upload": True,
        "webhook_support": True,
    },
    "custom_provider": {
        "contact_sync": True,
        "conversation_sync": True,
        "message_send": False,
        "media_upload": False,
        "webhook_support": False,
    },
}

DEMO_PROVIDERS = [
    {
        "provider_name": "Demo WeCom API",
        "provider_type": "wecom_api",
        "status": "active",
    },
    {
        "provider_name": "Demo Official Account API",
        "provider_type": "official_account_api",
        "status": "active",
    },
    {
        "provider_name": "Demo Third-Party Connector",
        "provider_type": "third_party_connector",
        "status": "active",
    },
]

WEBHOOK_FRAMEWORK: list[dict[str, Any]] = [
    {
        "event_type": "inbound_message",
        "status": "architecture_only",
        "processing_enabled": False,
        "message": "Webhook handler registered — live processing disabled in v1",
    },
    {
        "event_type": "contact_update",
        "status": "architecture_only",
        "processing_enabled": False,
        "message": "Contact update webhook scaffold — no live processing in v1",
    },
    {
        "event_type": "conversation_update",
        "status": "architecture_only",
        "processing_enabled": False,
        "message": "Conversation update webhook scaffold — no live processing in v1",
    },
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _capabilities_for_type(provider_type: str) -> dict[str, bool]:
    return dict(DEFAULT_CAPABILITIES.get(provider_type, DEFAULT_CAPABILITIES["custom_provider"]))


def _provider_to_dict(provider: WeChatProvider) -> dict[str, Any]:
    caps = provider.capabilities_json or _capabilities_for_type(provider.provider_type)
    return {
        "id": provider.id,
        "provider_name": provider.provider_name,
        "provider_type": provider.provider_type,
        "status": provider.status,
        "capabilities": caps,
        "created_at": provider.created_at,
    }


class WeChatProviderService:
    @staticmethod
    async def ensure_demo_providers(db: AsyncSession) -> None:
        count = await db.scalar(select(func.count()).select_from(WeChatProvider))
        if count and count > 0:
            return
        for spec in DEMO_PROVIDERS:
            provider = WeChatProvider(
                provider_name=spec["provider_name"],
                provider_type=spec["provider_type"],
                status=spec["status"],
                capabilities_json=_capabilities_for_type(spec["provider_type"]),
                config_json={"demo": True, "credentials_required": False},
            )
            db.add(provider)
            await db.flush()
            db.add(
                WeChatProviderConfiguration(
                    provider_id=provider.id,
                    tenant_id=None,
                    config_status="configured",
                    config_json={"demo": True, "mode": "placeholder"},
                ),
            )
        for hook in WEBHOOK_FRAMEWORK:
            db.add(
                WeChatProviderWebhookEvent(
                    event_type=hook["event_type"],
                    status=hook["status"],
                    notes=hook["message"],
                    payload_json={"framework": "v1", "live_processing": False},
                ),
            )
        await db.commit()
        logger.info("%s seeded %s demo providers", MARKER, len(DEMO_PROVIDERS))

    @staticmethod
    async def _get_provider(db: AsyncSession, provider_id: UUID) -> WeChatProvider:
        provider = await db.get(WeChatProvider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        return provider

    @staticmethod
    async def list_providers(db: AsyncSession) -> dict[str, Any]:
        await WeChatProviderService.ensure_demo_providers(db)
        rows = (
            await db.execute(
                select(WeChatProvider).order_by(WeChatProvider.created_at.asc()),
            )
        ).scalars().all()
        items = [_provider_to_dict(p) for p in rows]
        return {"items": items, "total": len(items)}

    @staticmethod
    async def list_configurations(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        await WeChatProviderService.ensure_demo_providers(db)
        q = select(WeChatProviderConfiguration).order_by(
            WeChatProviderConfiguration.created_at.asc(),
        )
        if tenant_id:
            q = q.where(WeChatProviderConfiguration.tenant_id == tenant_id)
        rows = (await db.execute(q)).scalars().all()
        provider_ids = {c.provider_id for c in rows}
        names: dict[UUID, str] = {}
        if provider_ids:
            name_rows = (
                await db.execute(
                    select(WeChatProvider.id, WeChatProvider.provider_name).where(
                        WeChatProvider.id.in_(provider_ids),
                    ),
                )
            ).all()
            names = {r[0]: r[1] for r in name_rows}
        items = []
        for cfg in rows:
            items.append({
                "id": cfg.id,
                "provider_id": cfg.provider_id,
                "provider_name": names.get(cfg.provider_id),
                "tenant_id": cfg.tenant_id,
                "config_status": cfg.config_status,
                "last_connection_test": cfg.last_connection_test,
                "created_at": cfg.created_at,
            })
        return {"items": items, "total": len(items)}

    @staticmethod
    def validate_config(provider_type: str, config_json: dict[str, Any] | None) -> dict[str, Any]:
        """Validate provider config shape — no real credentials required in v1."""
        cfg = dict(config_json or {})
        errors: list[str] = []
        warnings: list[str] = []

        if provider_type == "wecom_api":
            if not cfg.get("corp_id") and not cfg.get("demo"):
                warnings.append("corp_id not set — demo/placeholder mode")
        elif provider_type == "official_account_api":
            if not cfg.get("app_id") and not cfg.get("demo"):
                warnings.append("app_id not set — demo/placeholder mode")
        elif provider_type == "third_party_connector":
            if not cfg.get("connector_url") and not cfg.get("demo"):
                warnings.append("connector_url not set — demo/placeholder mode")

        if cfg.get("auto_send") or cfg.get("send_messages"):
            errors.append("message sending is disabled in v1")

        valid = len(errors) == 0
        return {
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
            "provider_type": provider_type,
            "credentials_required": False,
        }

    @staticmethod
    async def test_connection(
        db: AsyncSession,
        *,
        provider_id: UUID,
        config_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await WeChatProviderService.ensure_demo_providers(db)
        provider = await WeChatProviderService._get_provider(db, provider_id)
        start = time.perf_counter()

        merged_cfg = dict(provider.config_json or {})
        if config_json:
            merged_cfg.update(config_json)

        validation = WeChatProviderService.validate_config(provider.provider_type, merged_cfg)
        if not validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail="; ".join(validation["errors"]) or "Invalid configuration",
            )

        latency_ms = int((time.perf_counter() - start) * 1000) + 8
        ok = provider.status in ("active", "pending")
        message = (
            f"Demo connection OK ({provider.provider_type}) — no live provider API in v1"
            if ok
            else f"Provider status is {provider.status}"
        )

        cfg_row = (
            await db.execute(
                select(WeChatProviderConfiguration)
                .where(WeChatProviderConfiguration.provider_id == provider_id)
                .order_by(WeChatProviderConfiguration.created_at.desc())
                .limit(1),
            )
        ).scalar_one_or_none()
        now = _utcnow()
        if cfg_row:
            cfg_row.last_connection_test = now
            cfg_row.config_status = "validated" if ok else "error"
            if config_json:
                cfg_row.config_json = merged_cfg
        await db.commit()

        return {
            "ok": ok,
            "provider_id": provider.id,
            "provider_name": provider.provider_name,
            "provider_type": provider.provider_type,
            "message": message,
            "latency_ms": latency_ms,
            "config_valid": validation["valid"],
            "details": {
                "mode": "demo",
                "external_calls": False,
                "send_capable": False,
                "validation": validation,
                "adapters_available": list_adapter_providers(),
            },
        }

    @staticmethod
    async def register_provider(
        db: AsyncSession,
        *,
        provider_name: str,
        provider_type: str,
        tenant_id: UUID | None = None,
        config_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if provider_type not in DEFAULT_CAPABILITIES:
            raise HTTPException(status_code=400, detail=f"Unsupported provider type: {provider_type}")

        merged_cfg = dict(config_json or {})
        merged_cfg.setdefault("demo", True)
        validation = WeChatProviderService.validate_config(provider_type, merged_cfg)
        if not validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail="; ".join(validation["errors"]) or "Invalid configuration",
            )

        provider = WeChatProvider(
            provider_name=provider_name.strip(),
            provider_type=provider_type,
            status="active",
            capabilities_json=_capabilities_for_type(provider_type),
            config_json=merged_cfg,
        )
        db.add(provider)
        await db.flush()

        configuration = WeChatProviderConfiguration(
            provider_id=provider.id,
            tenant_id=tenant_id,
            config_status="configured",
            config_json=merged_cfg,
        )
        db.add(configuration)
        await db.commit()
        await db.refresh(provider)
        await db.refresh(configuration)

        logger.info("%s registered provider %s (%s)", MARKER, provider.id, provider_type)
        return {
            "provider": _provider_to_dict(provider),
            "configuration": {
                "id": configuration.id,
                "provider_id": configuration.provider_id,
                "provider_name": provider.provider_name,
                "tenant_id": configuration.tenant_id,
                "config_status": configuration.config_status,
                "last_connection_test": configuration.last_connection_test,
                "created_at": configuration.created_at,
            },
            "message": "Provider registered — architecture only, no live API calls",
        }

    @staticmethod
    def webhook_status() -> list[dict[str, Any]]:
        return list(WEBHOOK_FRAMEWORK)

    @staticmethod
    async def integration_checks(db: AsyncSession) -> list[dict[str, Any]]:
        """Lightweight integration probes for connected modules."""
        checks: list[dict[str, Any]] = []

        try:
            from app.services.wechat_sync_service import WeChatSyncService

            sync_status = await WeChatSyncService.status_overview(db)
            checks.append({
                "module": "wechat_sync",
                "status": "ok" if sync_status.get("accounts_total", 0) > 0 else "degraded",
                "message": "WeChat Sync accounts available for provider-backed import",
                "details": {
                    "accounts_total": sync_status.get("accounts_total", 0),
                    "adapters": sync_status.get("adapters_available", []),
                },
            })
        except Exception as exc:
            checks.append({
                "module": "wechat_sync",
                "status": "unavailable",
                "message": str(exc)[:200],
                "details": {},
            })

        try:
            from app.models.communication import CommunicationThread
            from sqlalchemy import select as sa_select

            thread_count = await db.scalar(
                sa_select(func.count()).select_from(CommunicationThread).where(
                    CommunicationThread.channel.in_(["wechat", "wecom"]),
                ),
            ) or 0
            checks.append({
                "module": "wechat_center",
                "status": "ok",
                "message": "WeChat Center channel threads reachable",
                "details": {"wechat_threads": int(thread_count)},
            })
        except Exception as exc:
            checks.append({
                "module": "wechat_center",
                "status": "unavailable",
                "message": str(exc)[:200],
                "details": {},
            })

        try:
            from app.models.communication import CommunicationThread

            inbox_count = await db.scalar(
                select(func.count()).select_from(CommunicationThread),
            ) or 0
            checks.append({
                "module": "unified_inbox",
                "status": "ok",
                "message": "Unified Inbox communication hub available",
                "details": {"threads_total": int(inbox_count)},
            })
        except Exception as exc:
            checks.append({
                "module": "unified_inbox",
                "status": "unavailable",
                "message": str(exc)[:200],
                "details": {},
            })

        try:
            from app.services.communication_intelligence_service import CommunicationIntelligenceService

            overview = await CommunicationIntelligenceService.overview(db)
            checks.append({
                "module": "communication_intelligence",
                "status": "ok",
                "message": "Communication Intelligence overview reachable",
                "details": {"has_overview": bool(overview)},
            })
        except Exception as exc:
            checks.append({
                "module": "communication_intelligence",
                "status": "degraded",
                "message": str(exc)[:200],
                "details": {},
            })

        provider_count = await db.scalar(select(func.count()).select_from(WeChatProvider)) or 0
        checks.append({
            "module": "executive_copilot",
            "status": "ok" if provider_count > 0 else "degraded",
            "message": "Executive Copilot can surface provider health in overview",
            "details": {"providers_registered": int(provider_count)},
        })

        return checks

    @staticmethod
    async def provider_health(db: AsyncSession) -> dict[str, Any]:
        await WeChatProviderService.ensure_demo_providers(db)
        providers = (await db.execute(select(WeChatProvider))).scalars().all()
        configs = (await db.execute(select(WeChatProviderConfiguration))).scalars().all()

        config_by_provider: dict[UUID, WeChatProviderConfiguration] = {}
        for cfg in configs:
            if cfg.provider_id not in config_by_provider:
                config_by_provider[cfg.provider_id] = cfg

        health_items: list[dict[str, Any]] = []
        last_test: datetime | None = None
        for provider in providers:
            cfg = config_by_provider.get(provider.id)
            test_at = cfg.last_connection_test if cfg else None
            if test_at and (last_test is None or test_at > last_test):
                last_test = test_at
            connection_ok = provider.status == "active" and (
                cfg is None or cfg.config_status in ("configured", "validated")
            )
            health_items.append({
                "provider_id": provider.id,
                "provider_name": provider.provider_name,
                "provider_type": provider.provider_type,
                "status": provider.status,
                "config_status": cfg.config_status if cfg else None,
                "last_connection_test": test_at,
                "connection_ok": connection_ok,
                "message": "Ready (demo mode)" if connection_ok else "Needs configuration or validation",
            })

        active = sum(1 for p in providers if p.status == "active")
        validated = sum(1 for c in configs if c.config_status == "validated")
        integration = await WeChatProviderService.integration_checks(db)
        degraded_modules = [c for c in integration if c["status"] != "ok"]
        overall = "ok"
        if not providers:
            overall = "unavailable"
        elif degraded_modules or active < len(providers):
            overall = "degraded"

        return {
            "providers_total": len(providers),
            "providers_active": active,
            "configurations_total": len(configs),
            "configurations_validated": validated,
            "last_connection_test": last_test,
            "overall_status": overall,
            "provider_health": health_items,
            "integration_checks": integration,
            "webhook_status": WeChatProviderService.webhook_status(),
            "safety": {
                "message_send_disabled": True,
                "no_external_provider_calls": True,
                "no_real_credentials_required": True,
                "no_automatic_messaging": True,
            },
        }

    # --- Webhook framework stubs (architecture only) ---

    @staticmethod
    async def handle_inbound_message(
        db: AsyncSession,
        *,
        provider_id: UUID | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = WeChatProviderWebhookEvent(
            provider_id=provider_id,
            event_type="inbound_message",
            status="architecture_only",
            payload_json=payload,
            notes="Recorded only — live inbound processing disabled in v1",
        )
        db.add(event)
        await db.commit()
        return {"status": "architecture_only", "processed": False, "event_id": str(event.id)}

    @staticmethod
    async def handle_contact_update(
        db: AsyncSession,
        *,
        provider_id: UUID | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = WeChatProviderWebhookEvent(
            provider_id=provider_id,
            event_type="contact_update",
            status="architecture_only",
            payload_json=payload,
            notes="Recorded only — live contact update processing disabled in v1",
        )
        db.add(event)
        await db.commit()
        return {"status": "architecture_only", "processed": False, "event_id": str(event.id)}

    @staticmethod
    async def handle_conversation_update(
        db: AsyncSession,
        *,
        provider_id: UUID | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = WeChatProviderWebhookEvent(
            provider_id=provider_id,
            event_type="conversation_update",
            status="architecture_only",
            payload_json=payload,
            notes="Recorded only — live conversation update processing disabled in v1",
        )
        db.add(event)
        await db.commit()
        return {"status": "architecture_only", "processed": False, "event_id": str(event.id)}
