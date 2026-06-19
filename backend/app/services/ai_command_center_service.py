"""AI Command Center — plan, confirm, and execute safe admin actions."""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.ai_command import AiCommand, AiCommandAction
from app.models.client import Client
from app.schemas.ai_command import ALLOWED_ACTION_TYPES
from app.schemas.attribution_link import AttributionLinkCreate
from app.schemas.campaign import CampaignCreate
from app.schemas.content import ContentCreate
from app.schemas.content_studio import ContentStudioGenerateRequest
from app.schemas.crm import CrmDealEventCreate, CrmLeadCreate
from app.schemas.landing_page import LandingPageCreate
from app.schemas.operator_task import OperatorTaskCreate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.attribution_link_service import AttributionLinkService
from app.services.audit_service import AuditService
from app.services.buyer_finder_service import BuyerFinderService
from app.services.campaign_service import CampaignService
from app.services.content_service import ContentService
from app.services.content_studio_service import ContentStudioService
from app.services.crm_service import CrmService
from app.services.deal_service import DealService
from app.services.landing_page_service import LandingPageService
from app.services.lead_intelligence_service import LeadIntelligenceService
from app.services.operator_task_service import OperatorTaskService
from app.services.ai_command_context_service import AiCommandContextService
from app.services.sales_agent_service import SalesAgentService

logger = logging.getLogger(__name__)

_MARKER = "[AI Command]"

ALLOWED_TYPES = frozenset(ALLOWED_ACTION_TYPES)

BLOCKED_ACTION_SUBSTRINGS = frozenset({
    "publish", "delete", "send_message", "send_email", "send_telegram",
    "mark_paid", "commission_paid", "invoice_paid", "auto_publish",
    "approve_commission", "mark_commission",
})

BLOCKED_PAYLOAD_KEYS = frozenset({
    "publish", "delete", "send", "status_paid", "commission_status",
    "auto_apply", "auto_publish",
})

_PLANNER_SYSTEM = """\
You are an AI command planner for an internal SMM + sales admin tool.
Convert the operator command into a SAFE action plan using ONLY these action types:
- create_campaign {client_id, name, description?, objective?, status?: "draft"}
- create_task {client_id, title, description?, priority?, due_at?}
- create_content_draft {client_id, campaign_id?, platforms?, internal_notes?, count?: 1}
- generate_content_studio_drafts {client_id, campaign_id?, content_count, content_goal, platforms?}
- create_crm_lead {client_id, name, company?, phone?, email?, telegram?, interest?, notes?, source?}
- create_deal_note {deal_id, title, note}
- create_follow_up_task {client_id, title, description?, lead_id?, deal_id?, priority?}
- run_audit {}
- run_sales_agent_scan {}
- run_buyer_finder {product_id}
- create_attribution_link {client_id, channel, destination_url, title, campaign_id?, product_id?}
- create_landing_page_draft {client_id, slug, title, subtitle?, description?, campaign_id?, product_id?, status?: "draft"}
- show_hot_leads {client_id?}
- show_neglected_leads {client_id?}
- score_all_leads {client_id?, limit?: 50}

Return ONLY JSON:
{
  "parsed_intent": "short intent label",
  "summary": "1-2 sentence plan summary for admin review",
  "unsupported_parts": ["parts of command that cannot be done safely"],
  "risk_level": "low|medium|high",
  "actions": [
    {
      "action_type": "one of allowed types",
      "label": "human-readable step",
      "payload": {},
      "is_critical": false
    }
  ]
}

Rules:
- NEVER plan publish, delete, external messaging, payment, or commission status changes
- All content actions create drafts only (status draft)
- Use client_id UUIDs from CLIENT DIRECTORY when matching client names
- Use product_id / campaign_id UUIDs only when provided in context
- Prefer draft status for campaigns and landing pages
- If command mentions audit + tasks, plan run_audit then create_task for critical issues
- Max 8 actions per plan
"""


