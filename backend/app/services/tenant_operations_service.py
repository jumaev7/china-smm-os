"""Admin tenant operations — onboarding readiness and Telegram intake visibility."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.models.publishing_account import PublishingAccount
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.models.telegram_ingestion import TelegramIngestionSettings
from app.models.tenant import TenantUser
from app.services.admin_rbac_service import AdminRbacService, CurrentAdminUser
from app.services.subscription_service import SubscriptionService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

PLACEHOLDER_PREFIX = "Telegram Group:"
TELEGRAM_SOURCES = frozenset({"telegram", "telegram_group", "tg_group_buffer"})
ACTIVE_ACCOUNT_STATUSES = frozenset({"connected", "mock"})


def _is_placeholder_client(client: Client) -> bool:
    name = (client.company_name or "").strip()
    if name.startswith(PLACEHOLDER_PREFIX):
        return True
    notes = (client.notes or "").lower()
    return "auto-created from telegram" in notes


class TenantOperationsService:
    @staticmethod
    async def _webhook_snapshot() -> dict[str, Any]:
        token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
        if not token:
            return {}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
            body = resp.json()
            if not body.get("ok"):
                return {}
            info = body.get("result") or {}
            return {
                "webhook_url": info.get("url") or None,
                "webhook_pending_updates": info.get("pending_update_count"),
                "webhook_last_error": info.get("last_error_message") or None,
            }
        except Exception as exc:
            logger.debug("getWebhookInfo failed: %s", exc)
            return {}

    @staticmethod
    async def _last_intake_for_client(
        db: AsyncSession,
        client_id: UUID,
    ) -> datetime | None:
        content_at = await db.scalar(
            select(func.max(ContentItem.created_at)).where(
                ContentItem.client_id == client_id,
                ContentItem.source.in_(tuple(TELEGRAM_SOURCES)),
            ),
        )
        buffer_at = await db.scalar(
            select(func.max(TelegramGroupBufferMessage.message_at)).where(
                TelegramGroupBufferMessage.client_id == client_id,
            ),
        )
        candidates = [t for t in (content_at, buffer_at) if t is not None]
        return max(candidates) if candidates else None

    @staticmethod
    async def _duplicate_group_clients(
        db: AsyncSession,
        group_id: str,
        exclude_client_id: UUID,
    ) -> list[Client]:
        if not group_id:
            return []
        result = await db.execute(
            select(Client).where(
                Client.telegram_group_id == group_id,
                Client.id != exclude_client_id,
            ),
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_tenant_operations(
        db: AsyncSession,
        admin: CurrentAdminUser,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        AdminRbacService.assert_permission(admin, "tenants.read")
        tenant = await TenantService.get_tenant(db, tenant_id)

        owners = (
            await db.execute(
                select(TenantUser).where(
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.role == "owner",
                    TenantUser.status == "active",
                ),
            )
        ).scalars().all()
        owner = owners[0] if owners else None
        owner_has_password = any(bool(u.password_hash) for u in owners)

        clients = (
            await db.execute(
                select(Client).where(Client.tenant_id == tenant_id).order_by(Client.created_at),
            )
        ).scalars().all()
        client_ids = [c.id for c in clients]
        primary_client = next((c for c in clients if not _is_placeholder_client(c)), None)
        if primary_client is None and clients:
            primary_client = clients[0]

        content_count = 0
        telegram_content_count = 0
        if client_ids:
            content_count = int(
                await db.scalar(
                    select(func.count()).select_from(ContentItem).where(
                        ContentItem.client_id.in_(client_ids),
                    ),
                ) or 0,
            )
            telegram_content_count = int(
                await db.scalar(
                    select(func.count()).select_from(ContentItem).where(
                        ContentItem.client_id.in_(client_ids),
                        ContentItem.source.in_(tuple(TELEGRAM_SOURCES)),
                    ),
                ) or 0,
            )

        sub, _plan = await SubscriptionService._active_subscription(db, tenant_id)
        subscription_status = sub.status if sub else None

        has_publish_dest = any(
            bool((c.telegram_publish_chat_id or "").strip()) for c in clients
        )
        connected_accounts = int(
            await db.scalar(
                select(func.count()).select_from(PublishingAccount).where(
                    PublishingAccount.status.in_(tuple(ACTIVE_ACCOUNT_STATUSES)),
                ),
            ) or 0,
        )

        ingestion_settings = (
            await db.execute(select(TelegramIngestionSettings).limit(1))
        ).scalar_one_or_none()
        ingestion_enabled = bool(
            settings.TELEGRAM_INGESTION_ENABLED
            and ingestion_settings
            and ingestion_settings.enabled,
        )

        webhook_info = await TenantOperationsService._webhook_snapshot()
        telegram_health = {
            "bot_configured": bool((settings.TELEGRAM_BOT_TOKEN or "").strip()),
            "ingestion_enabled": ingestion_enabled,
            **webhook_info,
        }

        clients_telegram: list[dict[str, Any]] = []
        any_intake_linked = False
        any_duplicate_warning = False
        for client in clients:
            group_id = (client.telegram_group_id or "").strip() or None
            intake_linked = bool(group_id)
            if intake_linked and not _is_placeholder_client(client):
                any_intake_linked = True
            duplicates = []
            duplicate_warning = False
            if group_id:
                dupes = await TenantOperationsService._duplicate_group_clients(
                    db, group_id, client.id,
                )
                if dupes:
                    duplicate_warning = True
                    any_duplicate_warning = True
                    duplicates = [str(d.id) for d in dupes]
            last_intake = await TenantOperationsService._last_intake_for_client(db, client.id)
            clients_telegram.append({
                "client_id": client.id,
                "company_name": client.company_name,
                "is_placeholder": _is_placeholder_client(client),
                "telegram_group_id": group_id,
                "telegram_group_title": client.telegram_group_title,
                "telegram_workflow_mode": client.telegram_workflow_mode,
                "telegram_publish_chat_id": client.telegram_publish_chat_id,
                "intake_linked": intake_linked,
                "duplicate_group_warning": duplicate_warning,
                "duplicate_client_ids": duplicates,
                "last_intake_at": last_intake,
            })

        checks: list[dict[str, Any]] = [
            {
                "id": "tenant_active",
                "label": "Tenant active",
                "ok": tenant.status == "active",
                "detail": f"Status: {tenant.status}",
                "critical": True,
            },
            {
                "id": "owner_user",
                "label": "Owner user created",
                "ok": owner is not None,
                "detail": owner.email if owner else "No active owner user",
                "critical": True,
            },
            {
                "id": "owner_password",
                "label": "Owner can log in",
                "ok": owner_has_password,
                "detail": "Password set" if owner_has_password else "Owner has no password — set via admin provision or reset",
                "critical": True,
            },
            {
                "id": "client_record",
                "label": "Linked client record",
                "ok": bool(clients),
                "detail": f"{len(clients)} client(s)" if clients else "No CRM client linked to tenant",
                "critical": True,
            },
            {
                "id": "telegram_intake",
                "label": "Telegram intake linked",
                "ok": any_intake_linked,
                "detail": "Group ID on primary client" if any_intake_linked else "Link telegram_group_id on client settings",
                "critical": False,
            },
            {
                "id": "telegram_no_duplicates",
                "label": "No duplicate group linkage",
                "ok": not any_duplicate_warning,
                "detail": "Duplicate clients share the same group ID" if any_duplicate_warning else "OK",
                "critical": False,
            },
            {
                "id": "content_items",
                "label": "Content available",
                "ok": content_count > 0,
                "detail": f"{content_count} item(s), {telegram_content_count} from Telegram",
                "critical": False,
            },
            {
                "id": "publishing",
                "label": "Publishing destination",
                "ok": has_publish_dest or connected_accounts > 0,
                "detail": (
                    "Client publish chat or platform account connected"
                    if (has_publish_dest or connected_accounts > 0)
                    else "Connect a publish destination or publishing account"
                ),
                "critical": False,
            },
            {
                "id": "subscription",
                "label": "Subscription active",
                "ok": subscription_status in ("trial", "active"),
                "detail": subscription_status or "No subscription — create on Billing",
                "critical": False,
            },
            {
                "id": "bot_ready",
                "label": "Telegram bot configured",
                "ok": telegram_health["bot_configured"] and ingestion_enabled,
                "detail": (
                    "Bot token + ingestion enabled"
                    if telegram_health["bot_configured"] and ingestion_enabled
                    else "Check TELEGRAM_BOT_TOKEN and ingestion settings"
                ),
                "critical": False,
            },
        ]

        critical_blockers = [c["label"] for c in checks if c["critical"] and not c["ok"]]
        readiness = "ready" if not critical_blockers else "onboarding_incomplete"

        next_steps: list[str] = []
        if not owner_has_password:
            next_steps.append("Set owner password or re-provision via Create Client")
        if not clients:
            next_steps.append("Ensure tenant has a linked CRM client record")
        if clients and not any_intake_linked:
            next_steps.append("Link Telegram group on client settings (/clients → Telegram)")
        if any_duplicate_warning:
            next_steps.append("Resolve duplicate Telegram group clients (run link_telegram_group.py or merge)")
        if subscription_status not in ("trial", "active"):
            next_steps.append("Create trial/active subscription on Billing page")
        if not telegram_health["bot_configured"]:
            next_steps.append("Configure TELEGRAM_BOT_TOKEN and register webhook for live intake")
        if content_count == 0:
            next_steps.append("Client can upload via Telegram group or create content manually")
        if not next_steps and readiness == "ready":
            next_steps.append("Tenant is ready for content operations — share login and test Telegram intake")

        return {
            "tenant_id": tenant_id,
            "company_name": tenant.company_name,
            "tenant_status": tenant.status,
            "plan": tenant.plan,
            "readiness": readiness,
            "checks": checks,
            "blockers": critical_blockers,
            "owner_email": owner.email if owner else None,
            "owner_has_password": owner_has_password,
            "client_count": len(clients),
            "primary_client_id": primary_client.id if primary_client else None,
            "content_count": content_count,
            "telegram_content_count": telegram_content_count,
            "subscription_status": subscription_status,
            "has_publishing_destination": has_publish_dest,
            "connected_publishing_accounts": connected_accounts,
            "clients_telegram": clients_telegram,
            "telegram_health": telegram_health,
            "next_steps": next_steps,
        }
