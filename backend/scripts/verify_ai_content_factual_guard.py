"""Factual guard verification for Governed AI Content Adaptation.

Unit-level checks (no DB required): protected fact modifications rejected;
valid adaptations that preserve facts pass.

Run from backend/:  python scripts/verify_ai_content_factual_guard.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["AI_PLATFORM_ENABLED"] = "true"
os.environ["AI_DEFAULT_PROVIDER"] = "mock"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def main() -> int:
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    from app.services.ai_content.factual_guard import (
        extract_protected_facts,
        validate_factual_consistency,
    )
    from app.services.ai_platform.structured_output import parse_structured_output

    source = (
        "Launch price is $99 on 2026-07-01. Order at https://example.com/buy. "
        "Promo CODE-STEEL20 applies. Model XR-450 ships in 5 kg packs."
    )
    facts = extract_protected_facts(
        source,
        approved_urls=["https://example.com/buy"],
        product_names=["XR-450"],
    )
    record("extract_facts_nonempty", len(facts) >= 3, str(len(facts)))
    record(
        "extract_has_price_url_promo",
        {"price", "url", "promo_code"} <= {f.category for f in facts},
        str(sorted({f.category for f in facts})),
    )

    def _out(caption: str, link: str | None = "https://example.com/buy"):
        return parse_structured_output({
            "platform": "instagram",
            "locale": "en",
            "length_profile": "standard",
            "caption": caption,
            "hashtags": ["#steel"],
            "cta": None,
            "link": link,
            "transformations": [
                {
                    "type": "rewrite_for_platform",
                    "reason": "platform_style",
                    "source_sections": ["paragraph:0"],
                }
            ],
            "claims": [{"text": "$99", "source_reference": "source:price:0"}],
            "warnings": [],
        })

    ok = validate_factual_consistency(
        source_facts=facts,
        output=_out(source),
        length_profile="standard",
        approved_urls=["https://example.com/buy"],
    )
    record("valid_preserved_passed", ok.status == "passed", str(ok.errors[:3]))

    bad_price = validate_factual_consistency(
        source_facts=facts,
        output=_out(source.replace("$99", "$149")),
        length_profile="standard",
        approved_urls=["https://example.com/buy"],
    )
    record(
        "modified_price_rejected",
        bad_price.status == "failed",
        str(bad_price.errors[:4]),
    )

    bad_url = validate_factual_consistency(
        source_facts=facts,
        output=_out(
            source.replace("https://example.com/buy", "https://evil.example/x"),
            link="https://evil.example/x",
        ),
        length_profile="standard",
        approved_urls=["https://example.com/buy"],
    )
    record("changed_url_rejected", bad_url.status == "failed", str(bad_url.errors[:4]))

    bad_promo = validate_factual_consistency(
        source_facts=facts,
        output=_out(source.replace("CODE-STEEL20", "CODE-HACK99")),
        length_profile="standard",
        approved_urls=["https://example.com/buy"],
    )
    record(
        "modified_promo_rejected",
        bad_promo.status == "failed",
        str(bad_promo.errors[:4]),
    )

    invented = validate_factual_consistency(
        source_facts=facts,
        output=_out(source + " Only 777 seats left."),
        length_profile="standard",
        approved_urls=["https://example.com/buy"],
    )
    record(
        "new_number_rejected",
        invented.status == "failed" and any("number" in e for e in invented.errors),
        str(invented.errors[:4]),
    )

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
