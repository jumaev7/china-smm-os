"""Compliance-readiness checks — deterministic internal patterns only (not legal advice)."""
from __future__ import annotations

import re

from app.services.publishing_intelligence.checks._helpers import check, combined_caption_text, find_urls
from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext

# Reuse patterns similar to intelligence normalizer redaction keys.
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|secret|password|bearer\s+[a-z0-9\-._~+/]+=*)\b"
    r"|sk-[a-zA-Z0-9]{10,}"
    r"|xox[baprs]-[a-zA-Z0-9-]+",
)
_PLACEHOLDER_RE = re.compile(
    r"(?i)\b(todo|fixme|tbd|placeholder|xxx+|lorem ipsum|insert (text|here)|\[your .+?\])\b",
)
_DRAFT_RE = re.compile(r"(?i)\b(draft|wip|do not publish|не публиковать|черновик)\b")
_TEST_RE = re.compile(r"(?i)\b(test post|testing only|ignore this|asdasd|qwerty)\b")
_PROHIBITED_RE = re.compile(r"(?i)<script|javascript:")


def run_compliance_checks(ctx: ReviewContext) -> list[CheckResult]:
    text = combined_caption_text(ctx)
    results: list[CheckResult] = []

    # Disclosure — soft: only if affiliate/ad-like markers without disclosure
    ad_markers = re.search(r"(?i)\b(sponsored|affiliate|партнерск|реклама)\b", text or "")
    disclosure = re.search(r"(?i)\b(ad\b|реклама|#ad|#реклама|партнерский материал)\b", text or "")
    if ad_markers and not disclosure:
        results.append(
            check(
                "missing_required_disclosure",
                "compliance_readiness",
                "warning",
                score=50,
                weight=2,
                severity="warning",
                evidence={"note": "Heuristic disclosure readiness — not legal advice"},
                recommendation_key="add_disclosure_if_required",
            )
        )
    else:
        results.append(
            check(
                "missing_required_disclosure",
                "compliance_readiness",
                "passed" if text else "not_applicable",
                score=100 if text else None,
                weight=1,
                evidence={"ad_markers": bool(ad_markers)},
            )
        )

    placeholders = _PLACEHOLDER_RE.findall(text or "")
    results.append(
        check(
            "forbidden_placeholder",
            "compliance_readiness",
            "failed" if placeholders else "passed",
            score=0 if placeholders else 100,
            weight=3,
            severity="critical" if placeholders else "info",
            evidence={"matches": len(placeholders)},
            recommendation_key="remove_placeholders" if placeholders else None,
        )
    )

    bad_schemes = []
    for url in find_urls(text):
        if re.match(r"(?i)(javascript:|data:|file:)", url):
            bad_schemes.append("unsafe_scheme")
        elif url.lower().startswith("http://"):
            bad_schemes.append("insecure_http")
    results.append(
        check(
            "unsupported_link_scheme",
            "compliance_readiness",
            "failed" if any(s == "unsafe_scheme" for s in bad_schemes) else (
                "warning" if bad_schemes else "passed"
            ),
            score=0 if any(s == "unsafe_scheme" for s in bad_schemes) else (70 if bad_schemes else 100),
            weight=2,
            severity="critical" if any(s == "unsafe_scheme" for s in bad_schemes) else "info",
            evidence={"issues": bad_schemes},
            recommendation_key="fix_link_scheme" if bad_schemes else None,
        )
    )

    secrets = bool(_SECRET_RE.search(text or ""))
    results.append(
        check(
            "sensitive_secret_pattern",
            "compliance_readiness",
            "failed" if secrets else "passed",
            score=0 if secrets else 100,
            weight=3,
            severity="critical" if secrets else "info",
            evidence={"detected": secrets},
            recommendation_key="remove_secrets_from_caption" if secrets else None,
        )
    )

    test_info = bool(_TEST_RE.search(text or ""))
    results.append(
        check(
            "internal_test_text",
            "compliance_readiness",
            "warning" if test_info else "passed",
            score=40 if test_info else 100,
            weight=2,
            severity="warning" if test_info else "info",
            evidence={"detected": test_info},
            recommendation_key="remove_test_text" if test_info else None,
        )
    )

    draft = bool(_DRAFT_RE.search(text or ""))
    results.append(
        check(
            "draft_marker_present",
            "compliance_readiness",
            "warning" if draft else "passed",
            score=35 if draft else 100,
            weight=2,
            severity="warning" if draft else "info",
            evidence={"detected": draft},
            recommendation_key="remove_draft_markers" if draft else None,
        )
    )

    prohibited = bool(_PROHIBITED_RE.search(text or ""))
    results.append(
        check(
            "prohibited_token_pattern",
            "compliance_readiness",
            "failed" if prohibited else "passed",
            score=0 if prohibited else 100,
            weight=2,
            severity="critical" if prohibited else "info",
            evidence={"detected": prohibited},
            recommendation_key="remove_prohibited_tokens" if prohibited else None,
        )
    )
    return results
