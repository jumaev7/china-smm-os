"""WhatsApp Sync v1 — account registry, contact/conversation import, job tracking (no auto-send)."""
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
from app.models.whatsapp import WhatsAppContact, WhatsAppMessage, WhatsAppThread
from app.models.whatsapp_sync import WhatsAppSyncAccount, WhatsAppSyncJob
from app.services.whatsapp_adapter import (
    WhatsAppAdapterContact,
    list_adapter_providers,
    resolve_adapter,
)

logger = logging.getLogger(__name__)

MARKER = "[WhatsApp Sync]"
SYNC_SOURCE = "whatsapp_sync"
CHANNEL = "whatsapp"
DEMO_ACCOUNTS = [
    {
        "account_name": "Demo WhatsApp Cloud API",
        "account_type": "whatsapp_cloud_api",
        "status": "connected",
        "provider": "demo",
        "phone_number": "+10000000001",
    },
    {
        "account_name": "Demo WhatsApp Business API",
        "account_type": "whatsapp_business_api",
        "status": "connected",
        "provider": "demo",
        "phone_number": "+10000000002",
    },
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _account_config(account: WhatsAppSyncAccount) -> dict[str, Any]:
    cfg = dict(account.config_json or {})
    cfg["account_type"] = account.account_type
    cfg["account_name"] = account.account_name
    cfg["phone_number"] = account.phone_number
    cfg["external_account_id"] = account.external_account_id
    return cfg


def _ext_msg_marker(external_id: str) -> str:
    return f"{MARKER} ext_id={external_id}"


class WhatsAppSyncService:
    @staticmethod
    async def ensure_demo_accounts(db: AsyncSession) -> None:
        count = await db.scalar(select(func.count()).select_from(WhatsAppSyncAccount))
        if count and count > 0:
            return
        for spec in DEMO_ACCOUNTS:
            db.add(
                WhatsAppSyncAccount(
                    account_name=spec["account_name"],
                    account_type=spec["account_type"],
                    status=spec["status"],
                    provider=spec["provider"],
                    phone_number=spec["phone_number"],
                    config_json={"sync_interval_minutes": 60, "demo": True},
                ),
            )
        await db.commit()
        logger.info("%s seeded %s demo accounts", MARKER, len(DEMO_ACCOUNTS))

    @staticmethod
    async def list_accounts(db: AsyncSession) -> dict[str, Any]:
        await WhatsAppSyncService.ensure_demo_accounts(db)
        rows = (
            await db.execute(
                select(WhatsAppSyncAccount).order_by(WhatsAppSyncAccount.created_at.asc()),
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
        q = select(WhatsAppSyncJob).order_by(WhatsAppSyncJob.created_at.desc())
        if status:
            q = q.where(WhatsAppSyncJob.status == status)
        count_q = select(func.count()).select_from(WhatsAppSyncJob)
        if status:
            count_q = count_q.where(WhatsAppSyncJob.status == status)
        total = await db.scalar(count_q) or 0
        rows = (await db.execute(q.offset(skip).limit(limit))).scalars().all()
        account_ids = {j.account_id for j in rows if j.account_id}
        names: dict[UUID, str] = {}
        if account_ids:
            acc_rows = (
                await db.execute(
                    select(WhatsAppSyncAccount.id, WhatsAppSyncAccount.account_name).where(
                        WhatsAppSyncAccount.id.in_(account_ids),
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
        await WhatsAppSyncService.ensure_demo_accounts(db)
        accounts = (await db.execute(select(WhatsAppSyncAccount))).scalars().all()
        last_sync = max((a.last_sync_at for a in accounts if a.last_sync_at), default=None)
        pending = await db.scalar(
            select(func.count()).select_from(WhatsAppSyncJob).where(WhatsAppSyncJob.status == "pending"),
        ) or 0
        cutoff = _utcnow() - timedelta(days=7)
        failed_recent = await db.scalar(
            select(func.count())
            .select_from(WhatsAppSyncJob)
            .where(
                WhatsAppSyncJob.status == "failed",
                WhatsAppSyncJob.created_at >= cutoff,
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
    async def _get_account(db: AsyncSession, account_id: UUID | None) -> WhatsAppSyncAccount:
        if account_id is None:
            row = (
                await db.execute(
                    select(WhatsAppSyncAccount)
                    .where(WhatsAppSyncAccount.status == "connected")
                    .order_by(WhatsAppSyncAccount.created_at.asc())
                    .limit(1),
                )
            ).scalar_one_or_none()
            if not row:
                raise HTTPException(404, "No connected WhatsApp sync account found")
            return row
        row = await db.get(WhatsAppSyncAccount, account_id)
        if not row:
            raise HTTPException(404, "WhatsApp sync account not found")
        return row

    @staticmethod
    async def _create_job(
        db: AsyncSession,
        *,
        account_id: UUID | None,
        job_type: str,
        trigger: str = "manual",
    ) -> WhatsAppSyncJob:
        job = WhatsAppSyncJob(
            account_id=account_id,
            job_type=job_type,
            trigger=trigger,
            status="pending",
        )
        db.add(job)
        await db.flush()
        return job

    @staticmethod
    async def _start_job(job: WhatsAppSyncJob) -> None:
        job.status = "running"
        job.started_at = _utcnow()

    @staticmethod
    async def _complete_job(
        job: WhatsAppSyncJob,
        *,
        stats: dict[str, Any],
        error: str | None = None,
    ) -> None:
        job.status = "failed" if error else "completed"
        job.stats_json = stats
        job.error_message = error
        job.completed_at = _utcnow()

    @staticmethod
    async def _find_hub_contact(
        db: AsyncSession,
        adapter_contact: WhatsAppAdapterContact,
    ) -> CommunicationContact | None:
        clauses = []
        if adapter_contact.phone:
            clauses.append(CommunicationContact.phone == adapter_contact.phone)
            clauses.append(CommunicationContact.whatsapp == adapter_contact.phone)
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
    async def _find_wa_center_contact(
        db: AsyncSession,
        phone: str | None,
    ) -> WhatsAppContact | None:
        if not phone:
            return None
        return (
            await db.execute(
                select(WhatsAppContact).where(WhatsAppContact.phone == phone).limit(1),
            )
        ).scalar_one_or_none()

    @staticmethod
    def _apply_hub_contact_fields(
        contact: CommunicationContact,
        adapter_contact: WhatsAppAdapterContact,
    ) -> bool:
        changed = False
        if adapter_contact.name and contact.name != adapter_contact.name:
            contact.name = adapter_contact.name
            changed = True
        if adapter_contact.phone:
            if contact.phone != adapter_contact.phone:
                contact.phone = adapter_contact.phone
                changed = True
            if contact.whatsapp != adapter_contact.phone:
                contact.whatsapp = adapter_contact.phone
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
        marker = f"{MARKER} source={SYNC_SOURCE} channel={CHANNEL}"
        ext_note = f"external_id={adapter_contact.external_id}"
        notes = contact.notes or ""
        if marker not in notes:
            contact.notes = f"{notes}\n{marker}\n{ext_note}".strip()
            changed = True
        return changed

    @staticmethod
    async def _upsert_wa_center_contact(
        db: AsyncSession,
        adapter_contact: WhatsAppAdapterContact,
        *,
        crm_client_id: UUID | None = None,
    ) -> tuple[WhatsAppContact, bool]:
        """Return contact and whether it was newly created."""
        if not adapter_contact.phone:
            name = adapter_contact.name
            contact = WhatsAppContact(
                phone=f"sync:{adapter_contact.external_id}",
                display_name=name,
                company=adapter_contact.company,
                country=adapter_contact.country,
                crm_client_id=crm_client_id,
            )
            db.add(contact)
            await db.flush()
            return contact, True
        existing = await WhatsAppSyncService._find_wa_center_contact(db, adapter_contact.phone)
        if existing:
            changed = False
            if adapter_contact.name and existing.display_name != adapter_contact.name:
                existing.display_name = adapter_contact.name
                changed = True
            if adapter_contact.company and not existing.company:
                existing.company = adapter_contact.company
                changed = True
            if adapter_contact.country and not existing.country:
                existing.country = adapter_contact.country
                changed = True
            if crm_client_id and not existing.crm_client_id:
                existing.crm_client_id = crm_client_id
                changed = True
            return existing, False if not changed else False
        contact = WhatsAppContact(
            phone=adapter_contact.phone,
            display_name=adapter_contact.name,
            company=adapter_contact.company,
            country=adapter_contact.country,
            crm_client_id=crm_client_id,
        )
        db.add(contact)
        await db.flush()
        return contact, True

    @staticmethod
    async def _link_crm_if_match(
        db: AsyncSession,
        contact: CommunicationContact,
        adapter_contact: WhatsAppAdapterContact,
    ) -> bool:
        """Link to existing CRM lead only — never auto-create leads or clients."""
        if contact.lead_id:
            return False
        if not adapter_contact.phone:
            return False
        lead = (
            await db.execute(
                select(CrmLead).where(CrmLead.phone == adapter_contact.phone).limit(1),
            )
        ).scalar_one_or_none()
        if lead:
            contact.lead_id = lead.id
            if not contact.client_id:
                contact.client_id = lead.client_id
            return True
        return False

    @staticmethod
    async def sync_contacts(
        db: AsyncSession,
        *,
        account_id: UUID | None = None,
    ) -> dict[str, Any]:
        account = await WhatsAppSyncService._get_account(db, account_id)
        job = await WhatsAppSyncService._create_job(
            db, account_id=account.id, job_type="contacts", trigger="manual",
        )
        await WhatsAppSyncService._start_job(job)
        stats: dict[str, Any] = {
            "imported": 0,
            "updated": 0,
            "deduplicated": 0,
            "crm_linked": 0,
            "wa_center_imported": 0,
            "wa_center_updated": 0,
        }
        try:
            adapter = resolve_adapter(account.provider, account.account_type)
            since = account.last_sync_at
            remote = await adapter.fetch_contacts(_account_config(account), since=since)
            for ac in remote:
                crm_client_id = None
                existing = await WhatsAppSyncService._find_hub_contact(db, ac)
                if existing:
                    if WhatsAppSyncService._apply_hub_contact_fields(existing, ac):
                        stats["updated"] += 1
                    else:
                        stats["deduplicated"] += 1
                    if await WhatsAppSyncService._link_crm_if_match(db, existing, ac):
                        stats["crm_linked"] += 1
                        if existing.client_id:
                            crm_client_id = existing.client_id
                else:
                    contact = CommunicationContact(
                        name=ac.name,
                        phone=ac.phone,
                        whatsapp=ac.phone,
                        company=ac.company,
                        country=ac.country,
                        preferred_language=ac.preferred_language,
                        notes=f"{MARKER} source={SYNC_SOURCE} channel={CHANNEL}\nexternal_id={ac.external_id}",
                    )
                    db.add(contact)
                    await db.flush()
                    stats["imported"] += 1
                    if await WhatsAppSyncService._link_crm_if_match(db, contact, ac):
                        stats["crm_linked"] += 1
                    if contact.client_id:
                        crm_client_id = contact.client_id

                wa_contact, created = await WhatsAppSyncService._upsert_wa_center_contact(
                    db, ac, crm_client_id=crm_client_id,
                )
                if created:
                    stats["wa_center_imported"] += 1
                else:
                    stats["wa_center_updated"] += 1
                _ = wa_contact

            account.last_sync_at = _utcnow()
            await WhatsAppSyncService._complete_job(job, stats=stats)
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
            failed_job = await db.get(WhatsAppSyncJob, job_id)
            if failed_job:
                failed_job.status = "running"
                failed_job.started_at = failed_job.started_at or _utcnow()
                await WhatsAppSyncService._complete_job(failed_job, stats=stats, error=str(exc)[:500])
                await db.commit()
            logger.exception("%s contacts sync failed", MARKER)
            raise HTTPException(500, f"Contact sync failed: {exc}") from exc

    @staticmethod
    async def _find_hub_thread(
        db: AsyncSession,
        *,
        external_thread_id: str,
    ) -> CommunicationThread | None:
        return (
            await db.execute(
                select(CommunicationThread).where(
                    CommunicationThread.external_thread_id == external_thread_id,
                    CommunicationThread.channel == CHANNEL,
                ).limit(1),
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _find_or_create_wa_thread(
        db: AsyncSession,
        wa_contact: WhatsAppContact,
    ) -> WhatsAppThread:
        row = (
            await db.execute(
                select(WhatsAppThread)
                .where(WhatsAppThread.contact_id == wa_contact.id)
                .order_by(WhatsAppThread.created_at.desc())
                .limit(1),
            )
        ).scalar_one_or_none()
        if row:
            return row
        thread = WhatsAppThread(contact_id=wa_contact.id, unread_count=0)
        db.add(thread)
        await db.flush()
        return thread

    @staticmethod
    async def sync_conversations(
        db: AsyncSession,
        *,
        account_id: UUID | None = None,
    ) -> dict[str, Any]:
        account = await WhatsAppSyncService._get_account(db, account_id)
        job = await WhatsAppSyncService._create_job(
            db, account_id=account.id, job_type="conversations", trigger="manual",
        )
        await WhatsAppSyncService._start_job(job)
        stats: dict[str, Any] = {
            "conversations_imported": 0,
            "conversations_updated": 0,
            "messages_imported": 0,
            "messages_skipped_duplicate": 0,
            "wa_messages_imported": 0,
        }
        try:
            adapter = resolve_adapter(account.provider, account.account_type)
            since = account.last_sync_at
            conversations = await adapter.fetch_conversations(
                _account_config(account), since=since, include_messages=True,
            )
            for conv in conversations:
                ac_stub = WhatsAppAdapterContact(
                    external_id=conv.external_contact_id or conv.external_id,
                    name=conv.title.split("—")[0].strip() if "—" in conv.title else conv.title,
                    phone=conv.phone,
                )
                hub_contact = await WhatsAppSyncService._find_hub_contact(db, ac_stub)
                if not hub_contact:
                    hub_contact = CommunicationContact(
                        name=ac_stub.name,
                        phone=ac_stub.phone,
                        whatsapp=ac_stub.phone,
                        notes=f"{MARKER} source={SYNC_SOURCE} channel={CHANNEL}\nexternal_id={ac_stub.external_id}",
                    )
                    db.add(hub_contact)
                    await db.flush()
                    await WhatsAppSyncService._link_crm_if_match(db, hub_contact, ac_stub)

                wa_contact, _ = await WhatsAppSyncService._upsert_wa_center_contact(
                    db, ac_stub, crm_client_id=hub_contact.client_id,
                )
                wa_thread = await WhatsAppSyncService._find_or_create_wa_thread(db, wa_contact)

                thread = await WhatsAppSyncService._find_hub_thread(
                    db, external_thread_id=conv.external_id,
                )
                if thread:
                    stats["conversations_updated"] += 1
                    thread.title = conv.title
                    thread.last_message_at = conv.last_message_at or thread.last_message_at
                    thread.last_manual_sync_at = _utcnow()
                    if not thread.contact_id:
                        thread.contact_id = hub_contact.id
                else:
                    thread = CommunicationThread(
                        contact_id=hub_contact.id,
                        channel=CHANNEL,
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

                if conv.last_message_at:
                    wa_thread.last_message_at = conv.last_message_at

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

                    wa_rows = (
                        await db.execute(
                            select(WhatsAppMessage.content).where(
                                WhatsAppMessage.thread_id == wa_thread.id,
                            ),
                        )
                    ).scalars().all()
                    for content in wa_rows:
                        if content and MARKER in content and "ext_id=" in content:
                            part = content.split("ext_id=", 1)[-1].split()[0]
                            existing_msg_ids.add(part)

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
                    db.add(
                        WhatsAppMessage(
                            thread_id=wa_thread.id,
                            direction="incoming",
                            content=f"{msg.message_text}\n{_ext_msg_marker(msg.external_id)}",
                            status="received",
                            created_at=msg.sent_at or _utcnow(),
                        ),
                    )
                    stats["messages_imported"] += 1
                    stats["wa_messages_imported"] += 1

            account.last_sync_at = _utcnow()
            await WhatsAppSyncService._complete_job(job, stats=stats)
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
            failed_job = await db.get(WhatsAppSyncJob, job_id)
            if failed_job:
                failed_job.status = "running"
                failed_job.started_at = failed_job.started_at or _utcnow()
                await WhatsAppSyncService._complete_job(failed_job, stats=stats, error=str(exc)[:500])
                await db.commit()
            logger.exception("%s conversations sync failed", MARKER)
            raise HTTPException(500, f"Conversation sync failed: {exc}") from exc

    @staticmethod
    async def test_connection(
        db: AsyncSession,
        *,
        account_id: UUID,
    ) -> dict[str, Any]:
        account = await WhatsAppSyncService._get_account(db, account_id)
        job = await WhatsAppSyncService._create_job(
            db, account_id=account.id, job_type="test_connection", trigger="manual",
        )
        await WhatsAppSyncService._start_job(job)
        adapter = resolve_adapter(account.provider, account.account_type)
        result = await adapter.test_connection(_account_config(account))
        stats = {"ok": result.ok, "provider": result.provider, "latency_ms": result.latency_ms}
        if result.ok:
            account.status = "connected"
            if not account.provider:
                account.provider = result.provider
        else:
            account.status = "error"
        await WhatsAppSyncService._complete_job(
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
        await WhatsAppSyncService.ensure_demo_accounts(db)
        now = _utcnow()
        job_ids: list[UUID] = []
        accounts = (
            await db.execute(
                select(WhatsAppSyncAccount).where(WhatsAppSyncAccount.status == "connected"),
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
                    .select_from(WhatsAppSyncJob)
                    .where(
                        WhatsAppSyncJob.account_id == account.id,
                        WhatsAppSyncJob.job_type == job_type,
                        WhatsAppSyncJob.status == "pending",
                    ),
                )
                if pending:
                    continue
                job = await WhatsAppSyncService._create_job(
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
