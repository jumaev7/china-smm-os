"""Communication Hub demo seed — mock providers for empty tenants."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication import (
    CommunicationContact,
    CommunicationFollowUp,
    CommunicationMessage,
    CommunicationThread,
)
from app.services.communication_template_service import CommunicationTemplateService

logger = logging.getLogger(__name__)
MARKER = "[Communication Hub Seed]"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommunicationHubSeedService:
    @staticmethod
    async def ensure_tenant_demo_data(db: AsyncSession, tenant_id: UUID) -> bool:
        """Seed mock conversations, follow-ups, and templates when tenant hub is empty."""
        await CommunicationTemplateService.ensure_default_templates(db, tenant_id)

        fu_count = int(
            (await db.execute(
                select(func.count()).select_from(CommunicationFollowUp).where(
                    CommunicationFollowUp.tenant_id == tenant_id,
                )
            )).scalar() or 0
        )
        thread_count = int(
            (await db.execute(
                select(func.count()).select_from(CommunicationThread).where(
                    CommunicationThread.tenant_id == tenant_id,
                )
            )).scalar() or 0
        )
        if thread_count >= 3 and fu_count >= 2:
            return False

        now = _utcnow()
        seeded = False

        if thread_count < 3:
            contacts_data = [
                ("Almaty Trading LLC", "Dmitry Petrov", "whatsapp", "Kazakhstan"),
                ("Tashkent Import Co", "Sardor Karimov", "telegram", "Uzbekistan"),
                ("Bishkek Wholesale", "Aida Sydykova", "manual", "Kyrgyzstan"),
            ]
            for company, name, channel, country in contacts_data:
                contact = CommunicationContact(
                    tenant_id=tenant_id,
                    name=name,
                    company=company,
                    country=country,
                    whatsapp=f"+998{hash(name) % 900000000:09d}" if channel == "whatsapp" else None,
                    telegram=f"@{name.split()[0].lower()}" if channel == "telegram" else None,
                )
                db.add(contact)
                await db.flush()

                thread = CommunicationThread(
                    tenant_id=tenant_id,
                    contact_id=contact.id,
                    channel=channel,
                    title=f"{company} — product inquiry",
                    status="open" if channel != "manual" else "waiting",
                    last_message_at=now - timedelta(hours=hash(name) % 48),
                )
                db.add(thread)
                await db.flush()

                inbound = CommunicationMessage(
                    thread_id=thread.id,
                    direction="inbound",
                    sender_name=name,
                    message_text=(
                        f"Hello, we are interested in your factory products for {country}. "
                        "Could you share MOQ and lead time?"
                    ),
                    status="unanswered" if channel != "manual" else "read",
                )
                db.add(inbound)
                if channel == "manual":
                    outbound = CommunicationMessage(
                        thread_id=thread.id,
                        direction="outbound",
                        sender_name="Sales Team",
                        message_text="Thank you for your inquiry. We will send the catalog shortly.",
                        status="sent",
                    )
                    db.add(outbound)
                    thread.last_message_at = now - timedelta(hours=2)
                await db.flush()
                seeded = True

            await db.commit()
            logger.info("%s seeded threads for tenant=%s", MARKER, tenant_id)

        if fu_count < 2:
            threads = list(
                (await db.execute(
                    select(CommunicationThread)
                    .where(CommunicationThread.tenant_id == tenant_id)
                    .limit(3)
                )).scalars().all()
            )
            if threads:
                db.add(CommunicationFollowUp(
                    tenant_id=tenant_id,
                    thread_id=threads[0].id,
                    title="Follow up on MOQ request",
                    description="Send catalog and pricing for wholesale order.",
                    due_date=now - timedelta(days=1),
                    status="pending",
                    assigned_user="sales@factory.local",
                ))
                db.add(CommunicationFollowUp(
                    tenant_id=tenant_id,
                    thread_id=threads[min(1, len(threads) - 1)].id,
                    title="Schedule video call",
                    description="Confirm product specs and payment terms.",
                    due_date=now.replace(hour=17, minute=0, second=0, microsecond=0),
                    status="pending",
                    assigned_user="manager@factory.local",
                ))
                await db.commit()
                seeded = True
                logger.info("%s seeded follow-ups for tenant=%s", MARKER, tenant_id)

        return seeded
