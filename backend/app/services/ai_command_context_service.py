"""AI Command Center — page/entity context loading and suggestions."""
from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.campaign import Campaign
from app.models.client import Client
from app.models.content import ContentItem
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.landing_page import LandingPage
from app.models.media_library import MediaAsset
from app.models.partner import Partner
from app.models.product import Product

logger = logging.getLogger(__name__)

_CONTEXT_MARKER = "[AI Command Context]"
_SUGGESTION_MARKER = "[AI Command Suggestion]"

ENTITY_TYPES = frozenset({
    "client", "campaign", "content", "product", "crm_lead",
    "deal", "partner", "media_asset", "landing_page",
})

THIS_PHRASES = (
    r"\bthis product\b",
    r"\bfor this product\b",
    r"\bthis client\b",
    r"\bfor this client\b",
    r"\bthis campaign\b",
    r"\bfor this campaign\b",
    r"\bthis lead\b",
    r"\bfor this lead\b",
    r"\bthis deal\b",
    r"\bfor this deal\b",
    r"\bthis partner\b",
    r"\bthese selected assets\b",
    r"\bselected assets\b",
    r"\bthis item\b",
    r"\bthis page\b",
)


class AiCommandContextService:
    @staticmethod
    def normalize_input(
        *,
        current_page: str | None = None,
        entity_type: str | None = None,
        entity_id: UUID | str | None = None,
        selected_items: list[str] | None = None,
        user_context_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        et = (entity_type or "").strip().lower() or None
        if et and et not in ENTITY_TYPES:
            et = None
        eid = str(entity_id) if entity_id else None
        return {
            "current_page": (current_page or "").strip(),
            "entity_type": et,
            "entity_id": eid,
            "selected_items": [str(x) for x in (selected_items or []) if x],
            "user_context_json": dict(user_context_json or {}),
        }

    @staticmethod
    async def load_context(
        db: AsyncSession,
        ctx_input: dict[str, Any],
    ) -> dict[str, Any]:
        entity_type = ctx_input.get("entity_type")
        entity_id = ctx_input.get("entity_id")
        entity_data: dict[str, Any] = {}
        client_id: str | None = None
        entity_label: str | None = None

        if entity_type and entity_id:
            try:
                euuid = UUID(str(entity_id))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid entity_id")

            if entity_type == "client":
                r = await db.execute(select(Client).where(Client.id == euuid))
                ent = r.scalar_one_or_none()
                if not ent:
                    raise HTTPException(status_code=404, detail="Client not found")
                client_id = str(ent.id)
                entity_label = ent.company_name
                entity_data = {"id": str(ent.id), "company_name": ent.company_name, "category": ent.business_category}

            elif entity_type == "product":
                r = await db.execute(select(Product).where(Product.id == euuid))
                ent = r.scalar_one_or_none()
                if not ent:
                    raise HTTPException(status_code=404, detail="Product not found")
                client_id = str(ent.client_id)
                entity_label = ent.name
                entity_data = {
                    "id": str(ent.id), "name": ent.name, "category": ent.category,
                    "client_id": client_id, "description": (ent.description or "")[:300],
                }

            elif entity_type == "campaign":
                r = await db.execute(select(Campaign).where(Campaign.id == euuid))
                ent = r.scalar_one_or_none()
                if not ent:
                    raise HTTPException(status_code=404, detail="Campaign not found")
                client_id = str(ent.client_id)
                entity_label = ent.name
                entity_data = {
                    "id": str(ent.id), "name": ent.name, "objective": ent.objective,
                    "status": ent.status, "client_id": client_id,
                }

            elif entity_type == "content":
                r = await db.execute(select(ContentItem).where(ContentItem.id == euuid))
                ent = r.scalar_one_or_none()
                if not ent:
                    raise HTTPException(status_code=404, detail="Content not found")
                client_id = str(ent.client_id)
                entity_label = f"Content ({ent.status})"
                entity_data = {
                    "id": str(ent.id), "status": ent.status, "client_id": client_id,
                    "campaign_id": str(ent.campaign_id) if ent.campaign_id else None,
                    "platforms": list(ent.platforms or []),
                }

            elif entity_type == "crm_lead":
                r = await db.execute(select(CrmLead).where(CrmLead.id == euuid))
                ent = r.scalar_one_or_none()
                if not ent:
                    raise HTTPException(status_code=404, detail="CRM lead not found")
                client_id = str(ent.client_id)
                entity_label = ent.name
                entity_data = {
                    "id": str(ent.id), "name": ent.name, "company": ent.company,
                    "status": ent.status, "client_id": client_id, "interest": ent.interest,
                }

            elif entity_type == "deal":
                r = await db.execute(
                    select(CrmDeal).options(selectinload(CrmDeal.lead)).where(CrmDeal.id == euuid)
                )
                ent = r.scalar_one_or_none()
                if not ent:
                    raise HTTPException(status_code=404, detail="Deal not found")
                client_id = str(ent.client_id)
                entity_label = ent.title
                entity_data = {
                    "id": str(ent.id), "title": ent.title, "status": ent.status,
                    "client_id": client_id, "lead_id": str(ent.lead_id),
                    "lead_name": ent.lead.name if ent.lead else None,
                }

            elif entity_type == "partner":
                r = await db.execute(select(Partner).where(Partner.id == euuid))
                ent = r.scalar_one_or_none()
                if not ent:
                    raise HTTPException(status_code=404, detail="Partner not found")
                entity_label = ent.name
                entity_data = {
                    "id": str(ent.id), "name": ent.name, "country": ent.country,
                    "partner_type": ent.partner_type,
                }

            elif entity_type == "media_asset":
                r = await db.execute(select(MediaAsset).where(MediaAsset.id == euuid))
                ent = r.scalar_one_or_none()
                if not ent:
                    raise HTTPException(status_code=404, detail="Media asset not found")
                client_id = str(ent.client_id)
                entity_label = ent.title
                entity_data = {
                    "id": str(ent.id), "title": ent.title, "file_type": ent.file_type,
                    "client_id": client_id, "campaign_id": str(ent.campaign_id) if ent.campaign_id else None,
                }

            elif entity_type == "landing_page":
                r = await db.execute(select(LandingPage).where(LandingPage.id == euuid))
                ent = r.scalar_one_or_none()
                if not ent:
                    raise HTTPException(status_code=404, detail="Landing page not found")
                client_id = str(ent.client_id)
                entity_label = ent.title
                entity_data = {
                    "id": str(ent.id), "title": ent.title, "slug": ent.slug,
                    "status": ent.status, "client_id": client_id,
                    "product_id": str(ent.product_id) if ent.product_id else None,
                    "campaign_id": str(ent.campaign_id) if ent.campaign_id else None,
                }

        selected_assets: list[dict[str, Any]] = []
        for sid in ctx_input.get("selected_items") or []:
            try:
                ar = await db.execute(select(MediaAsset).where(MediaAsset.id == UUID(str(sid))))
                asset = ar.scalar_one_or_none()
                if asset:
                    selected_assets.append({
                        "id": str(asset.id), "title": asset.title, "client_id": str(asset.client_id),
                    })
                    if not client_id:
                        client_id = str(asset.client_id)
            except ValueError:
                continue

        summary_parts = []
        if entity_label and entity_type:
            summary_parts.append(f"{entity_type}: {entity_label}")
        if ctx_input.get("current_page"):
            summary_parts.append(f"page={ctx_input['current_page']}")
        if selected_assets:
            summary_parts.append(f"{len(selected_assets)} selected asset(s)")

        loaded = {
            **ctx_input,
            "client_id": client_id,
            "entity_label": entity_label,
            "entity_data": entity_data,
            "selected_assets": selected_assets,
            "entity_summary": " · ".join(summary_parts) if summary_parts else None,
        }
        logger.info(
            "%s loaded: type=%s id=%s client=%s page=%s",
            _CONTEXT_MARKER, entity_type, entity_id, client_id, ctx_input.get("current_page"),
        )
        return loaded

    @staticmethod
    def context_block(ctx: dict[str, Any]) -> str:
        lines = [
            f"CURRENT PAGE: {ctx.get('current_page') or 'unknown'}",
            f"ENTITY TYPE: {ctx.get('entity_type') or 'none'}",
            f"ENTITY ID: {ctx.get('entity_id') or 'none'}",
            f"CLIENT ID: {ctx.get('client_id') or 'none'}",
        ]
        if ctx.get("entity_summary"):
            lines.append(f"SUMMARY: {ctx['entity_summary']}")
        if ctx.get("entity_data"):
            lines.append(f"ENTITY DATA: {ctx['entity_data']}")
        if ctx.get("selected_assets"):
            lines.append(f"SELECTED ASSETS: {ctx['selected_assets']}")
        if ctx.get("user_context_json"):
            lines.append(f"USER CONTEXT: {ctx['user_context_json']}")
        lines.append(
            "Resolve phrases: 'this product' -> product_id, 'this client' -> client_id, "
            "'this campaign' -> campaign_id, 'this lead' -> crm lead_id, "
            "'this deal' -> deal_id, 'selected assets' -> media_asset_ids from SELECTED ASSETS."
        )
        return "\n".join(lines)

    @staticmethod
    def command_uses_context_phrases(command: str) -> bool:
        text = command.lower()
        return any(re.search(p, text) for p in THIS_PHRASES)

    @staticmethod
    def apply_context_to_actions(actions: list[dict[str, Any]], ctx: dict[str, Any]) -> list[dict[str, Any]]:
        if not ctx.get("entity_type") and not ctx.get("client_id"):
            return actions

        et = ctx.get("entity_type")
        ed = ctx.get("entity_data") or {}
        client_id = ctx.get("client_id")
        product_id = ed.get("id") if et == "product" else ed.get("product_id")
        campaign_id = ed.get("id") if et == "campaign" else ed.get("campaign_id")
        lead_id = ed.get("id") if et == "crm_lead" else ed.get("lead_id")
        deal_id = ed.get("id") if et == "deal" else None

        asset_ids = [a["id"] for a in ctx.get("selected_assets") or []]
        if et == "media_asset" and ed.get("id"):
            asset_ids = [ed["id"]] + [x for x in asset_ids if x != ed["id"]]

        out: list[dict[str, Any]] = []
        for act in actions:
            payload = dict(act.get("payload") or {})
            if client_id and not payload.get("client_id"):
                payload["client_id"] = client_id
            if product_id and act["action_type"] in (
                "run_buyer_finder", "create_landing_page_draft", "create_attribution_link",
            ) and not payload.get("product_id"):
                payload["product_id"] = product_id
            if campaign_id and act["action_type"] in (
                "generate_content_studio_drafts", "create_content_draft",
                "create_landing_page_draft", "create_attribution_link", "create_campaign",
            ) and not payload.get("campaign_id"):
                payload["campaign_id"] = campaign_id
            if lead_id and act["action_type"] in ("create_follow_up_task",) and not payload.get("lead_id"):
                payload["lead_id"] = lead_id
            if deal_id and act["action_type"] in ("create_deal_note", "create_follow_up_task") and not payload.get("deal_id"):
                payload["deal_id"] = deal_id
            if asset_ids and act["action_type"] == "generate_content_studio_drafts":
                payload["media_asset_ids"] = asset_ids
            if et == "product" and act["action_type"] == "run_buyer_finder" and ed.get("id"):
                payload["product_id"] = ed["id"]
            out.append({**act, "payload": payload})
        return out

    @staticmethod
    async def suggestions(
        db: AsyncSession,
        *,
        current_page: str | None = None,
        entity_type: str | None = None,
        entity_id: UUID | str | None = None,
        selected_items: list[str] | None = None,
        user_context_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx_input = AiCommandContextService.normalize_input(
            current_page=current_page,
            entity_type=entity_type,
            entity_id=entity_id,
            selected_items=selected_items,
            user_context_json=user_context_json,
        )
        ctx = await AiCommandContextService.load_context(db, ctx_input)
        et = ctx.get("entity_type")
        ed = ctx.get("entity_data") or {}
        items: list[dict[str, Any]] = []

        def add(label: str, command: str, *, kind: str = "command", href: str | None = None) -> None:
            items.append({"label": label, "command": command, "kind": kind, "href": href})

        if et == "product":
            name = ed.get("name") or "this product"
            add("Find buyers", f"Find buyers for this product")
            add("Create landing page", f"Create a landing page draft for this product")
            add("Create attribution link", f"Create an attribution tracking link for this product")
            add("Generate campaign", f"Create a draft campaign for {name}")
            add("Analyze export potential", f"Run buyer finder and create follow-up task for {name}")
            add("Open Buyer Finder", "", kind="link", href=f"/buyer-finder?product={ed.get('id')}")

        elif et == "crm_lead":
            add("Score this lead", "Score this lead with AI intelligence")
            add("Suggest next step", "Create a follow-up task for this lead with suggested next actions")
            add("Generate proposal", "Create a task to draft a sales proposal for this lead")
            add("Create follow-up task", "Create a follow-up task for this lead")
            add("Match products", "Create a task to review product matches for this lead")
            add("Open CRM lead", "", kind="link", href=f"/crm?lead={ed.get('id')}")

        elif et == "campaign":
            add("Generate content drafts", "Generate 5 content studio drafts for this campaign")
            add("Open pipeline", "", kind="link", href="/pipeline")
            add("Create landing page", "Create a landing page draft for this campaign")
            add("Run audit", "Run audit and create tasks for critical issues")
            add("Create attribution link", "Create an attribution link for this campaign")

        elif et == "deal":
            add("Add deal note", "Add a note to this deal with latest status summary")
            add("Create follow-up task", "Create a follow-up task for this deal")
            add("Open Deal Room", "", kind="link", href=f"/crm/deals/{ed.get('id')}")

        elif et == "client":
            add("Create campaign", f"Create a draft campaign for this client")
            add("Run sales agent scan", "Run sales agent scan")
            add("Run audit", "Run audit and create tasks for critical issues")

        elif et == "content":
            add("Create follow-up task", "Create a task to review this content draft")
            add("Open content", "", kind="link", href=f"/content/{ed.get('id')}")

        elif et == "partner":
            add("Create follow-up task", "Create a follow-up task for this partner")
            add("Open partner", "", kind="link", href=f"/partners/{ed.get('id')}")

        elif et == "landing_page":
            add("Create attribution link", "Create an attribution link for this landing page")
            add("Copy public URL", "", kind="link", href=f"/landing-pages")

        elif et == "media_asset":
            add("Generate content draft", "Generate a content studio draft using this asset")
            if ctx.get("selected_assets") and len(ctx["selected_assets"]) > 1:
                add("Generate from selected", "Generate content studio drafts from these selected assets")

        else:
            page = ctx.get("current_page") or ""
            if "buyer-finder" in page:
                add("Run buyer analysis", "Analyze buyers for the selected product")
            elif "sales-department" in page:
                add("Generate briefing", "Run sales agent scan and create summary task")
            elif "crm" in page:
                add("Show hot leads", "show hot leads")
                add("Show neglected leads", "show neglected leads")
                add("Score all leads", "score all leads")
            else:
                add("Run audit", "Run audit and create tasks for critical issues")
                add("Sales agent scan", "Run sales agent scan")

        logger.info(
            "%s generated: type=%s count=%s page=%s",
            _SUGGESTION_MARKER, et, len(items), current_page,
        )
        return {
            "current_page": ctx.get("current_page"),
            "entity_type": et,
            "entity_id": ctx.get("entity_id"),
            "entity_label": ctx.get("entity_label"),
            "entity_summary": ctx.get("entity_summary"),
            "suggestions": items[:12],
        }
