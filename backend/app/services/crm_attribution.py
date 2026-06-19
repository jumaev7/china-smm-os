"""CRM lead attribution helpers — shared SQL and Python fallbacks."""
from __future__ import annotations

from sqlalchemy import func

from app.models.crm_lead import CrmLead

ATTRIBUTION_LABELS: dict[str, str] = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "wechat": "WeChat",
    "website": "Website",
    "referral": "Referral",
    "manual": "Manual",
    "other": "Other",
}


def attribution_source_expr(*, include_attribution_source: bool = True):
    """SQL: attribution_source → source → 'other' (falls back when column missing)."""
    if include_attribution_source:
        return func.coalesce(CrmLead.attribution_source, CrmLead.source, "other")
    return func.coalesce(CrmLead.source, "other")


def normalize_attribution_key(raw: str | None) -> str:
    key = str(raw or "other").lower().strip()
    if key not in ATTRIBUTION_LABELS:
        return "other"
    return key


def effective_attribution_from_lead(lead: CrmLead | None, *, include_attribution_source: bool = True) -> str:
    if not lead:
        return "other"
    if include_attribution_source:
        return normalize_attribution_key(lead.attribution_source or lead.source)
    return normalize_attribution_key(lead.source)
