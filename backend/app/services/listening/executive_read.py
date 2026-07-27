"""Dedicated Executive Copilot read model for Listening market intelligence.

Consumes ListeningIntelligenceService. Does not couple to raw mention tables
from ExecutiveCopilotService. Fixture data is always excluded. Coverage-
insufficient conclusions are suppressed. No Business Health weight changes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.listening.analytics.intelligence_service import ListeningIntelligenceService


async def executive_market_intelligence(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    window_key: str = "30d",
) -> dict[str, Any]:
    """Structured, evidence-backed market intelligence for Executive Copilot."""
    overview = await ListeningIntelligenceService.intelligence_overview(
        db,
        tenant_id,
        window_key=window_key,
        include_fixture=False,
        review_policy="default_exclude_irrelevant",
        timezone_name="UTC",
    )
    coverage = overview.get("coverage") or {}
    coverage_status = coverage.get("status") or "unavailable"
    limitations = list(overview.get("limitations") or [])

    market_anomaly = None
    for a in overview.get("notable_anomalies") or []:
        market_anomaly = {
            "code": a.get("code"),
            "severity": a.get("severity"),
            "explanation": a.get("explanation"),
            "evidence_mention_ids": list(a.get("evidence_mention_ids") or [])[:5],
            "category": "market_signal",
        }
        break

    dq_warning = None
    for a in overview.get("data_quality_anomalies") or []:
        dq_warning = {
            "code": a.get("code"),
            "severity": a.get("severity"),
            "explanation": a.get("explanation"),
            "category": "data_quality",
        }
        break

    strongest_change = None
    for s in overview.get("top_subjects") or []:
        if s.get("change_kind") in {"percentage", "new_activity"} and s.get("absolute_change") is not None:
            strongest_change = {
                "subject_id": s.get("subject_id"),
                "canonical_name": s.get("canonical_name"),
                "subject_type": s.get("subject_type"),
                "observed_mention_count": s.get("observed_mention_count"),
                "previous_comparable_count": s.get("previous_comparable_count"),
                "absolute_change": s.get("absolute_change"),
                "percentage_change": s.get("percentage_change"),
                "change_kind": s.get("change_kind"),
                "evidence_mention_ids": list(s.get("evidence_mention_ids") or [])[:5],
            }
            break

    emerging_topic = None
    for t in overview.get("emerging_topics") or []:
        emerging_topic = {
            "topic_id": t.get("topic_id"),
            "label": t.get("label"),
            "current_count": t.get("current_count"),
            "baseline_count": t.get("baseline_count"),
            "change_kind": t.get("change_kind"),
            "evidence_mention_ids": list(t.get("representative_mention_ids") or [])[:5],
            "detection_reason": t.get("detection_reason"),
        }
        break

    conclusions_suppressed = coverage_status in {"insufficient", "unavailable"}
    statements: list[dict[str, Any]] = []

    if coverage_status != "sufficient":
        statements.append({
            "kind": "coverage_warning",
            "text": (
                f"Listening coverage is '{coverage_status}'. "
                "Strong market conclusions are suppressed."
            ),
            "evidence_mention_ids": [],
            "category": "data_quality",
        })

    if dq_warning:
        statements.append({
            "kind": "data_quality",
            "text": dq_warning.get("explanation"),
            "evidence_mention_ids": [],
            "category": "data_quality",
            "code": dq_warning.get("code"),
        })

    if not conclusions_suppressed:
        if market_anomaly:
            statements.append({
                "kind": "anomaly",
                "text": market_anomaly.get("explanation"),
                "evidence_mention_ids": market_anomaly.get("evidence_mention_ids") or [],
                "category": "market_signal",
                "code": market_anomaly.get("code"),
            })
        if strongest_change:
            if strongest_change.get("change_kind") == "new_activity":
                text = (
                    f"Observed mentions for '{strongest_change['canonical_name']}' show "
                    f"new activity from 0 to {strongest_change['observed_mention_count']}."
                )
            else:
                text = (
                    f"Observed mentions for '{strongest_change['canonical_name']}' changed from "
                    f"{strongest_change.get('previous_comparable_count')} to "
                    f"{strongest_change.get('observed_mention_count')}."
                )
            statements.append({
                "kind": "subject_change",
                "text": text,
                "evidence_mention_ids": strongest_change.get("evidence_mention_ids") or [],
                "category": "market_signal",
            })
        if emerging_topic:
            statements.append({
                "kind": "emerging_topic",
                "text": emerging_topic.get("detection_reason"),
                "evidence_mention_ids": emerging_topic.get("evidence_mention_ids") or [],
                "category": "market_signal",
            })

    return {
        "available": True,
        "schema_version": "listening_executive_mi_v1",
        "coverage_status": coverage_status,
        "freshness_status": coverage.get("freshness_status"),
        "eligible_mention_count": overview.get("eligible_mention_count") or 0,
        "comparison_valid": bool(overview.get("comparison_valid")),
        "conclusions_suppressed": conclusions_suppressed,
        "highest_priority_anomaly": market_anomaly if not conclusions_suppressed else None,
        "strongest_subject_change": strongest_change if not conclusions_suppressed else None,
        "emerging_topic": emerging_topic if not conclusions_suppressed else None,
        "coverage_warning": {
            "status": coverage_status,
            "limitations": coverage.get("limitations") or [],
        },
        "data_quality_warning": dq_warning,
        "statements": statements,
        "evidence_href": "/listening/intelligence",
        "limitations": limitations,
        "read_only": True,
        "ai_generated": False,
        "business_health_unchanged": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def safe_executive_market_intelligence(
    db: AsyncSession,
    *,
    tenant_id: UUID | None,
) -> dict[str, Any]:
    if tenant_id is None:
        return {
            "available": False,
            "reason": "tenant_unavailable",
            "conclusions_suppressed": True,
            "statements": [],
            "business_health_unchanged": True,
        }
    try:
        return await executive_market_intelligence(db, tenant_id=tenant_id)
    except Exception:
        return {
            "available": False,
            "reason": "listening_intelligence_error",
            "conclusions_suppressed": True,
            "statements": [],
            "business_health_unchanged": True,
            "limitations": ["Market intelligence section degraded due to a calculation error."],
        }
