"""Provenance validation verification for the Deterministic Content Optimizer.

Proves the no-invention validator accepts source-derived and template-derived
text and rejects invented words, numbers, prices, URLs, and product names.
Also covers Unicode / mixed-script edge cases. No database required.

Run from backend/:  python scripts/verify_content_optimizer_provenance.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

    from app.services.content_optimizer.provenance import build_corpus, validate_variant

    source = (
        "Discover our export-ready steel components for global buyers.\n\n"
        "Price starts at $1200 per ton. Visit https://example.com/catalog today.\n"
        "Contact us to request a quote. #export #steel"
    )
    template = "Order now via our catalog."
    corpus = build_corpus([source, template, "#export", "#steel", "https://example.com/catalog"])

    ok = validate_variant(
        caption=(
            "Discover our export-ready steel components for global buyers.\n\n"
            "Contact us to request a quote."
        ),
        hashtags=["export", "steel"],
        cta="Contact us to request a quote",
        link="https://example.com/catalog",
        corpus=corpus,
    )
    record("source_only_variant_accepted", ok.ok, str(ok.extras))

    ok = validate_variant(
        caption="Order now via our catalog.",
        hashtags=[],
        cta="Order now via our catalog.",
        link=None,
        corpus=corpus,
    )
    record("approved_template_text_accepted", ok.ok, str(ok.extras))

    ok = validate_variant(
        caption="Discover our amazing export-ready steel components for global buyers.",
        hashtags=["export"],
        cta=None,
        link=None,
        corpus=corpus,
    )
    record("invented_word_rejected", not ok.ok, str(ok.extras))

    ok = validate_variant(
        caption="Price starts at $1500 per ton.",
        hashtags=[],
        cta=None,
        link=None,
        corpus=corpus,
    )
    record("changed_price_rejected", not ok.ok, str(ok.extras))

    ok = validate_variant(
        caption="Price starts at $1200 per ton.",
        hashtags=[],
        cta=None,
        link=None,
        corpus=corpus,
    )
    record("unchanged_price_accepted", ok.ok, str(ok.extras))

    ok = validate_variant(
        caption="Visit https://evil.example/phish today.",
        hashtags=[],
        cta=None,
        link="https://evil.example/phish",
        corpus=corpus,
    )
    record("changed_url_rejected", not ok.ok, str(ok.extras))

    ok = validate_variant(
        caption="Discover our export-ready titanium components for global buyers.",
        hashtags=[],
        cta=None,
        link=None,
        corpus=corpus,
    )
    record("changed_product_name_rejected", not ok.ok, str(ok.extras))

    ok = validate_variant(
        caption=(
            "Discover our export-ready steel components for global buyers.\n\n\n"
            "Contact us to request a quote."
        ),
        hashtags=["export", "steel"],
        cta=None,
        link=None,
        corpus=corpus,
    )
    record("formatting_only_changes_accepted", ok.ok, str(ok.extras))

    mixed = "钢 components 出口 ready. Contact us. 你好世界。"
    mixed_corpus = build_corpus([mixed, "#export"])
    ok = validate_variant(
        caption="钢 components 出口 ready.\n\nContact us.",
        hashtags=["export"],
        cta="Contact us",
        link=None,
        corpus=mixed_corpus,
    )
    record("mixed_script_edge_accepted", ok.ok, str(ok.extras))

    ok = validate_variant(
        caption="钢 components 出口 ready. 全新优惠 Contact us.",
        hashtags=[],
        cta=None,
        link=None,
        corpus=mixed_corpus,
    )
    record("mixed_script_invention_rejected", not ok.ok, str(ok.extras))

    emoji_src = "Ship worldwide 🎉 with full docs. Contact us today."
    emoji_corpus = build_corpus([emoji_src])
    ok = validate_variant(
        caption="Ship worldwide 🎉 with full docs.\n\nContact us today.",
        hashtags=[],
        cta="Contact us today",
        link=None,
        corpus=emoji_corpus,
    )
    record("unicode_emoji_formatting_accepted", ok.ok, str(ok.extras))

    ok = validate_variant(
        caption="Ship worldwide with full docs. Quantity is 999 units.",
        hashtags=[],
        cta=None,
        link=None,
        corpus=emoji_corpus,
    )
    record("invented_number_rejected", not ok.ok, str(ok.extras))

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
