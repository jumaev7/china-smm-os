"""Deterministic publishing review check modules."""
from __future__ import annotations

from app.services.publishing_intelligence.checks.caption import run_caption_checks
from app.services.publishing_intelligence.checks.compliance import run_compliance_checks
from app.services.publishing_intelligence.checks.cta import run_cta_checks
from app.services.publishing_intelligence.checks.hashtag import run_hashtag_checks
from app.services.publishing_intelligence.checks.keyword import run_keyword_checks
from app.services.publishing_intelligence.checks.language import run_language_checks
from app.services.publishing_intelligence.checks.media import run_media_checks
from app.services.publishing_intelligence.checks.platform_fit import run_platform_fit_checks
from app.services.publishing_intelligence.checks.scheduling import run_scheduling_checks
from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext


def run_all_checks(
    ctx: ReviewContext,
    *,
    account_status_by_platform: dict[str, str] | None = None,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.extend(run_caption_checks(ctx))
    results.extend(run_platform_fit_checks(ctx))
    results.extend(run_cta_checks(ctx))
    results.extend(run_hashtag_checks(ctx))
    results.extend(run_keyword_checks(ctx))
    results.extend(run_media_checks(ctx))
    results.extend(run_language_checks(ctx))
    results.extend(run_compliance_checks(ctx))
    results.extend(
        run_scheduling_checks(ctx, account_status_by_platform=account_status_by_platform or {})
    )
    return results
