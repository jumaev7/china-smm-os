"""Meta publishing connection — account health, refresh, disconnect."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.publishing_account import PublishingAccount
from app.services.meta_graph_client import (
    debug_token,
    exchange_for_long_lived_token,
    get_user_pages,
    meta_oauth_configured,
    missing_connection_permissions,
    missing_facebook_publish_permissions,
    pick_page,
    token_is_expired,
)
from app.services.publishing_destination_registry import (
    platform_implementation,
    tenant_destination_status,
)
from app.utils.token_vault import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

META_PLATFORMS = frozenset({"facebook", "instagram"})
USABLE_STATUSES = frozenset({"connected", "mock"})


def _loads_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _loads_permissions(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return list(data) if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _dumps_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


class MetaConnectionService:
    @staticmethod
    def is_meta_platform(platform: str) -> bool:
        return platform in META_PLATFORMS

    @staticmethod
    async def list_meta_accounts(db: AsyncSession, tenant_id: UUID) -> list[PublishingAccount]:
        result = await db.execute(
            select(PublishingAccount)
            .where(PublishingAccount.tenant_id == tenant_id)
            .where(PublishingAccount.platform.in_(tuple(META_PLATFORMS)))
            .order_by(PublishingAccount.platform, PublishingAccount.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_primary_meta_accounts(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> dict[str, PublishingAccount | None]:
        accounts = await MetaConnectionService.list_meta_accounts(db, tenant_id)
        by_platform: dict[str, PublishingAccount | None] = {"facebook": None, "instagram": None}
        for account in accounts:
            if account.status == "disconnected":
                continue
            if by_platform.get(account.platform) is None:
                by_platform[account.platform] = account
        return by_platform

    @staticmethod
    def account_permissions(account: PublishingAccount) -> list[str]:
        return _loads_permissions(account.permissions_json)

    @staticmethod
    def account_metadata(account: PublishingAccount) -> dict[str, Any]:
        return _loads_json(account.account_metadata_json)

    @staticmethod
    def derive_status(
        *,
        token_valid: bool,
        expired: bool,
        missing_perms: list[str],
        has_page: bool,
        disconnected: bool = False,
    ) -> str:
        if disconnected:
            return "disconnected"
        if not has_page:
            return "blocked"
        if expired:
            return "expired"
        if not token_valid:
            return "invalid"
        if missing_perms:
            return "missing_permissions"
        return "connected"

    @staticmethod
    async def evaluate_account_health(
        account: PublishingAccount,
        *,
        live_check: bool = True,
    ) -> dict[str, Any]:
        permissions = MetaConnectionService.account_permissions(account)
        metadata = MetaConnectionService.account_metadata(account)
        expired = token_is_expired(account.expires_at)
        blockers: list[str] = []
        health = "unknown"

        has_page = bool(account.facebook_page_id) if account.platform == "facebook" else True
        if account.platform == "instagram" and not account.instagram_business_account_id:
            has_page = False
            blockers.append("Instagram Business account not linked to the connected Facebook Page")

        missing_perms = missing_connection_permissions(permissions)
        token_valid = bool(account.access_token_encrypted)

        if live_check and token_valid and meta_oauth_configured() and not expired:
            if metadata.get("demo"):
                health = "healthy" if account.status == "connected" else health
                token_valid = True
                missing_perms = []
            else:
                try:
                    token = decrypt_token(account.access_token_encrypted or "")
                    debug_data = await debug_token(token)
                    if not debug_data.get("is_valid"):
                        token_valid = False
                        blockers.append("Meta access token is invalid — reconnect required")
                    else:
                        live_perms = debug_data.get("scopes") or []
                        if isinstance(live_perms, list) and live_perms and not permissions:
                            permissions = sorted({str(p) for p in live_perms if p})
                        missing_perms = missing_connection_permissions(permissions)
                except Exception as exc:
                    logger.warning("Meta token health check failed: %s", exc)
                    token_valid = False
                    blockers.append(f"Token validation failed: {exc}")

        if expired:
            blockers.append("Meta access token has expired — reconnect or refresh")
        if missing_perms:
            blockers.append(
                f"Missing Meta permissions: {', '.join(missing_perms)}",
            )
        if account.platform == "facebook" and not account.facebook_page_id:
            blockers.append("Facebook Page is disconnected — reconnect Meta account")
        if account.status == "disconnected":
            blockers.append("Meta account disconnected")

        derived_status = MetaConnectionService.derive_status(
            token_valid=token_valid,
            expired=expired,
            missing_perms=missing_perms,
            has_page=has_page,
            disconnected=account.status == "disconnected",
        )
        if account.status in USABLE_STATUSES or account.status in {
            "expired", "invalid", "missing_permissions", "blocked",
        }:
            effective_status = derived_status
        else:
            effective_status = account.status

        if effective_status == "connected":
            health = "healthy"
        elif effective_status == "mock":
            health = "mock"
        elif effective_status == "expired":
            health = "expired"
        elif effective_status == "missing_permissions":
            health = "missing_permissions"
        elif effective_status in ("invalid", "blocked"):
            health = "unhealthy"
        else:
            health = "disconnected"

        expired_flag = token_is_expired(account.expires_at)
        has_page_token = bool(account.access_token_encrypted)
        is_demo = bool(metadata.get("demo"))
        dest_status = tenant_destination_status(
            account.platform,
            has_account=True,
            account_status=effective_status,
            facebook_page_id=account.facebook_page_id,
            permissions=permissions,
            token_expired=expired_flag,
            has_page_token=has_page_token,
            is_demo=is_demo,
        )
        implementation = platform_implementation(
            account.platform,
            dest_status=dest_status,
            account_status=effective_status,
            facebook_page_id=account.facebook_page_id,
            permissions=permissions,
            token_expired=expired_flag,
            has_page_token=has_page_token,
            is_demo=is_demo,
        )
        publish_ready = account.platform == "facebook" and implementation == "live"

        return {
            "platform": account.platform,
            "account_id": str(account.id),
            "account_name": account.account_name,
            "status": effective_status,
            "health": health,
            "expires_at": account.expires_at,
            "token_expired": expired,
            "facebook_page_id": account.facebook_page_id,
            "instagram_business_account_id": account.instagram_business_account_id,
            "permissions": permissions,
            "missing_permissions": missing_perms,
            "metadata": metadata,
            "blockers": blockers,
            "publish_ready": publish_ready,
            "implementation": implementation,
        }

    @staticmethod
    async def get_connection_summary(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        configured = meta_oauth_configured()
        accounts = await MetaConnectionService.get_primary_meta_accounts(db, tenant_id)
        fb = accounts.get("facebook")
        ig = accounts.get("instagram")
        fb_health = await MetaConnectionService.evaluate_account_health(fb, live_check=True) if fb else None
        ig_health = await MetaConnectionService.evaluate_account_health(ig, live_check=False) if ig else None

        for account, health in ((fb, fb_health), (ig, ig_health)):
            if account and health and account.status not in ("mock", "disconnected"):
                derived = health["status"]
                if derived != account.status:
                    account.status = derived

        if fb or ig:
            await db.commit()

        connected = bool(
            fb
            and fb.status not in ("disconnected", "mock")
            and fb_health
            and fb_health["status"] == "connected"
        )
        blockers: list[str] = []
        if not configured:
            blockers.append("Meta OAuth not configured (META_APP_ID, META_APP_SECRET, META_OAUTH_REDIRECT_URI)")
        if fb_health:
            blockers.extend(fb_health["blockers"])
        if ig_health:
            blockers.extend(ig_health["blockers"])

        return {
            "oauth_configured": configured,
            "connected": connected,
            "facebook": fb_health,
            "instagram": ig_health,
            "permissions": fb_health["permissions"] if fb_health else [],
            "missing_permissions": list(dict.fromkeys(
                (fb_health or {}).get("missing_permissions", [])
                + (ig_health or {}).get("missing_permissions", []),
            )),
            "expires_at": fb.expires_at if fb else None,
            "token_expired": fb_health["token_expired"] if fb_health else False,
            "health": fb_health["health"] if fb_health else ("not_configured" if not configured else "disconnected"),
            "blockers": list(dict.fromkeys(blockers)),
            "publish_implementation": (
                fb_health.get("implementation", "mock") if fb_health else "mock"
            ),
        }

    @staticmethod
    async def upsert_from_oauth(
        db: AsyncSession,
        tenant_id: UUID,
        connection: dict[str, Any],
    ) -> dict[str, PublishingAccount]:
        page_token = connection["page_access_token"]
        user_token = connection["user_access_token"]
        expires_at = connection.get("page_expires_at") or connection.get("user_expires_at")
        permissions = connection.get("permissions") or []
        metadata = connection.get("metadata") or {}
        metadata.update({
            "facebook_page_name": connection.get("facebook_page_name"),
            "instagram_username": connection.get("instagram_username"),
        })

        shared = {
            "access_token_encrypted": encrypt_token(page_token),
            "refresh_token_encrypted": encrypt_token(user_token),
            "expires_at": expires_at,
            "facebook_page_id": connection.get("facebook_page_id"),
            "instagram_business_account_id": connection.get("instagram_business_account_id"),
            "permissions_json": _dumps_json(permissions),
            "account_metadata_json": _dumps_json(metadata),
            "status": "connected",
        }

        accounts: dict[str, PublishingAccount] = {}
        fb_name = connection.get("facebook_page_name") or "Facebook Page"
        fb = await MetaConnectionService._upsert_platform_account(
            db,
            tenant_id=tenant_id,
            platform="facebook",
            account_name=fb_name,
            account_id=connection["facebook_page_id"],
            shared=shared,
        )
        accounts["facebook"] = fb

        ig_id = connection.get("instagram_business_account_id") or ""
        if ig_id:
            ig_name = connection.get("instagram_username") or "Instagram Business"
            ig = await MetaConnectionService._upsert_platform_account(
                db,
                tenant_id=tenant_id,
                platform="instagram",
                account_name=f"@{ig_name}" if not ig_name.startswith("@") else ig_name,
                account_id=ig_id,
                shared=shared,
            )
            accounts["instagram"] = ig

        await db.commit()
        for account in accounts.values():
            await db.refresh(account)
        return accounts

    @staticmethod
    async def _upsert_platform_account(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        platform: str,
        account_name: str,
        account_id: str,
        shared: dict[str, Any],
    ) -> PublishingAccount:
        result = await db.execute(
            select(PublishingAccount)
            .where(PublishingAccount.tenant_id == tenant_id)
            .where(PublishingAccount.platform == platform)
            .where(PublishingAccount.account_id == account_id)
            .limit(1)
        )
        account = result.scalar_one_or_none()
        if account:
            for key, value in shared.items():
                setattr(account, key, value)
            account.account_name = account_name
            account.updated_at = datetime.now(timezone.utc)
            return account

        account = PublishingAccount(
            tenant_id=tenant_id,
            platform=platform,
            account_name=account_name,
            account_id=account_id,
            **shared,
        )
        db.add(account)
        return account

    @staticmethod
    async def refresh_tokens(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        accounts = await MetaConnectionService.get_primary_meta_accounts(db, tenant_id)
        fb = accounts.get("facebook")
        if not fb or not fb.refresh_token_encrypted:
            raise HTTPException(status_code=400, detail="No connected Meta account to refresh")

        try:
            user_token = decrypt_token(fb.refresh_token_encrypted)
            long_lived = await exchange_for_long_lived_token(user_token)
            new_user_token = long_lived.get("access_token") or user_token
            pages = await get_user_pages(new_user_token)
            page = pick_page(pages) or next(
                (p for p in pages if str(p.get("id")) == fb.facebook_page_id),
                None,
            )
            if not page:
                raise HTTPException(status_code=400, detail="Connected Facebook Page no longer accessible")

            page_token = page.get("access_token") or ""
            from app.services.meta_graph_client import debug_token as graph_debug_token

            user_debug = await graph_debug_token(new_user_token)
            page_debug = await graph_debug_token(page_token) if page_token else {}
            connection = {
                "user_access_token": new_user_token,
                "user_expires_at": MetaConnectionService._expires_from_debug(user_debug),
                "page_access_token": page_token,
                "page_expires_at": MetaConnectionService._expires_from_debug(page_debug),
                "facebook_page_id": str(page.get("id") or fb.facebook_page_id or ""),
                "facebook_page_name": str(page.get("name") or fb.account_name),
                "instagram_business_account_id": str(
                    (page.get("instagram_business_account") or {}).get("id")
                    or fb.instagram_business_account_id
                    or "",
                ),
                "instagram_username": str(
                    (page.get("instagram_business_account") or {}).get("username")
                    or MetaConnectionService.account_metadata(fb).get("instagram_username")
                    or "",
                ),
                "permissions": user_debug.get("scopes") or MetaConnectionService.account_permissions(fb),
                "metadata": MetaConnectionService.account_metadata(fb),
            }
            updated = await MetaConnectionService.upsert_from_oauth(db, tenant_id, connection)
            return {
                "ok": True,
                "message": "Meta tokens refreshed",
                "accounts": {k: str(v.id) for k, v in updated.items()},
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Meta token refresh failed")
            raise HTTPException(status_code=400, detail=f"Meta token refresh failed: {exc}") from exc

    @staticmethod
    def _expires_from_debug(debug_data: dict[str, Any]) -> datetime | None:
        expires_at = debug_data.get("expires_at")
        if expires_at in (None, 0):
            return None
        try:
            return datetime.fromtimestamp(int(expires_at), tz=timezone.utc)
        except (TypeError, ValueError):
            return None

    @staticmethod
    async def disconnect(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        accounts = await MetaConnectionService.list_meta_accounts(db, tenant_id)
        cleared = 0
        for account in accounts:
            if account.status == "mock":
                continue
            account.access_token_encrypted = None
            account.refresh_token_encrypted = None
            account.expires_at = None
            account.facebook_page_id = None
            account.instagram_business_account_id = None
            account.permissions_json = None
            account.account_metadata_json = None
            account.status = "disconnected"
            cleared += 1
        await db.commit()
        return {"ok": True, "message": f"Disconnected {cleared} Meta publishing account(s)"}

    @staticmethod
    def facebook_publish_blockers(account: PublishingAccount) -> list[str]:
        """Publish-time blockers specific to Facebook Page live posts."""
        if account.platform != "facebook" or account.status == "mock":
            return []
        if MetaConnectionService.account_metadata(account).get("demo"):
            return ["Facebook demo account cannot publish live — connect a real Meta account"]
        blockers = MetaConnectionService.readiness_blockers(account)
        if blockers:
            return blockers
        permissions = MetaConnectionService.account_permissions(account)
        missing_publish = missing_facebook_publish_permissions(permissions)
        if missing_publish:
            return [f"Facebook publish permission missing: {', '.join(missing_publish)}"]
        if not account.facebook_page_id:
            return ["Facebook Page ID is missing — reconnect Meta account"]
        if not account.access_token_encrypted:
            return ["Facebook Page access token is missing — reconnect Meta account"]
        if token_is_expired(account.expires_at):
            return ["Meta access token expired — reconnect or refresh the connection"]
        return []

    @staticmethod
    def readiness_blockers(account: PublishingAccount) -> list[str]:
        """Specific publish-safety messages for Meta platforms."""
        if account.status == "mock":
            return []
        if account.status == "disconnected":
            return ["Meta account disconnected — connect Facebook/Instagram in Publishing settings"]
        if token_is_expired(account.expires_at):
            return ["Meta access token expired — reconnect or refresh the connection"]
        if account.status == "invalid":
            return ["Meta access token is invalid — reconnect required"]
        if account.status == "missing_permissions":
            missing = missing_connection_permissions(MetaConnectionService.account_permissions(account))
            if missing:
                return [f"Meta account missing permissions: {', '.join(missing)}"]
            return ["Meta account missing required permissions — reconnect with full scope"]
        if account.platform == "instagram" and not account.instagram_business_account_id:
            return ["Instagram Business account not linked — connect a Page with an Instagram Business profile"]
        if account.platform == "facebook" and not account.facebook_page_id:
            return ["Facebook Page disconnected — reconnect Meta account"]
        if account.status == "blocked":
            return ["Meta publishing account is blocked — reconnect required"]
        if account.status != "connected":
            return [f"Meta account not ready (status={account.status})"]
        return []
