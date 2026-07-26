"""Business Health v2 assessment engine (orchestration)."""
from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.business_health.aggregator import assemble_assessment
from app.services.business_health.evaluators import EVALUATORS
from app.services.business_health.observations import (
    collect_all_observations,
    resolve_tenant_id,
    sales_obs_from_executive_snapshot,
)
from app.services.business_health.policy import BUSINESS_HEALTH_VERSION, DOMAIN_WEIGHTS
from app.services.business_health.types import BusinessHealthAssessment, DomainHealthAssessment

logger = logging.getLogger(__name__)
MARKER = "[BusinessHealthV2]"


def assess_from_observations(
    observations: dict[str, dict[str, Any] | None],
    *,
    duration_ms: float | None = None,
) -> BusinessHealthAssessment:
    """Pure path: map observation dicts → domain assessments → aggregate."""
    domains: list[DomainHealthAssessment] = []
    for domain in DOMAIN_WEIGHTS:
        evaluator = EVALUATORS[domain]
        obs = observations.get(domain)
        try:
            assessment = evaluator(obs)
        except Exception as exc:  # noqa: BLE001 — isolate evaluator failures
            logger.warning("%s evaluator_failed domain=%s err=%s", MARKER, domain, type(exc).__name__)
            from app.services.business_health.evaluators import _unavailable

            assessment = _unavailable(domain, "error")
            assessment.summary = f"Evaluator error: {type(exc).__name__}"
        domains.append(assessment)
    return assemble_assessment(domains, duration_ms=duration_ms)


async def assess_business_health(
    db: AsyncSession,
    *,
    tenant_id: UUID | None = None,
    client_id: UUID | None = None,
    sales_preloaded: dict[str, Any] | None = None,
    executive_snapshot: Any | None = None,
) -> dict[str, Any]:
    """Compute Business Health v2 for an organization scope.

    Read-only. Does not mutate providers, CRM, billing, or automations.
    """
    started = time.perf_counter()
    errors: list[str] = []

    resolved_tenant = await resolve_tenant_id(db, tenant_id=tenant_id, client_id=client_id)
    if sales_preloaded is None and executive_snapshot is not None:
        sales_preloaded = sales_obs_from_executive_snapshot(executive_snapshot)

    observations = await collect_all_observations(
        db,
        tenant_id=resolved_tenant,
        client_id=client_id,
        sales_preloaded=sales_preloaded,
        errors=errors,
    )
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    assessment = assess_from_observations(observations, duration_ms=duration_ms)

    available = assessment.domains_evaluated
    unavailable = assessment.domains_unavailable
    logger.info(
        "%s assessed tenant=%s client=%s version=%s score=%s domains_ok=%s domains_na=%s duration_ms=%s errors=%s",
        MARKER,
        str(resolved_tenant) if resolved_tenant else None,
        str(client_id) if client_id else None,
        BUSINESS_HEALTH_VERSION,
        assessment.score,
        available,
        unavailable,
        duration_ms,
        len(errors),
    )
    payload = assessment.to_dict()
    if errors:
        payload["collection_errors"] = errors[:20]
    return payload
