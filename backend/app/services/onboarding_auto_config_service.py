"""Post-provision onboarding defaults — idempotent tenant workspace seeding."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.content import ContentItem
from app.models.sales_crm import SalesDeal, SalesLead, SalesProposal, SalesProposalItem
from app.models.tenant_onboarding import TenantOnboardingProgress
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

ONBOARDING_AUTO_CONFIG_MARKER = "[OnboardingAutoConfig]"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OnboardingAutoConfigService:
    @staticmethod
    async def _get_or_create_progress(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> TenantOnboardingProgress:
        result = await db.execute(
            select(TenantOnboardingProgress).where(TenantOnboardingProgress.tenant_id == tenant_id),
        )
        row = result.scalar_one_or_none()
        if row:
            return row
        row = TenantOnboardingProgress(
            tenant_id=tenant_id,
            status="not_started",
            progress_percent=0,
            steps_completed={},
            milestone_messages=[],
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def ensure_tenant_onboarding_defaults(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> dict[str, int | bool]:
        """Idempotent — seeds welcome assets and initializes onboarding progress."""
        progress = await OnboardingAutoConfigService._get_or_create_progress(db, tenant_id)
        if progress.auto_config_applied:
            return {"skipped": True, "reason": "already_applied"}

        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        if not client_ids:
            return {"skipped": True, "reason": "no_client"}

        client_id = client_ids[0]
        client = await db.get(Client, client_id)
        if not client:
            return {"skipped": True, "reason": "client_missing"}

        counts: dict[str, int] = {
            "leads": 0,
            "deals": 0,
            "content": 0,
            "proposals": 0,
            "scheduled_content": 0,
        }
        now = _utcnow()
        marker = ONBOARDING_AUTO_CONFIG_MARKER

        lead_count = int(
            (await db.execute(
                select(func.count()).select_from(SalesLead).where(SalesLead.tenant_id == tenant_id),
            )).scalar() or 0,
        )
        if lead_count == 0:
            lead = SalesLead(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                name="Sample Buyer Contact",
                company=client.company_name or "Welcome Lead",
                email="buyer@example.com",
                country=client.target_audience or "Export market",
                status="new",
                source="onboarding",
                notes=f"{marker} Starter lead for pipeline visibility.",
            )
            db.add(lead)
            await db.flush()
            counts["leads"] = 1
            lead_id = lead.id
        else:
            lead_row = (
                await db.execute(
                    select(SalesLead).where(SalesLead.tenant_id == tenant_id).limit(1),
                )
            ).scalar_one_or_none()
            lead_id = lead_row.id if lead_row else None

        deal_count = int(
            (await db.execute(
                select(func.count()).select_from(SalesDeal).where(SalesDeal.tenant_id == tenant_id),
            )).scalar() or 0,
        )
        if deal_count == 0 and lead_id:
            deal = SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                title=f"{client.company_name or 'Factory'} — Export Opportunity",
                stage="lead",
                value=Decimal("25000"),
                currency="USD",
                lead_id=lead_id,
                notes=f"{marker} Default pipeline deal — edit or replace with real opportunities.",
            )
            db.add(deal)
            counts["deals"] = 1

        content_count = int(
            (await db.execute(
                select(func.count()).select_from(ContentItem).where(ContentItem.client_id == client_id),
            )).scalar() or 0,
        )
        if content_count == 0:
            welcome = ContentItem(
                id=uuid.uuid4(),
                client_id=client_id,
                platforms=["instagram", "telegram"],
                status="draft",
                source="manual",
                caption_short_en="Welcome to your export marketing workspace",
                caption_long_en=(
                    "This is your first AI-ready content slot. Upload factory photos "
                    "and generate multilingual captions to reach international buyers."
                ),
                internal_notes=f"{marker} Welcome content template.",
                created_at=now,
                updated_at=now,
            )
            db.add(welcome)
            counts["content"] = 1

        scheduled_count = int(
            (await db.execute(
                select(func.count()).select_from(ContentItem).where(
                    ContentItem.client_id == client_id,
                    ContentItem.status == "scheduled",
                ),
            )).scalar() or 0,
        )
        if scheduled_count == 0:
            schedule_at = now + timedelta(days=3)
            scheduled = ContentItem(
                id=uuid.uuid4(),
                client_id=client_id,
                platforms=["instagram"],
                status="scheduled",
                source="manual",
                caption_short_en="Your first scheduled export post",
                internal_notes=f"{marker} Default publishing schedule placeholder.",
                scheduled_for=schedule_at,
                created_at=now,
                updated_at=now,
            )
            db.add(scheduled)
            counts["scheduled_content"] = 1

        proposal_count = int(
            (await db.execute(
                select(func.count()).select_from(SalesProposal).where(SalesProposal.tenant_id == tenant_id),
            )).scalar() or 0,
        )
        if proposal_count == 0:
            proposal = SalesProposal(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                proposal_number=f"ONB-{now.year}-0001",
                title="Sample Export Proposal",
                issue_date=now,
                valid_until=now + timedelta(days=30),
                currency="USD",
                subtotal=Decimal("25000"),
                discount=Decimal("0"),
                tax=Decimal("0"),
                total=Decimal("25000"),
                status="draft",
                notes=f"{marker} Sample proposal — customize for your first buyer.",
            )
            db.add(proposal)
            await db.flush()
            db.add(SalesProposalItem(
                id=uuid.uuid4(),
                proposal_id=proposal.id,
                product_or_service_name="Product line — customize with your catalog",
                description="Replace with your catalog items",
                quantity=Decimal("1"),
                unit_price=Decimal("25000"),
                discount=Decimal("0"),
                total=Decimal("25000"),
                sort_order=0,
            ))
            counts["proposals"] = 1

        progress.auto_config_applied = True
        progress.auto_config_applied_at = now
        progress.onboarding_version = 2
        if not progress.executive_walkthrough_progress:
            progress.executive_walkthrough_progress = {
                "completed_panels": [],
                "initialized_at": now.isoformat(),
            }
        if not progress.first_success_state:
            progress.first_success_state = {"initialized_at": now.isoformat()}
        if (
            progress.status != "completed"
            and not progress.manually_completed
            and not progress.started_at
        ):
            progress.started_at = now
            if progress.status == "not_started":
                progress.status = "in_progress"

        await db.flush()

        from app.services.onboarding_readiness_service import OnboardingReadinessService

        await OnboardingReadinessService.sync_progress(db, tenant_id, progress)

        logger.info("%s tenant=%s counts=%s", marker, tenant_id, counts)
        return {"skipped": False, **counts}
