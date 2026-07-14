"""CRUD for publishing accounts (mock and future real connectors)."""
from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.publishing_account import PublishingAccount, ACCOUNT_STATUSES, PLATFORMS
from app.schemas.publishing import MOCK_ACCOUNT_LABELS, PublishingAccountCreate, PublishingAccountUpdate
from app.services.automation_domain_events import INTEGRATION_ATTENTION_STATUSES
from app.services.meta_connection_service import MetaConnectionService
from app.services.meta_graph_client import token_is_expired
from app.utils.telegram_publish_destination import validate_telegram_publish_chat_id

ACTIVE_STATUSES = frozenset({"connected", "mock"})


class PublishingAccountService:
    @staticmethod
    def _tenant_clause(tenant_id: UUID):
        return PublishingAccount.tenant_id == tenant_id

    @staticmethod
    def _serialize(account: PublishingAccount) -> dict:
        permissions = MetaConnectionService.account_permissions(account)
        metadata = MetaConnectionService.account_metadata(account)
        expired = token_is_expired(account.expires_at)
        health = None
        missing_permissions: list[str] = []
        if MetaConnectionService.is_meta_platform(account.platform) and account.status != "mock":
            from app.services.meta_graph_client import missing_connection_permissions

            missing_permissions = missing_connection_permissions(permissions)
            if account.status == "disconnected":
                health = "disconnected"
            elif expired:
                health = "expired"
            elif account.status == "missing_permissions" or missing_permissions:
                health = "missing_permissions"
            elif account.status == "invalid":
                health = "unhealthy"
            elif account.status == "connected":
                health = "healthy"
            else:
                health = account.status
        return {
            "id": account.id,
            "tenant_id": account.tenant_id,
            "platform": account.platform,
            "account_name": account.account_name,
            "account_id": account.account_id,
            "status": account.status,
            "expires_at": account.expires_at,
            "facebook_page_id": account.facebook_page_id,
            "instagram_business_account_id": account.instagram_business_account_id,
            "permissions": permissions,
            "account_metadata": metadata,
            "token_expired": expired,
            "health": health,
            "missing_permissions": missing_permissions,
            "created_at": account.created_at,
            "updated_at": account.updated_at,
        }

    @staticmethod
    async def list_all(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        platform: str | None = None,
        status: str | None = None,
    ) -> tuple[list[PublishingAccount], int]:
        tenant_filter = PublishingAccountService._tenant_clause(tenant_id)
        query = (
            select(PublishingAccount)
            .where(tenant_filter)
            .order_by(PublishingAccount.platform, PublishingAccount.created_at)
        )
        count_q = select(func.count()).select_from(PublishingAccount).where(tenant_filter)
        if platform:
            query = query.where(PublishingAccount.platform == platform)
            count_q = count_q.where(PublishingAccount.platform == platform)
        if status:
            query = query.where(PublishingAccount.status == status)
            count_q = count_q.where(PublishingAccount.status == status)
        total = (await db.execute(count_q)).scalar() or 0
        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def get(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> PublishingAccount:
        result = await db.execute(
            select(PublishingAccount).where(
                PublishingAccount.id == account_id,
                PublishingAccountService._tenant_clause(tenant_id),
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=404, detail="Publishing account not found")
        return account

    @staticmethod
    async def create(
        db: AsyncSession,
        tenant_id: UUID,
        data: PublishingAccountCreate,
    ) -> PublishingAccount:
        if data.platform not in PLATFORMS:
            raise HTTPException(status_code=400, detail=f"Unsupported platform: {data.platform}")

        if data.mock or data.status == "mock":
            account_name = data.account_name or MOCK_ACCOUNT_LABELS.get(data.platform, f"{data.platform.title()} Mock")
            account_id = data.account_id or f"mock-{data.platform}-{secrets.token_hex(4)}"
            status = "mock"
        else:
            if not data.account_name or not data.account_id:
                raise HTTPException(status_code=400, detail="account_name and account_id are required")
            account_name = data.account_name.strip()
            account_id = data.account_id.strip()
            if data.platform == "telegram":
                try:
                    account_id = validate_telegram_publish_chat_id(account_id) or account_id
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            status = data.status if data.status in ACCOUNT_STATUSES else "connected"

        account = PublishingAccount(
            tenant_id=tenant_id,
            platform=data.platform,
            account_name=account_name,
            account_id=account_id,
            access_token_encrypted=data.access_token_encrypted,
            status=status,
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account

    @staticmethod
    async def update(
        db: AsyncSession,
        tenant_id: UUID,
        account_id: UUID,
        data: PublishingAccountUpdate,
    ) -> PublishingAccount:
        account = await PublishingAccountService.get(db, tenant_id, account_id)
        previous_status = account.status
        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            if field == "status" and value not in ACCOUNT_STATUSES:
                raise HTTPException(status_code=400, detail=f"Invalid status: {value}")
            setattr(account, field, value)
        new_status = account.status
        if (
            "status" in updates
            and new_status != previous_status
            and new_status in INTEGRATION_ATTENTION_STATUSES
        ):
            await MetaConnectionService._emit_disconnected(
                db,
                account,
                previous_status=previous_status,
                disconnect_reason="user_status_update",
                requires_reauthorization=new_status != "disconnected" or previous_status != "disconnected",
                disconnect_kind="user_initiated",
            )
        await db.commit()
        await db.refresh(account)
        return account

    @staticmethod
    async def delete(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> None:
        account = await PublishingAccountService.get(db, tenant_id, account_id)
        previous_status = account.status
        if previous_status != "disconnected" and previous_status != "mock":
            account.status = "disconnected"
            await MetaConnectionService._emit_disconnected(
                db,
                account,
                previous_status=previous_status,
                disconnect_reason="account_deleted",
                requires_reauthorization=False,
                disconnect_kind="user_initiated",
            )
        await db.delete(account)
        await db.commit()

    @staticmethod
    async def find_telegram_account_by_chat_id(
        db: AsyncSession,
        tenant_id: UUID,
        chat_id: str,
    ) -> PublishingAccount | None:
        normalized = validate_telegram_publish_chat_id(chat_id)
        if not normalized:
            return None
        result = await db.execute(
            select(PublishingAccount)
            .where(PublishingAccountService._tenant_clause(tenant_id))
            .where(PublishingAccount.platform == "telegram")
            .where(PublishingAccount.status.in_(tuple(ACTIVE_STATUSES)))
            .where(PublishingAccount.account_id == normalized)
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _default_platform_account(
        db: AsyncSession,
        tenant_id: UUID,
        platform: str,
    ) -> PublishingAccount:
        result = await db.execute(
            select(PublishingAccount)
            .where(PublishingAccountService._tenant_clause(tenant_id))
            .where(PublishingAccount.platform == platform)
            .where(PublishingAccount.status.in_(tuple(ACTIVE_STATUSES)))
            .order_by(PublishingAccount.created_at)
            .limit(1)
        )
        account = result.scalar_one_or_none()
        if not account:
            if MetaConnectionService.is_meta_platform(platform):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"No connected Meta publishing account for {platform} in this tenant. "
                        "Connect Facebook/Instagram in Publishing settings."
                    ),
                )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No connected or mock publishing account for {platform} in this tenant. "
                    "Add one in Publishing settings."
                ),
            )
        return account

    @staticmethod
    async def resolve_for_platform(
        db: AsyncSession,
        tenant_id: UUID,
        platform: str,
        account_id: UUID | None = None,
        *,
        client_publish_chat_id: str | None = None,
    ) -> PublishingAccount:
        if account_id:
            account = await PublishingAccountService.get(db, tenant_id, account_id)
            if account.platform != platform:
                raise HTTPException(
                    status_code=400,
                    detail=f"Account {account_id} is for {account.platform}, not {platform}",
                )
            if account.status not in ACTIVE_STATUSES:
                if MetaConnectionService.is_meta_platform(platform):
                    blockers = MetaConnectionService.readiness_blockers(account)
                    detail = blockers[0] if blockers else (
                        f"Account {account.account_name} is not ready (status={account.status})"
                    )
                    raise HTTPException(status_code=400, detail=detail)
                raise HTTPException(
                    status_code=400,
                    detail=f"Account {account.account_name} is not connected (status={account.status})",
                )
            return account

        if platform == "telegram" and client_publish_chat_id:
            matched = await PublishingAccountService.find_telegram_account_by_chat_id(
                db, tenant_id, client_publish_chat_id,
            )
            if matched:
                return matched
            return await PublishingAccountService._default_platform_account(db, tenant_id, platform)

        return await PublishingAccountService._default_platform_account(db, tenant_id, platform)
