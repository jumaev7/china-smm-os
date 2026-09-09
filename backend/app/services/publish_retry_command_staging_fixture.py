"""Staging-only synthetic fixture builder (Phase 3C.1C-D2-B2a).

Requires VerifiedRetryCommandStagingContext. Cannot mutate production DB.
Creates synthetic tenant / content / account / failed attempt / pending or
claimed retry command with unmistakable staging markers.

NO provider credentials. NO public API. NO production IDs copied.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.publish_retry_command_eligibility import (
    STAGING_CORRELATION_ID_PREFIX,
    STAGING_TENANT_NAME_PREFIX,
)
from app.services.publish_retry_command_staging_identity import (
    REQUIRED_DATABASE_NAME,
    StagingIdentityError,
    VerifiedRetryCommandStagingContext,
    assert_verified_staging_context,
    query_current_database,
)


@dataclass(frozen=True, slots=True)
class StagingRetryFixture:
    """IDs for a synthetic staging retry-command campaign."""

    tenant_id: UUID
    client_id: UUID
    content_id: UUID
    account_id: UUID
    original_attempt_id: UUID
    command_id: UUID
    correlation_id: str
    tenant_name: str
    worker_id: str
    platform: str = "telegram"
    publish_version: str = "1"
    destination_key: str = ""
    idempotency_key: str = ""


class PublishRetryCommandStagingFixtureBuilder:
    """Create synthetic retry fixtures only under verified staging identity."""

    def __init__(self, staging_context: VerifiedRetryCommandStagingContext) -> None:
        self._staging = assert_verified_staging_context(
            staging_context,
            what="PublishRetryCommandStagingFixtureBuilder",
        )

    @property
    def staging_context(self) -> VerifiedRetryCommandStagingContext:
        return self._staging

    async def create(
        self,
        db: AsyncSession,
        *,
        platform: str = "telegram",
        command_status: str = "pending",
        worker_id: str | None = None,
        lease_seconds: int = 180,
        commit: bool = True,
    ) -> StagingRetryFixture:
        """Atomically create synthetic rows. Fail closed if DB identity drifts."""
        current = await query_current_database(db)
        if current != REQUIRED_DATABASE_NAME:
            raise StagingIdentityError(
                "current_database_not_staging",
                detail=f"fixture builder saw current_database()={current!r}",
            )
        if current != self._staging.current_database:
            raise StagingIdentityError(
                "staging_capability_db_mismatch",
                detail="verified context DB does not match live connection",
            )

        tenant_id = uuid4()
        client_id = uuid4()
        content_id = uuid4()
        account_id = uuid4()
        original_attempt_id = uuid4()
        command_id = uuid4()
        suffix = str(uuid4())[:8]
        tenant_name = f"{STAGING_TENANT_NAME_PREFIX}{suffix}"
        correlation_id = f"{STAGING_CORRELATION_ID_PREFIX}{uuid4()}"
        # correlation_id column is String(64)
        correlation_id = correlation_id[:64]
        worker = worker_id or f"staging-harness:1:{uuid4()}"
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=max(30, int(lease_seconds)))
        publish_version = "1"
        destination_key = f"{platform}:{account_id}"
        cmd_idem = f"staging-cmd:{command_id}"
        attempt_idem = f"staging-orig:{original_attempt_id}"

        has_company = await _tenants_has_column(db, "company_name")
        has_name = await _tenants_has_column(db, "name")

        if has_company and has_name:
            await db.execute(
                text(
                    "INSERT INTO tenants (id, company_name, name, status, plan) "
                    "VALUES (:id, :cname, :name, 'active', 'starter')"
                ),
                {"id": tenant_id, "cname": tenant_name, "name": tenant_name},
            )
        elif has_company:
            await db.execute(
                text(
                    "INSERT INTO tenants (id, company_name, status, plan) "
                    "VALUES (:id, :name, 'active', 'starter')"
                ),
                {"id": tenant_id, "name": tenant_name},
            )
        elif has_name:
            await db.execute(
                text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
                {"id": tenant_id, "name": tenant_name},
            )
        else:
            raise StagingIdentityError(
                "tenants_schema_unsupported",
                detail="tenants table needs company_name or name",
            )

        await db.execute(
            text(
                "INSERT INTO clients (id, tenant_id, company_name) "
                "VALUES (:id, :tenant_id, :name)"
            ),
            {"id": client_id, "tenant_id": tenant_id, "name": tenant_name},
        )
        await db.execute(
            text(
                """
                INSERT INTO content_items
                    (id, client_id, status, platforms, updated_at)
                VALUES
                    (:id, :client_id, 'failed', ARRAY[:platform]::varchar[], :now)
                """
            ),
            {
                "id": content_id,
                "client_id": client_id,
                "platform": platform,
                "now": now,
            },
        )
        # No Meta/Telegram tokens or OAuth credentials.
        await db.execute(
            text(
                """
                INSERT INTO publishing_accounts
                    (id, tenant_id, platform, account_name, account_id, status)
                VALUES
                    (:id, :tenant_id, :platform, :account_name, :account_ext, 'mock')
                """
            ),
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "platform": platform,
                "account_name": f"{STAGING_TENANT_NAME_PREFIX}account-{suffix}",
                "account_ext": f"staging-fake-account-{suffix}",
            },
        )
        await db.execute(
            text(
                """
                INSERT INTO publish_attempts (
                    id, content_id, platform, account_id, status, failure_code,
                    publish_version, attempt_number, idempotency_key, retryable,
                    error
                ) VALUES (
                    :id, :content_id, :platform, :account_id, 'failed',
                    'provider_unavailable', :pv, 1, :ikey, true,
                    'staging synthetic original failure'
                )
                """
            ),
            {
                "id": original_attempt_id,
                "content_id": content_id,
                "platform": platform,
                "account_id": account_id,
                "pv": publish_version,
                "ikey": attempt_idem,
            },
        )

        lease_owner = worker if command_status == "claimed" else None
        lease_exp = lease_expires if command_status == "claimed" else None
        claimed_at = now if command_status == "claimed" else None
        await db.execute(
            text(
                """
                INSERT INTO publish_retry_commands (
                    id, tenant_id, client_id, content_id, original_attempt_id,
                    resulting_attempt_id, platform, publishing_account_id,
                    publish_version, destination_key, requested_source,
                    idempotency_key, status, provider_outcome, lease_owner,
                    lease_expires_at, claimed_at, started_at,
                    provider_write_started_at, finished_at, correlation_id
                ) VALUES (
                    :id, :tid, :cid, :content_id, :orig,
                    NULL, :platform, :acct,
                    :pv, :dest, 'admin',
                    :ikey, :status, NULL, :owner,
                    :lease_expires, :claimed_at, :started_at,
                    NULL, NULL, :corr
                )
                """
            ),
            {
                "id": command_id,
                "tid": tenant_id,
                "cid": client_id,
                "content_id": content_id,
                "orig": original_attempt_id,
                "platform": platform,
                "acct": account_id,
                "pv": publish_version,
                "dest": destination_key,
                "ikey": cmd_idem,
                "status": command_status,
                "owner": lease_owner,
                "lease_expires": lease_exp,
                "claimed_at": claimed_at,
                "started_at": claimed_at,
                "corr": correlation_id,
            },
        )

        if commit:
            await db.commit()
        else:
            await db.flush()

        return StagingRetryFixture(
            tenant_id=tenant_id,
            client_id=client_id,
            content_id=content_id,
            account_id=account_id,
            original_attempt_id=original_attempt_id,
            command_id=command_id,
            correlation_id=correlation_id,
            tenant_name=tenant_name,
            worker_id=worker,
            platform=platform,
            publish_version=publish_version,
            destination_key=destination_key,
            idempotency_key=cmd_idem,
        )


async def _tenants_has_column(db: AsyncSession, column: str) -> bool:
    row = (
        await db.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'tenants'
                  AND column_name = :col
                LIMIT 1
                """
            ),
            {"col": column},
        )
    ).first()
    return row is not None