class AiCommandCenterService:
    @staticmethod
    async def _load_clients(db: AsyncSession) -> list[Client]:
        r = await db.execute(select(Client).order_by(Client.company_name).limit(100))
        return list(r.scalars().all())

    @staticmethod
    def _client_directory(clients: list[Client]) -> str:
        return "\n".join(f"- {c.id} | {c.company_name}" for c in clients[:50])

    @staticmethod
    def _validate_action(action_type: str, payload: dict[str, Any]) -> None:
        if action_type not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail=f"Blocked action type: {action_type}")
        lowered = json.dumps(payload or {}).lower()
        for blocked in BLOCKED_ACTION_SUBSTRINGS:
            if blocked in action_type.lower() or blocked in lowered:
                logger.warning("%s blocked: type=%s reason=forbidden_keyword", _MARKER, action_type)
                raise HTTPException(status_code=400, detail=f"Blocked unsafe action: {action_type}")
        for key in payload or {}:
            if key.lower() in BLOCKED_PAYLOAD_KEYS:
                raise HTTPException(status_code=400, detail=f"Blocked payload key: {key}")

    @staticmethod
    async def _parse_plan(
        db: AsyncSession,
        command: str,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = ctx or {}
        clients = await AiCommandCenterService._load_clients(db)
        directory = AiCommandCenterService._client_directory(clients)

        products_ctx = ""
        campaigns_ctx = ""
        focus_client = ctx.get("client_id")
        if focus_client:
            from app.models.product import Product
            from app.models.campaign import Campaign
            cid = UUID(str(focus_client))
            pr = await db.execute(select(Product.id, Product.name).where(Product.client_id == cid).limit(20))
            products_ctx = "\n".join(f"- {pid} | {name}" for pid, name in pr.all())
            cr = await db.execute(select(Campaign.id, Campaign.name).where(Campaign.client_id == cid).limit(20))
            campaigns_ctx = "\n".join(f"- {cid2} | {name}" for cid2, name in cr.all())
        elif clients:
            from app.models.product import Product
            from app.models.campaign import Campaign
            cid = clients[0].id
            pr = await db.execute(select(Product.id, Product.name).where(Product.client_id == cid).limit(20))
            products_ctx = "\n".join(f"- {pid} | {name}" for pid, name in pr.all())
            cr = await db.execute(select(Campaign.id, Campaign.name).where(Campaign.client_id == cid).limit(20))
            campaigns_ctx = "\n".join(f"- {cid2} | {name}" for cid2, name in cr.all())

        context_block = AiCommandContextService.context_block(ctx) if ctx.get("entity_type") or ctx.get("client_id") else ""

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("AI unavailable")
            _validate_api_key()
            openai = get_openai()
            user_parts = [
                f"COMMAND:\n{command.strip()}",
                f"CLIENT DIRECTORY:\n{directory}",
                f"SAMPLE PRODUCTS:\n{products_ctx or '(none)'}",
                f"SAMPLE CAMPAIGNS:\n{campaigns_ctx or '(none)'}",
            ]
            if context_block:
                user_parts.append(f"PAGE CONTEXT:\n{context_block}")
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _PLANNER_SYSTEM},
                    {"role": "user", "content": "\n\n".join(user_parts)},
                ],
                temperature=0.2,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
        except Exception as exc:
            logger.info("%s planner fallback: %s", _MARKER, exc)
            parsed = AiCommandCenterService._heuristic_plan(command, clients, ctx)

        actions_raw = parsed.get("actions") or []
        actions: list[dict[str, Any]] = []
        unsupported = list(parsed.get("unsupported_parts") or [])
        for raw in actions_raw[:8]:
            if not isinstance(raw, dict):
                continue
            atype = str(raw.get("action_type") or "").strip()
            if atype not in ALLOWED_TYPES:
                unsupported.append(f"Unsupported action: {atype or 'unknown'}")
                continue
            payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
            try:
                AiCommandCenterService._validate_action(atype, payload)
            except HTTPException:
                unsupported.append(f"Blocked unsafe action: {atype}")
                continue
            actions.append({
                "action_type": atype,
                "label": str(raw.get("label") or atype.replace("_", " ").title()),
                "payload": payload,
                "is_critical": bool(raw.get("is_critical")),
            })

        if not actions:
            actions = AiCommandCenterService._heuristic_plan(command, clients, ctx).get("actions", [])

        if ctx:
            actions = AiCommandContextService.apply_context_to_actions(actions, ctx)

        risk = str(parsed.get("risk_level") or "medium").lower()
        if risk not in ("low", "medium", "high"):
            risk = "medium" if len(actions) <= 3 else "high"

        return {
            "parsed_intent": str(parsed.get("parsed_intent") or "admin_command")[:255],
            "summary": str(parsed.get("summary") or f"Execute {len(actions)} safe action(s)")[:500],
            "unsupported_parts": unsupported[:5],
            "risk_level": risk,
            "actions": actions,
        }

    @staticmethod
    def _heuristic_plan(
        command: str,
        clients: list[Client],
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = ctx or {}
        text = command.lower()
        client_id = ctx.get("client_id") or (str(clients[0].id) if clients else None)
        ed = ctx.get("entity_data") or {}
        et = ctx.get("entity_type")
        product_id = ed.get("id") if et == "product" else ed.get("product_id")
        campaign_id = ed.get("id") if et == "campaign" else ed.get("campaign_id")
        lead_id = ed.get("id") if et == "crm_lead" else ed.get("lead_id")
        deal_id = ed.get("id") if et == "deal" else None
        actions: list[dict[str, Any]] = []
        unsupported: list[str] = []

        if any(w in text for w in ("publish", "send message", "delete", "mark paid", "invoice paid")):
            unsupported.append("Publishing, messaging, deletion, and payment changes are not allowed")

        if "audit" in text:
            actions.append({"action_type": "run_audit", "label": "Run system audit", "payload": {}, "is_critical": False})
            if "task" in text:
                actions.append({
                    "action_type": "create_task",
                    "label": "Create tasks for critical audit issues",
                    "payload": {
                        "client_id": client_id,
                        "title": "Review critical audit issues",
                        "description": "Follow up on critical issues from AI Command Center audit run.",
                        "priority": "high",
                    },
                    "is_critical": False,
                })

        if "campaign" in text and "this campaign" not in text:
            name_match = re.search(r"campaign(?: for)? ([^.]+?)(?: with|$)", text)
            name = (name_match.group(1).strip().title() if name_match else "New Campaign")[:255]
            actions.append({
                "action_type": "create_campaign",
                "label": f"Create draft campaign: {name}",
                "payload": {"client_id": client_id, "name": name, "status": "draft"},
                "is_critical": False,
            })

        if "draft post" in text or "content studio" in text or "draft posts" in text or (
            "content" in text and "draft" in text and "this campaign" in text
        ):
            count = 10 if "10" in text else (5 if "5" in text else 3)
            payload: dict[str, Any] = {
                "client_id": client_id,
                "content_count": count,
                "content_goal": "Product promotion",
                "platforms": ["instagram", "telegram"],
            }
            if campaign_id:
                payload["campaign_id"] = campaign_id
            actions.append({
                "action_type": "generate_content_studio_drafts",
                "label": f"Generate {count} content studio drafts",
                "payload": payload,
                "is_critical": False,
            })

        if "buyer" in text and "find" in text:
            bf_payload: dict[str, Any] = {}
            if product_id:
                bf_payload["product_id"] = product_id
            actions.append({
                "action_type": "run_buyer_finder",
                "label": "Run buyer finder analysis",
                "payload": bf_payload,
                "is_critical": False,
            })
            if "task" in text or "follow" in text:
                actions.append({
                    "action_type": "create_follow_up_task",
                    "label": "Create follow-up tasks for buyer recommendations",
                    "payload": {
                        "client_id": client_id,
                        "title": "Follow up on buyer finder recommendations",
                        "priority": "medium",
                    },
                    "is_critical": False,
                })

        if "landing page" in text:
            slug = "product-inquiry"
            lp_payload: dict[str, Any] = {
                "client_id": client_id,
                "slug": slug,
                "title": ed.get("name") or ed.get("title") or "Product inquiry",
                "status": "draft",
            }
            if product_id:
                lp_payload["product_id"] = product_id
            if campaign_id:
                lp_payload["campaign_id"] = campaign_id
            actions.append({
                "action_type": "create_landing_page_draft",
                "label": "Create landing page draft",
                "payload": lp_payload,
                "is_critical": False,
            })

        if "follow-up" in text or "follow up" in text or ("task" in text and ("lead" in text or "this lead" in text)):
            fu_payload: dict[str, Any] = {
                "client_id": client_id,
                "title": "Follow up on lead",
                "priority": "medium",
            }
            if lead_id:
                fu_payload["lead_id"] = lead_id
            if deal_id:
                fu_payload["deal_id"] = deal_id
            actions.append({
                "action_type": "create_follow_up_task",
                "label": "Create follow-up task",
                "payload": fu_payload,
                "is_critical": False,
            })

        if "deal note" in text or ("note" in text and "deal" in text):
            if deal_id:
                actions.append({
                    "action_type": "create_deal_note",
                    "label": "Add deal note",
                    "payload": {
                        "deal_id": deal_id,
                        "title": "AI Command note",
                        "note": command[:500],
                    },
                    "is_critical": False,
                })

        if "crm lead" in text or "create lead" in text:
            actions.append({
                "action_type": "create_crm_lead",
                "label": "Create CRM lead from command",
                "payload": {
                    "client_id": client_id,
                    "name": "New lead",
                    "notes": command[:500],
                    "source": "manual",
                },
                "is_critical": False,
            })

        if "sales agent" in text or "scan" in text:
            actions.append({
                "action_type": "run_sales_agent_scan",
                "label": "Run sales agent scan",
                "payload": {},
                "is_critical": False,
            })

        if "attribution" in text or "tracking link" in text:
            attr_payload: dict[str, Any] = {
                "client_id": client_id,
                "channel": "website",
                "destination_url": "https://example.com",
                "title": ed.get("name") or ed.get("title") or "Tracking link",
            }
            if product_id:
                attr_payload["product_id"] = product_id
            if campaign_id:
                attr_payload["campaign_id"] = campaign_id
            actions.append({
                "action_type": "create_attribution_link",
                "label": "Create attribution tracking link",
                "payload": attr_payload,
                "is_critical": False,
            })

        if "hot lead" in text or "show hot" in text:
            payload: dict[str, Any] = {}
            if client_id:
                payload["client_id"] = client_id
            actions.append({
                "action_type": "show_hot_leads",
                "label": "Show top hot leads",
                "payload": payload,
                "is_critical": False,
            })

        if "neglected lead" in text or "show neglected" in text:
            payload = {}
            if client_id:
                payload["client_id"] = client_id
            actions.append({
                "action_type": "show_neglected_leads",
                "label": "Show neglected leads",
                "payload": payload,
                "is_critical": False,
            })

        if "score all lead" in text or "rescore lead" in text or "score leads" in text:
            payload = {"limit": 50}
            if client_id:
                payload["client_id"] = client_id
            actions.append({
                "action_type": "score_all_leads",
                "label": "Score all leads (intelligence refresh)",
                "payload": payload,
                "is_critical": False,
            })

        if not actions and not unsupported:
            unsupported.append("Could not infer safe actions — try a more specific command")

        return {
            "parsed_intent": "heuristic_plan",
            "summary": f"Rule-based plan with {len(actions)} action(s)",
            "unsupported_parts": unsupported,
            "risk_level": "low" if len(actions) <= 2 else "medium",
            "actions": actions,
        }

    @staticmethod
    async def plan(
        db: AsyncSession,
        command: str,
        *,
        user_id: UUID | None = None,
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
        ctx: dict[str, Any] = {}
        if any(ctx_input.get(k) for k in ("entity_type", "entity_id", "current_page", "selected_items")):
            ctx = await AiCommandContextService.load_context(db, ctx_input)

        parsed = await AiCommandCenterService._parse_plan(db, command, ctx or None)

        cmd = AiCommand(
            user_id=user_id,
            raw_command=command.strip(),
            parsed_intent=parsed["parsed_intent"],
            status="awaiting_confirmation",
            action_plan_json=parsed["actions"],
            result_json={
                "summary": parsed["summary"],
                "risk_level": parsed["risk_level"],
                "unsupported_parts": parsed["unsupported_parts"],
                "context": {
                    "current_page": ctx.get("current_page"),
                    "entity_type": ctx.get("entity_type"),
                    "entity_id": ctx.get("entity_id"),
                    "entity_summary": ctx.get("entity_summary"),
                } if ctx else None,
            },
        )
        db.add(cmd)
        await db.flush()

        for act in parsed["actions"]:
            db.add(AiCommandAction(
                command_id=cmd.id,
                action_type=act["action_type"],
                payload_json=act.get("payload") or {},
                status="pending",
            ))

        await db.commit()
        await db.refresh(cmd)

        logger.info(
            "%s planned: id=%s actions=%s risk=%s",
            _MARKER, cmd.id, len(parsed["actions"]), parsed["risk_level"],
        )

        return {
            "command_id": cmd.id,
            "summary": parsed["summary"],
            "parsed_intent": parsed["parsed_intent"],
            "actions": parsed["actions"],
            "risk_level": parsed["risk_level"],
            "requires_confirmation": True,
            "unsupported_parts": parsed["unsupported_parts"],
            "context_summary": ctx.get("entity_summary") if ctx else None,
        }

    @staticmethod
    async def _uuid(payload: dict, key: str) -> UUID | None:
        val = payload.get(key)
        if not val:
            return None
        return UUID(str(val))

    @staticmethod
    async def _execute_one(db: AsyncSession, action: AiCommandAction) -> dict[str, Any]:
        atype = action.action_type
        payload = dict(action.payload_json or {})
        AiCommandCenterService._validate_action(atype, payload)

        if atype == "create_campaign":
            body = CampaignCreate(
                client_id=UUID(str(payload["client_id"])),
                name=str(payload.get("name") or "New campaign"),
                description=payload.get("description"),
                objective=payload.get("objective"),
                status=payload.get("status") or "draft",
            )
            result = await CampaignService.create_campaign(db, body)
            return {"entity": "campaign", "id": str(result["id"]), "name": result.get("name")}

        if atype == "create_task" or atype == "create_follow_up_task":
            body = OperatorTaskCreate(
                client_id=UUID(str(payload["client_id"])),
                title=str(payload.get("title") or "Follow-up task"),
                description=payload.get("description"),
                priority=payload.get("priority") or "medium",
                source_type="manual",
                created_by="admin",
                source_id=await AiCommandCenterService._uuid(payload, "lead_id")
                or await AiCommandCenterService._uuid(payload, "deal_id"),
            )
            result = await OperatorTaskService.create_task(db, body)
            return {"entity": "task", "id": str(result["id"]), "title": result.get("title")}

        if atype == "create_content_draft":
            client_id = UUID(str(payload["client_id"]))
            count = int(payload.get("count") or 1)
            created = []
            for i in range(min(count, 10)):
                body = ContentCreate(
                    client_id=client_id,
                    platforms=list(payload.get("platforms") or ["instagram"]),
                    internal_notes=str(payload.get("internal_notes") or f"[AI Command] Draft {i + 1}")[:2000],
                    source="ai_command",
                )
                item = await ContentService.create(db, body)
                if payload.get("campaign_id"):
                    row = await ContentService.get(db, item.id)
                    row.campaign_id = UUID(str(payload["campaign_id"]))
                    await db.commit()
                created.append({"id": str(item.id), "status": item.status})
            return {"entity": "content", "items": created}

        if atype == "generate_content_studio_drafts":
            body = ContentStudioGenerateRequest(
                client_id=UUID(str(payload["client_id"])),
                campaign_id=await AiCommandCenterService._uuid(payload, "campaign_id"),
                content_count=int(payload.get("content_count") or 3),
                content_goal=payload.get("content_goal") or "Product promotion",
                platforms=list(payload.get("platforms") or []),
                media_asset_ids=[],
            )
            result = await ContentStudioService.generate(db, body)
            return {
                "entity": "content_studio",
                "generated_count": result.get("generated_count", 0),
                "drafts": result.get("drafts", []),
            }

        if atype == "create_crm_lead":
            body = CrmLeadCreate(
                client_id=UUID(str(payload["client_id"])),
                name=str(payload.get("name") or "New lead"),
                company=payload.get("company"),
                phone=payload.get("phone"),
                email=payload.get("email"),
                telegram=payload.get("telegram"),
                interest=payload.get("interest"),
                notes=payload.get("notes"),
                source=payload.get("source") or "manual",
            )
            result = await CrmService.create_lead(db, body)
            return {"entity": "crm_lead", "id": str(result["id"]), "name": result.get("name")}

        if atype == "create_deal_note":
            deal_id = UUID(str(payload["deal_id"]))
            note = str(payload.get("note") or payload.get("title") or "AI Command note")
            body = CrmDealEventCreate(
                event_type="note",
                title=str(payload.get("title") or "Note")[:255],
                payload_json={"note": note[:2000], "source": "ai_command"},
            )
            result = await DealService.add_event(db, deal_id, body)
            return {"entity": "deal_event", "id": str(result["id"]), "deal_id": str(deal_id)}

        if atype == "run_audit":
            result = await AuditService.run(db)
            critical = [i for i in (result.get("issues") or []) if i.get("severity") == "critical"]
            return {
                "entity": "audit",
                "issue_count": len(result.get("issues") or []),
                "critical_count": len(critical),
            }

        if atype == "run_sales_agent_scan":
            result = await SalesAgentService.scan(db)
            return {
                "entity": "sales_agent_scan",
                "scanned": result.get("scanned", 0),
                "created": result.get("created", 0),
            }

        if atype == "run_buyer_finder":
            product_id = payload.get("product_id")
            if not product_id:
                from app.models.product import Product
                client_id = payload.get("client_id")
                q = select(Product.id).order_by(Product.created_at.desc()).limit(1)
                if client_id:
                    q = q.where(Product.client_id == UUID(str(client_id)))
                pid = await db.scalar(q)
                if not pid:
                    raise HTTPException(status_code=400, detail="product_id required for buyer finder")
                product_id = pid
            result = await BuyerFinderService.analyze_product(db, UUID(str(product_id)))
            return {
                "entity": "buyer_finder",
                "product_id": str(product_id),
                "analyzed_count": result.get("analyzed_count", 0),
            }

        if atype == "create_attribution_link":
            body = AttributionLinkCreate(
                client_id=UUID(str(payload["client_id"])),
                channel=payload.get("channel") or "website",
                destination_url=str(payload.get("destination_url") or "https://example.com"),
                title=str(payload.get("title") or "Tracking link"),
                campaign_id=await AiCommandCenterService._uuid(payload, "campaign_id"),
                product_id=await AiCommandCenterService._uuid(payload, "product_id"),
                description=payload.get("description"),
            )
            result = await AttributionLinkService.create(db, body)
            return {"entity": "attribution_link", "id": str(result["id"]), "tracking_url": result.get("tracking_url")}

        if atype == "create_landing_page_draft":
            import re as _re
            slug = str(payload.get("slug") or "landing-draft")
            slug = _re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")[:120] or "landing-draft"
            body = LandingPageCreate(
                client_id=UUID(str(payload["client_id"])),
                slug=slug,
                title=str(payload.get("title") or "Landing page draft"),
                subtitle=payload.get("subtitle"),
                description=payload.get("description"),
                campaign_id=await AiCommandCenterService._uuid(payload, "campaign_id"),
                product_id=await AiCommandCenterService._uuid(payload, "product_id"),
                status="draft",
            )
            result = await LandingPageService.create(db, body)
            return {"entity": "landing_page", "id": str(result["id"]), "public_url": result.get("public_url")}

        if atype == "show_hot_leads":
            cid = await AiCommandCenterService._uuid(payload, "client_id")
            leads = await LeadIntelligenceService.list_hot_leads(db, client_id=cid, limit=15)
            return {"entity": "hot_leads", "count": len(leads), "items": leads}

        if atype == "show_neglected_leads":
            cid = await AiCommandCenterService._uuid(payload, "client_id")
            leads = await LeadIntelligenceService.list_neglected_leads(db, client_id=cid, limit=15)
            return {"entity": "neglected_leads", "count": len(leads), "items": leads}

        if atype == "score_all_leads":
            from app.schemas.crm import LeadRescoreRequest
            cid = await AiCommandCenterService._uuid(payload, "client_id")
            limit = int(payload.get("limit") or 50)
            result = await LeadIntelligenceService.rescore_leads(
                db,
                LeadRescoreRequest(client_id=cid, limit=min(limit, 500)),
            )
            return {"entity": "lead_rescore", **result}

        raise HTTPException(status_code=400, detail=f"Unknown action: {atype}")

    @staticmethod
    async def execute(db: AsyncSession, command_id: UUID) -> dict[str, Any]:
        r = await db.execute(
            select(AiCommand)
            .options(selectinload(AiCommand.actions))
            .where(AiCommand.id == command_id)
        )
        cmd = r.scalar_one_or_none()
        if not cmd:
            raise HTTPException(status_code=404, detail="Command not found")
        if cmd.status not in ("awaiting_confirmation", "draft"):
            raise HTTPException(status_code=400, detail=f"Command cannot be executed (status={cmd.status})")

        cmd.status = "executing"
        await db.commit()
        logger.info("%s executing: id=%s actions=%s", _MARKER, command_id, len(cmd.actions))

        plan_meta = cmd.result_json or {}
        action_results: list[dict[str, Any]] = []
        had_failure = False
        critical_failed = False

        for action in sorted(cmd.actions, key=lambda a: a.created_at):
            label = next(
                (a.get("label") for a in (cmd.action_plan_json or []) if a.get("action_type") == action.action_type),
                action.action_type,
            )
            is_critical = any(
                a.get("is_critical")
                for a in (cmd.action_plan_json or [])
                if a.get("action_type") == action.action_type
            )
            if action.status == "completed":
                action_results.append({
                    "id": action.id,
                    "action_type": action.action_type,
                    "label": label,
                    "status": action.status,
                    "result": action.result_json,
                })
                continue

            try:
                result = await AiCommandCenterService._execute_one(db, action)
                action.status = "completed"
                action.result_json = result
                action.error = None
                await db.commit()
                logger.info(
                    "%s action completed: command=%s type=%s",
                    _MARKER, command_id, action.action_type,
                )
                action_results.append({
                    "id": action.id,
                    "action_type": action.action_type,
                    "label": label,
                    "status": "completed",
                    "result": result,
                })
            except HTTPException as exc:
                had_failure = True
                action.status = "failed"
                action.error = str(exc.detail)
                await db.commit()
                logger.warning(
                    "%s failed: command=%s type=%s error=%s",
                    _MARKER, command_id, action.action_type, exc.detail,
                )
                action_results.append({
                    "id": action.id,
                    "action_type": action.action_type,
                    "label": label,
                    "status": "failed",
                    "error": str(exc.detail),
                })
                if is_critical:
                    critical_failed = True
                    for remaining in cmd.actions:
                        if remaining.status == "pending":
                            remaining.status = "skipped"
                    await db.commit()
                    break
            except Exception as exc:
                had_failure = True
                action.status = "failed"
                action.error = str(exc)
                await db.commit()
                logger.warning(
                    "%s failed: command=%s type=%s error=%s",
                    _MARKER, command_id, action.action_type, exc,
                )
                action_results.append({
                    "id": action.id,
                    "action_type": action.action_type,
                    "label": label,
                    "status": "failed",
                    "error": str(exc),
                })

        await db.refresh(cmd)
        for action in cmd.actions:
            if action.status == "pending" and not critical_failed:
                action.status = "skipped"
        cmd.status = "failed" if had_failure and critical_failed else ("failed" if had_failure else "completed")
        cmd.result_json = {
            **plan_meta,
            "action_results": action_results,
        }
        if had_failure and critical_failed:
            cmd.error = "Critical action failed; remaining actions skipped"
        elif had_failure:
            cmd.error = "Some actions failed; non-critical actions continued"
        await db.commit()

        logger.info("%s execute finished: id=%s status=%s", _MARKER, command_id, cmd.status)

        return {
            "command_id": cmd.id,
            "status": cmd.status,
            "summary": plan_meta.get("summary"),
            "actions": action_results,
            "error": cmd.error,
        }

    @staticmethod
    async def history(
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        total = int(await db.scalar(select(func.count()).select_from(AiCommand)) or 0)
        r = await db.execute(
            select(AiCommand)
            .options(selectinload(AiCommand.actions))
            .order_by(AiCommand.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        items = []
        for cmd in r.scalars().all():
            meta = cmd.result_json or {}
            completed = sum(1 for a in cmd.actions if a.status == "completed")
            failed = sum(1 for a in cmd.actions if a.status == "failed")
            items.append({
                "id": cmd.id,
                "raw_command": cmd.raw_command,
                "parsed_intent": cmd.parsed_intent,
                "status": cmd.status,
                "summary": meta.get("summary"),
                "action_count": len(cmd.actions),
                "completed_count": completed,
                "failed_count": failed,
                "created_at": cmd.created_at,
                "updated_at": cmd.updated_at,
            })
        return {"items": items, "total": total}

    @staticmethod
    async def get_command(db: AsyncSession, command_id: UUID) -> dict[str, Any]:
        r = await db.execute(
            select(AiCommand)
            .options(selectinload(AiCommand.actions))
            .where(AiCommand.id == command_id)
        )
        cmd = r.scalar_one_or_none()
        if not cmd:
            raise HTTPException(status_code=404, detail="Command not found")
        meta = cmd.result_json or {}
        plan = cmd.action_plan_json or []
        label_map = {a.get("action_type"): a.get("label") for a in plan if isinstance(a, dict)}
        actions = []
        for a in cmd.actions:
            actions.append({
                "id": a.id,
                "action_type": a.action_type,
                "label": label_map.get(a.action_type, a.action_type),
                "status": a.status,
                "result": a.result_json,
                "error": a.error,
            })
        return {
            "id": cmd.id,
            "raw_command": cmd.raw_command,
            "parsed_intent": cmd.parsed_intent,
            "status": cmd.status,
            "summary": meta.get("summary"),
            "risk_level": meta.get("risk_level"),
            "unsupported_parts": meta.get("unsupported_parts") or [],
            "actions": actions,
            "result_json": cmd.result_json,
            "error": cmd.error,
            "created_at": cmd.created_at,
            "updated_at": cmd.updated_at,
        }
