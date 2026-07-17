"""Protected-fact extraction and factual consistency validation."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.services.ai_content.schemas import FactualValidationResult, ProtectedFact
from app.services.ai_platform.structured_output import PlatformAdaptationOutput


_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"\+\d{7,15}\b|\(\d{2,4}\)\s*\d{3}[\s-]?\d{2,}|\b\d{3}[\s-]\d{3}[\s-]\d{4}\b"
)
_PRICE_RE = re.compile(
    r"(?i)(?:\$|EUR|USD|RUB|UZS|€|£|¥|₽)\s?\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s?(?:USD|EUR|RUB|UZS)\b"
)
_PERCENT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s?%\b")
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_PROMO_RE = re.compile(r"\b(?:PROMO|CODE)[-_:]?\s*[A-Z0-9]{4,}\b", re.IGNORECASE)
_MODEL_RE = re.compile(r"\b[A-Z]{2,5}[-_]?\d{2,}[A-Z0-9-]*\b")
_MEASUREMENT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:mm|cm|m|km|kg|g|ml|l|pcs)\b", re.IGNORECASE
)


def extract_protected_facts(
    text: str,
    *,
    company_names: list[str] | None = None,
    product_names: list[str] | None = None,
    approved_urls: list[str] | None = None,
    mandatory_disclosures: list[str] | None = None,
) -> list[ProtectedFact]:
    facts: list[ProtectedFact] = []
    seen: set[str] = set()

    def _add(category: str, token: str, *, mandatory: bool = False, ref: str | None = None) -> None:
        t = (token or "").strip()
        if not t or t in seen:
            return
        seen.add(t)
        facts.append(
            ProtectedFact(
                category=category,
                token=t,
                mandatory=mandatory,
                source_reference=ref,
            )
        )

    body = text or ""
    for i, m in enumerate(_URL_RE.finditer(body)):
        _add("url", m.group(0), mandatory=True, ref=f"source:url:{i}")
    for url in approved_urls or []:
        _add("url", url, mandatory=True, ref="source:approved_url")
    for i, m in enumerate(_EMAIL_RE.finditer(body)):
        _add("email", m.group(0), mandatory=True, ref=f"source:email:{i}")
    for i, m in enumerate(_PHONE_RE.finditer(body)):
        _add("phone", m.group(0), mandatory=True, ref=f"source:phone:{i}")
    for i, m in enumerate(_PRICE_RE.finditer(body)):
        _add("price", m.group(0), mandatory=True, ref=f"source:price:{i}")
    for i, m in enumerate(_PERCENT_RE.finditer(body)):
        _add("percentage", m.group(0), mandatory=True, ref=f"source:percent:{i}")
    for i, m in enumerate(_DATE_RE.finditer(body)):
        _add("date", m.group(0), mandatory=True, ref=f"source:date:{i}")
    for i, m in enumerate(_MEASUREMENT_RE.finditer(body)):
        _add("measurement", m.group(0), mandatory=True, ref=f"source:measure:{i}")
    for i, m in enumerate(_PROMO_RE.finditer(body)):
        _add("promo_code", m.group(0), mandatory=True, ref=f"source:promo:{i}")
    for i, m in enumerate(_MODEL_RE.finditer(body)):
        _add("model_number", m.group(0), mandatory=False, ref=f"source:model:{i}")
    for name in company_names or []:
        if name and name in body:
            _add("company_name", name, mandatory=True, ref="source:company")
    for name in product_names or []:
        if name and name in body:
            _add("product_name", name, mandatory=True, ref="source:product")
    for disc in mandatory_disclosures or []:
        if disc:
            _add("disclosure", disc, mandatory=True, ref="source:disclosure")

    covered = {f.token for f in facts}
    date_spans = [m.span() for m in _DATE_RE.finditer(body)]
    url_spans = [m.span() for m in _URL_RE.finditer(body)]
    price_spans = [m.span() for m in _PRICE_RE.finditer(body)]
    skip_spans = date_spans + url_spans + price_spans
    for i, m in enumerate(_NUMBER_RE.finditer(body)):
        tok = m.group(0)
        if tok in covered or len(tok) <= 1:
            continue
        start, _end = m.span()
        if any(s <= start < e for s, e in skip_spans):
            continue
        _add("number", tok, mandatory=False, ref=f"source:number:{i}")

    return facts


def _normalize_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")
    except Exception:
        return url.strip()


def _normalize_price(token: str) -> str:
    return re.sub(r"\s+", "", (token or "").strip().lower())


def validate_factual_consistency(
    *,
    source_facts: list[ProtectedFact],
    output: PlatformAdaptationOutput,
    length_profile: str,
    approved_urls: list[str] | None = None,
) -> FactualValidationResult:
    """Deterministic post-generation validation. Limited semantic verification in Phase 2B."""
    result = FactualValidationResult(status="passed")
    caption = output.caption or ""
    output_urls = {_normalize_url(u) for u in _URL_RE.findall(caption)}
    if output.link:
        output_urls.add(_normalize_url(output.link))
    approved = {_normalize_url(u) for u in (approved_urls or [])}

    mandatory_categories = {
        "url", "email", "phone", "price", "percentage", "date",
        "measurement", "promo_code", "company_name", "product_name", "disclosure",
    }

    for fact in source_facts:
        if fact.token in caption or (
            fact.category == "url" and _normalize_url(fact.token) in output_urls
        ):
            result.preserved.append(fact.token)
            result.checks[f"preserved:{fact.category}"] = "ok"
            continue
        if fact.category == "price" and _normalize_price(fact.token) in _normalize_price(caption):
            result.preserved.append(fact.token)
            continue
        if fact.category in ("number", "price", "percentage", "date", "measurement", "model_number"):
            result.modified.append(fact.token)
            result.errors.append(f"modified_protected_fact:{fact.category}")
            key = "protected_number_consistency" if fact.category == "number" else f"{fact.category}_consistency"
            result.checks[key] = "failed"
            continue
        if fact.category == "url":
            result.modified.append(fact.token)
            result.errors.append("changed_url")
            result.checks["url_consistency"] = "failed"
            continue
        if fact.mandatory or fact.category in mandatory_categories:
            if length_profile == "short" and fact.category in ("number", "model_number") and not fact.mandatory:
                result.removed.append(fact.token)
                result.checks[f"removed:{fact.category}"] = "allowed_short"
            else:
                result.removed.append(fact.token)
                result.errors.append(f"removed_mandatory:{fact.category}")
                result.checks[
                    "mandatory_disclosure_presence"
                    if fact.category == "disclosure"
                    else f"{fact.category}_consistency"
                ] = "failed"
        else:
            result.removed.append(fact.token)
            if length_profile in ("short", "standard"):
                result.checks[f"removed:{fact.category}"] = "allowed"

    source_tokens = {f.token for f in source_facts}
    source_prices = {_normalize_price(f.token) for f in source_facts if f.category == "price"}
    source_urls = {_normalize_url(f.token) for f in source_facts if f.category == "url"} | approved
    source_corpus = " ".join(source_tokens)

    for m in _PRICE_RE.finditer(caption):
        tok = m.group(0)
        if tok in source_tokens or _normalize_price(tok) in source_prices:
            continue
        if any(_normalize_price(tok) == _normalize_price(s) for s in source_tokens):
            continue
        result.new.append(tok)
        result.errors.append("new_unsupported_price")
        result.checks["price_consistency"] = "failed"

    for m in _NUMBER_RE.finditer(caption):
        tok = m.group(0)
        if len(tok) <= 1:
            continue
        if tok in source_tokens or tok in source_corpus:
            continue
        if any(tok in s for s in source_tokens):
            continue
        # Skip numbers inside dates in the output caption
        date_spans = [span for span in (x.span() for x in _DATE_RE.finditer(caption))]
        start, _ = m.span()
        if any(s <= start < e for s, e in date_spans):
            continue
        result.new.append(tok)
        result.errors.append("new_unsupported_number")
        result.checks["protected_number_consistency"] = "failed"

    for url in output_urls:
        if url not in source_urls and url not in approved:
            result.new.append(url)
            result.errors.append("new_unsupported_url")
            result.checks["url_consistency"] = "failed"

    valid_refs = {f.source_reference for f in source_facts if f.source_reference}
    valid_refs.update({f"source:sentence:{i}" for i in range(50)})
    valid_refs.update({f"source:protected:{i}" for i in range(50)})
    valid_refs.add("source:sentence:0")
    for claim in output.claims:
        if claim.source_reference not in valid_refs and not claim.source_reference.startswith("source:"):
            result.errors.append("invalid_source_reference")
            result.checks["source_reference_validity"] = "failed"

    if result.errors:
        result.status = "failed"
    elif result.removed or result.modified:
        result.status = "warnings"

    for key in (
        "protected_number_consistency",
        "price_consistency",
        "date_consistency",
        "url_consistency",
        "product_name_consistency",
        "technical_spec_consistency",
        "mandatory_disclosure_presence",
        "unsupported_claim_detection",
        "source_reference_validity",
    ):
        result.checks.setdefault(
            key, "ok" if result.status == "passed" else result.checks.get(key, "skipped")
        )

    return result
