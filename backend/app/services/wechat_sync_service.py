"""WeChat Sync v1 — account registry, contact/conversation import, job tracking (no auto-send)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.communication import CommunicationContact, CommunicationMessage, CommunicationThread
from app.models.crm_lead import CrmLead
from app.models.wechat_sync import WeChatSyncAccount, WeChatSyncJob
from app.services.wechat_adapter import (
    WeChatAdapterContact,
    list_adapter_providers,
    resolve_adapter,
)

logger = logging.getLogger(__name__)

MARKER = "[WeChat Sync]"
SYNC_SOURCE = "wechat_sync"
DEMO_ACCOUNTS = [
    {
        "account_name": "Demo Personal WeChat",
        "account_type": "personal_wechat",
        "status": "connected",
        "provider": "demo",
    },
    {
        "account_name": "Demo WeCom Workspace",
        "account_type": "wecom",
        "status": "connected",
        "provider": "demo",
    },
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _account_config(account: WeChatSyncAccount) -> dict[str, Any]:
    cfg = dict(account.config_json or {})
    cfg["account_type"] = account.account_type
    cfg["account_name"] = account.account_name
    cfg["external_account_id"] = account.external_account_id
    return cfg


def _channel_for_account_type(account_type: str) -> str:
    return "wecom" if account_type == "wecom" else "wechat"


class WeChatSyncService:
    @staticmethod
    async def ensure_demo_accounts(db: AsyncSession) -> None:
        count = await db.scalar(select(func.count()).select_from(WeChatSyncAccount))
        if count and count > 0:
            return
        for spec in DEMO_ACCOUNTS:
            db.add(
                WeChatSyncAccount(
                    account_name=spec["account_name"],
                    account_type=spec["account_type"],
                    status=spec["status"],
                    provider=spec["provider"],
                    config_json={"sync_interval_minutes": 60, "demo": True},
                ),
            )
        await db.commit()
        logger.info("%s seeded %s demo accounts", MARKER, len(DEMO_ACCOUNTS))

    @staticmethod
    async def list_accounts(db: AsyncSession) -> dict[str, Any]:
        await WeChatSyncService.ensure_demo_accounts(db)
        rows = (
            await db.execute(
                select(WeChatSyncAccount).order_by(WeChatSyncAccount.created_at.asc()),
            )
        ).scalars().all()
        return {"items": rows, "total": len(rows)}

    @staticmethod
    async def list_jobs(
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
        status: str | None = None,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        q = select(WeChatSyncJob).order_by(WeChatSyncJob.created_at.desc())
        if status:
            q = q.where(WeChatSyncJob.status == status)
        count_q = select(func.count()).select_from(WeChatSyncJob)
        if status:
            count_q = count_q.where(WeChatSyncJob.status == status)
        total = await db.scalar(count_q) or 0
        rows = (await db.execute(q.offset(skip).limit(limit))).scalars().all()
        account_ids = {j.account_id for j in rows if j.account_id}
        names: dict[UUID, str] = {}
        if account_ids:
            acc_rows = (
                await db.execute(
                    select(WeChatSyncAccount.id, WeChatSyncAccount.account_name).where(
                        WeChatSyncAccount.id.in_(account_ids),
                    ),
                )
            ).all()
            names = {r[0]: r[1] for r in acc_rows}
        items = []
        for job in rows:
            items.append({
                "id": job.id,
                "account_id": job.account_id,
                "account_name": names.get(job.account_id) if job.account_id else None,
                "job_type": job.job_type,
                "trigger": job.trigger,
                "status": job.status,
                "stats_json": job.stats_json,
                "error_message": job.error_message,
                "started_at": job.started_at,
                "completed_at": job.completed_at,
                "created_at": job.created_at,
            })
        return {"items": items, "total": int(total)}

    @staticmethod
    async def status_overview(db: AsyncSession) -> dict[str, Any]:
        await WeChatSyncService.ensure_demo_accounts(db)
        accounts = (await db.execute(select(WeChatSyncAccount))).scalars().all()
        last_sync = max((a.last_sync_at for a in accounts if a.last_sync_at), default=None)
        pending = await db.scalar(
            select(func.count()).select_from(WeChatSyncJob).where(WeChatSyncJob.status == "pending"),
        ) or 0
        cutoff = _utcnow() - timedelta(days=7)
        failed_recent = await db.scalar(
            select(func.count())
            .select_from(WeChatSyncJob)
            .where(
                WeChatSyncJob.status == "failed",
                WeChatSyncJob.created_at >= cutoff,
            ),
        ) or 0
        return {
            "accounts_total": len(accounts),
            "accounts_connected": sum(1 for a in accounts if a.status == "connected"),
            "last_sync_at": last_sync,
            "pending_jobs": int(pending),
            "failed_jobs_recent": int(failed_recent),
            "adapters_available": list_adapter_providers(),
        }

    @staticmethod
    async def _get_account(db: AsyncSession, account_id: UUID | None) -> WeChatSyncAccount:
        if account_id is None:
            row = (
                await db.execute(
                    select(WeChatSyncAccount)
                    .where(WeChatSyncAccount.status == "connected")
                    .order_by(WeChatSyncAccount.created_at.asc())
                    .limit(1),
                )
            ).scalar_one_or_none()
            if not row:
                raise HTTPException(404, "No connected WeChat sync account found")
            return row
        row = await db.get(WeChatSyncAccount, account_id)
        if not row:
            raise HTTPException(404, "WeChat sync account not found")
        return row

    @staticmethod
    async def _create_job(
        db: AsyncSession,
        *,
        account_id: UUID | None,
        job_type: str,
        trigger: str = "manual",
    ) -> WeChatSyncJob:
        job = WeChatSyncJob(
            account_id=account_id,
            job_type=job_type,
            trigger=trigger,
            status="pending",
        )
        db.add(job)
        await db.flush()
        return job

    @staticmethod
    async def _start_job(job: WeChatSyncJob) -> None:
        job.status = "running"
        job.started_at = _utcnow()

    @staticmethod
    async def _complete_job(
        job: WeChatSyncJob,
        *,
        stats: dict[str, Any],
        error: str | None = None,
    ) -> None:
        job.status = "failed" if error else "completed"
        job.stats_json = stats
        job.error_message = error
        job.completed_at = _utcnow()

    @staticmethod
    async def _find_contact_match(
        db: AsyncSession,
        adapter_contact: WeChatAdapterContact,
        channel: str,
    ) -> CommunicationContact | None:
        clauses = []
        if adapter_contact.wechat_id:
            clauses.append(CommunicationContact.wechat_id == adapter_contact.wechat_id)
            clauses.append(CommunicationContact.wechat == adapter_contact.wechat_id)
        if adapter_contact.wecom_id:
            clauses.append(CommunicationContact.wecom_id == adapter_contact.wecom_id)
        if adapter_contact.external_id:
            clauses.append(
                CommunicationContact.notes.contains(f"external_id={adapter_contact.external_id}"),
            )
        if not clauses:
            return None
        return (
            await db.execute(select(CommunicationContact).where(or_(*clauses)).limit(1))
        ).scalar_one_or_none()

    @staticmethod
    def _apply_contact_fields(
        contact: CommunicationContact,
        adapter_contact: WeChatAdapterContact,
        channel: str,
    ) -> bool:
        changed = False
        if adapter_contact.name and contact.name != adapter_contact.name:
            contact.name = adapter_contact.name
            changed = True
        if adapter_contact.wechat_id:
            if contact.wechat_id != adapter_contact.wechat_id:
                contact.wechat_id = adapter_contact.wechat_id
                changed = True
            if not contact.wechat:
                contact.wechat = adapter_contact.wechat_id
                changed = True
        if adapter_contact.wecom_id and contact.wecom_id != adapter_contact.wecom_id:
            contact.wecom_id = adapter_contact.wecom_id
            changed = True
        if adapter_contact.company and not contact.company:
            contact.company = adapter_contact.company
            changed = True
        if adapter_contact.country and not contact.country:
            contact.country = adapter_contact.country
            changed = True
        if adapter_contact.preferred_language and not contact.preferred_language:
            contact.preferred_language = adapter_contact.preferred_language
            changed = True
        marker = f"{MARKER} source={SYNC_SOURCE} channel={channel}"
        ext_note = f"external_id={adapter_contact.external_id}"
        notes = contact.notes or ""
        if marker not in notes:
            contact.notes = f"{notes}\n{marker}\n{ext_note}".strip()
            changed = True
        return changed

    @staticmethod
    async def _link_crm_if_match(
        db: AsyncSession,
        contact: CommunicationContact,
        adapter_contact: WeChatAdapterContact,
    ) -> bool:
        """Link to existing CRM lead only — never auto-create leads."""
        if contact.lead_id:
            return False
        clauses = []
        if adapter_contact.phone:
            clauses.append(CrmLead.phone == adapter_contact.phone)
        if not clauses:
            return False
        lead = (
            await db.execute(select(CrmLead).where(or_(*clauses)).limit(1))
        ).scalar_one_or_none()
        if lead:
            contact.lead_id = lead.id
            return True
        return False

    @staticmethod
    async def sync_contacts(
        db: AsyncSession,
        *,
        account_id: UUID | None = None,
    ) -> dict[str, Any]:
        account = await WeChatSyncService._get_account(db, account_id)
        job = await WeChatSyncService._create_job(
            db, account_id=account.id, job_type="contacts", trigger="manual",
        )
        await WeChatSyncService._start_job(job)
        stats: dict[str, Any] = {
            "imported": 0,
            "updated": 0,
            "deduplicated": 0,
            "crm_linked": 0,
        }
        try:
            adapter = resolve_adapter(account.provider, account.account_type)
            channel = _channel_for_account_type(account.account_type)
            since = account.last_sync_at
            remote = await adapter.fetch_contacts(_account_config(account), since=since)
            for ac in remote:
                existing = await WeChatSyncService._find_contact_match(db, ac, channel)
                if existing:
                    if WeChatSyncService._apply_contact_fields(existing, ac, channel):
                        stats["updated"] += 1
                    else:
                        stats["deduplicated"] += 1
                    if await WeChatSyncService._link_crm_if_match(db, existing, ac):
                        stats["crm_linked"] += 1
                else:
                    contact = CommunicationContact(
                        name=ac.name,
                        wechat_id=ac.wechat_id,
                        wecom_id=ac.wecom_id,
                        wechat=ac.wechat_id,
                        company=ac.company,
                        country=ac.country,
                        preferred_language=ac.preferred_language,
                        notes=f"{MARKER} source={SYNC_SOURCE} channel={channel}\nexternal_id={ac.external_id}",
                    )
                    db.add(contact)
                    await db.flush()
                    stats["imported"] += 1
                    await WeChatSyncService._link_crm_if_match(db, contact, ac)
            account.last_sync_at = _utcnow()
            await WeChatSyncService._complete_job(job, stats=stats)
            await db.commit()
            logger.info("%s contacts sync account=%s stats=%s", MARKER, account.id, stats)
            return {
                "job_id": job.id,
                "status": job.status,
                "stats": stats,
                "message": "Contact sync completed (import/update only, no messaging)",
            }
        except Exception as exc:
            job_id = job.id
            await db.rollback()
            failed_job = await db.get(WeChatSyncJob, job_id)
            if failed_job:
                failed_job.status = "running"
                failed_job.started_at = failed_job.started_at or _utcnow()
                await WeChatSyncService._complete_job(failed_job, stats=stats, error=str(exc)[:500])
                await db.commit()
            logger.exception("%s contacts sync failed", MARKER)
            raise HTTPException(500, f"Contact sync failed: {exc}") from exc

    @staticmethod
    async def _find_thread(
        db: AsyncSession,
        *,
        external_thread_id: str,
        channel: str,
    ) -> CommunicationThread | None:
        return (
            await db.execute(
                select(CommunicationThread).where(
                    CommunicationThread.external_thread_id == external_thread_id,
                    CommunicationThread.channel == channel,
                ).limit(1),
            )
        ).scalar_one_or_none()

    @staticmethod
    async def sync_conversations(
        db: AsyncSession,
        *,
        account_id: UUID | None = None,
    ) -> dict[str, Any]:
        account = await WeChatSyncService._get_account(db, account_id)
        job = await WeChatSyncService._create_job(
            db, account_id=account.id, job_type="conversations", trigger="manual",
        )
        await WeChatSyncService._start_job(job)
        stats: dict[str, Any] = {
            "conversations_imported": 0,
            "conversations_updated": 0,
            "messages_imported": 0,
            "messages_skipped_duplicate": 0,
        }
        try:
            adapter = resolve_adapter(account.provider, account.account_type)
            channel = _channel_for_account_type(account.account_type)
            since = account.last_sync_at
            conversations = await adapter.fetch_conversations(
                _account_config(account), since=since, include_messages=True,
            )
            for conv in conversations:
                contact = None
                if conv.external_contact_id:
                    ac_stub = WeChatAdapterContact(
                        external_id=conv.external_contact_id,
                        name=conv.title.split("—")[0].strip() if "—" in conv.title else conv.title,
                        wechat_id=conv.external_contact_id if channel == "wechat" else None,
                        wecom_id=conv.external_contact_id if channel == "wecom" else None,
                    )
                    contact = await WeChatSyncService._find_contact_match(db, ac_stub, channel)
                    if not contact:
                        contact = CommunicationContact(
                            name=ac_stub.name,
                            wechat_id=ac_stub.wechat_id,
                            wecom_id=ac_stub.wecom_id,
                            wechat=ac_stub.wechat_id,
                            notes=f"{MARKER} source={SYNC_SOURCE} channel={channel}\nexternal_id={conv.external_contact_id}",
                        )
                        db.add(contact)
                        await db.flush()

                thread = await WeChatSyncService._find_thread(
                    db, external_thread_id=conv.external_id, channel=channel,
                )
                if thread:
                    stats["conversations_updated"] += 1
                    thread.title = conv.title
                    thread.last_message_at = conv.last_message_at or thread.last_message_at
                    thread.last_manual_sync_at = _utcnow()
                    if contact and not thread.contact_id:
                        thread.contact_id = contact.id
                else:
                    if not contact:
                        contact = CommunicationContact(
                            name=conv.title,
                            notes=f"{MARKER} source={SYNC_SOURCE} channel={channel}",
                        )
                        db.add(contact)
                        await db.flush()
                    thread = CommunicationThread(
                        contact_id=contact.id,
                        channel=channel,
                        external_thread_id=conv.external_id,
                        external_contact_id=conv.external_contact_id,
                        title=conv.title,
                        status="open",
                        last_message_at=conv.last_message_at,
                        last_manual_sync_at=_utcnow(),
                    )
                    db.add(thread)
                    await db.flush()
                    stats["conversations_imported"] += 1

                existing_msg_ids: set[str] = set()
                if conv.messages:
                    rows = (
                        await db.execute(
                            select(CommunicationMessage.ai_summary).where(
                                CommunicationMessage.thread_id == thread.id,
                            ),
                        )
                    ).scalars().all()
                    for summary in rows:
                        if summary and summary.startswith("ext_id="):
                            existing_msg_ids.add(summary.split("=", 1)[1].split()[0])

                for msg in conv.messages:
                    if msg.external_id in existing_msg_ids:
                        stats["messages_skipped_duplicate"] += 1
                        continue
                    if msg.direction != "inbound":
                        continue
                    db.add(
                        CommunicationMessage(
                            thread_id=thread.id,
                            direction="inbound",
                            sender_name=msg.sender_name,
                            message_text=msg.message_text,
                            ai_summary=f"ext_id={msg.external_id} {MARKER}",
                            created_at=msg.sent_at or _utcnow(),
                        ),
                    )
                    stats["messages_imported"] += 1

            account.last_sync_at = _utcnow()
            await WeChatSyncService._complete_job(job, stats=stats)
            await db.commit()
            logger.info("%s conversations sync account=%s stats=%s", MARKER, account.id, stats)
            return {
                "job_id": job.id,
                "status": job.status,
                "stats": stats,
                "message": "Conversation sync completed (inbound import only, no outbound send)",
            }
        except Exception as exc:
            job_id = job.id
            await db.rollback()
            failed_job = await db.get(WeChatSyncJob, job_id)
            if failed_job:
                failed_job.status = "running"
                failed_job.started_at = failed_job.started_at or _utcnow()
                await WeChatSyncService._complete_job(failed_job, stats=stats, error=str(exc)[:500])
                await db.commit()
            logger.exception("%s conversations sync failed", MARKER)
            raise HTTPException(500, f"Conversation sync failed: {exc}") from exc

    @staticmethod
    async def test_connection(
        db: AsyncSession,
        *,
        account_id: UUID,
    ) -> dict[str, Any]:
        account = await WeChatSyncService._get_account(db, account_id)
        job = await WeChatSyncService._create_job(
            db, account_id=account.id, job_type="test_connection", trigger="manual",
        )
        await WeChatSyncService._start_job(job)
        adapter = resolve_adapter(account.provider, account.account_type)
        result = await adapter.test_connection(_account_config(account))
        stats = {"ok": result.ok, "provider": result.provider, "latency_ms": result.latency_ms}
        if result.ok:
            account.status = "connected"
            if not account.provider:
                account.provider = result.provider
        else:
            account.status = "error"
        await WeChatSyncService._complete_job(
            job,
            stats=stats,
            error=None if result.ok else result.message,
        )
        await db.commit()
        return {
            "job_id": job.id,
            "ok": result.ok,
            "provider": result.provider,
            "message": result.message,
            "latency_ms": result.latency_ms,
            "details": result.details,
        }

    @staticmethod
    async def enqueue_scheduled_syncs(db: AsyncSession) -> list[UUID]:
        """Scheduled sync framework — creates pending jobs only; execution is separate."""
        await WeChatSyncService.ensure_demo_accounts(db)
        now = _utcnow()
        job_ids: list[UUID] = []
        accounts = (
            await db.execute(
                select(WeChatSyncAccount).where(WeChatSyncAccount.status == "connected"),
            )
        ).scalars().all()
        for account in accounts:
            cfg = account.config_json or {}
            interval = int(cfg.get("sync_interval_minutes") or 0)
            if interval <= 0:
                continue
            due = (
                account.last_sync_at is None
                or account.last_sync_at + timedelta(minutes=interval) <= now
            )
            if not due:
                continue
            for job_type in ("scheduled_contacts", "scheduled_conversations"):
                pending = await db.scalar(
                    select(func.count())
                    .select_from(WeChatSyncJob)
                    .where(
                        WeChatSyncJob.account_id == account.id,
                        WeChatSyncJob.job_type == job_type,
                        WeChatSyncJob.status == "pending",
                    ),
                )
                if pending:
                    continue
                job = await WeChatSyncService._create_job(
                    db,
                    account_id=account.id,
                    job_type=job_type,
                    trigger="scheduled",
                )
                job_ids.append(job.id)
        if job_ids:
            await db.commit()
            logger.info("%s enqueued %s scheduled jobs", MARKER, len(job_ids))
        return job_ids
