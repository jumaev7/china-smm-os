"""Unit tests for the Deterministic Content Optimizer (no DB).

Covers multilingual segmentation, URL/emoji/hashtag preservation, fingerprint
stability, transformation determinism, the no-invention provenance validator,
platform strategies, deterministic CTA/hashtag selection, the operation catalog
and the exposed configuration versions. Everything here is side-effect free and
runs without a database.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

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

    from app.services.content_optimizer import (
        OPTIMIZER_VERSION,
        SOURCE_FINGERPRINT_VERSION,
        VARIANT_FINGERPRINT_VERSION,
        ContentOptimizerService,
    )
    from app.services.content_optimizer import hashtag_optimizer as ht
    from app.services.content_optimizer.cta_selector import (
        select_existing_cta,
        source_has_cta,
    )
    from app.services.content_optimizer.provenance import (
        build_corpus,
        tokenize,
        validate_variant,
    )
    from app.services.content_optimizer.schemas import (
        LocaleSource,
        NormalizedSource,
        VariantDraft,
    )
    from app.services.content_optimizer.sentence_segmenter import (
        first_meaningful_sentence,
        segment,
        split_paragraphs,
        split_sentences,
    )
    from app.services.content_optimizer.source_fingerprint import (
        compute_source_fingerprint,
    )
    from app.services.content_optimizer.transformation_engine import (
        OperationContext,
        OPERATIONS,
        _op_deduplicate_exact_sentences,
        _op_truncate_at_sentence_boundary,
        list_operations,
        run_pipeline,
    )
    from app.services.content_optimizer.variant_fingerprint import (
        compute_variant_fingerprint,
    )
    from app.services.publishing_intelligence.platform_policies import (
        POLICY_CATALOG_VERSION,
    )

    # ---------------------------------------------------------------- helpers
    def make_source(
        text_en: str,
        *,
        hashtags: list[str] | None = None,
        links: list[str] | None = None,
        disclosure: str | None = None,
        platforms: list[str] | None = None,
    ) -> NormalizedSource:
        sections = segment(text_en)
        paragraphs = [s.text for s in sections]
        ls = LocaleSource(
            locale="en",
            short_text="",
            long_text=text_en,
            text=text_en,
            paragraphs=paragraphs,
            sections=sections,
            sentences=split_sentences(text_en),
            disclosure=disclosure,
        )
        return NormalizedSource(
            content_id=uuid4(),
            tenant_id=uuid4(),
            content_type="text",
            primary_locale="en",
            locales=["en"],
            platforms=platforms or ["telegram", "instagram"],
            locale_sources={"en": ls},
            hashtags=list(hashtags or []),
            hashtags_raw=" ".join(ht.render_hashtag(t) for t in (hashtags or [])),
            keywords=[],
            links=list(links or []),
            title=None,
            description=None,
        )

    # ---------------------------------------------------- 1. segmentation ----
    en = split_sentences("Hello world. How are you today? I am doing fine.")
    record("segment_en_sentences", len(en) == 3, str(en))

    ru = split_sentences("Привет мир. Как у вас дела? Всё хорошо.")
    record("segment_ru_sentences", len(ru) == 3, str(ru))

    uz = split_sentences("Salom dunyo. Qalaysiz bugun? Men yaxshiman.")
    record("segment_uz_latin_sentences", len(uz) == 3, str(uz))

    zh = split_sentences("你好世界。你今天好吗？我很好。")
    record("segment_zh_punctuation_sentences", len(zh) == 3, str(zh))

    # Abbreviations should not create false boundaries.
    abbr = split_sentences("Dr. Ivanov leads the plant. It ships worldwide.")
    record("segment_abbreviation_guard", len(abbr) == 2, str(abbr))

    paras = split_paragraphs("Block one line.\n\nBlock two line.")
    record("segment_paragraph_split", len(paras) == 2, str(paras))

    first = first_meaningful_sentence("   \n *** \nReal opening sentence here. More.")
    record("segment_first_meaningful", bool(first and "Real opening" in first), str(first))

    # ------------------------------------- 2. URL/emoji/hashtag preservation -
    preserve_text = "Order at https://example.com/catalog today! Save 20% 🎉 #export"
    preserve = split_sentences(preserve_text)
    joined = " ".join(preserve)
    record(
        "preserve_url_intact",
        "https://example.com/catalog" in joined,
        str(preserve),
    )
    record("preserve_emoji_intact", "🎉" in joined)
    record("preserve_hashtag_intact", "#export" in joined)
    record(
        "preserve_url_not_split_on_dot",
        any("https://example.com/catalog" in s for s in preserve),
    )

    # Tokenizer treats URL/hashtag/number as atomic, preserved tokens.
    toks = tokenize(preserve_text)
    record("tokenize_url_atomic", "u:https://example.com/catalog" in toks)
    record("tokenize_hashtag_atomic", "h:export" in toks)
    record("tokenize_number_atomic", "n:20" in toks)

    # ------------------------------------------- 3. fingerprint stability ----
    fp_kwargs = dict(
        target_platforms=["telegram", "instagram"],
        target_locales=["en"],
        length_profiles=["short", "standard"],
        cta_template_texts=["Contact us today."],
        optimizer_version=OPTIMIZER_VERSION,
        policy_version=POLICY_CATALOG_VERSION,
    )
    src_a = make_source("Durable steel components for export buyers. Contact us today.")
    src_b = make_source("Durable steel components for export buyers. Contact us today.")
    fp_a = compute_source_fingerprint(src_a, **fp_kwargs)
    fp_b = compute_source_fingerprint(src_b, **fp_kwargs)
    record("source_fp_same_input_same_hash", fp_a == fp_b, f"{fp_a[:12]} vs {fp_b[:12]}")

    src_edit = make_source("Durable steel components for export buyers. Contact us tomorrow.")
    fp_edit = compute_source_fingerprint(src_edit, **fp_kwargs)
    record("source_fp_relevant_edit_changes", fp_edit != fp_a)

    fp_reorder = compute_source_fingerprint(
        src_a,
        **{**fp_kwargs, "target_platforms": ["instagram", "telegram"]},
    )
    record("source_fp_platform_order_stable", fp_reorder == fp_a)

    fp_profile_reorder = compute_source_fingerprint(
        src_a,
        **{**fp_kwargs, "length_profiles": ["standard", "short"]},
    )
    record("source_fp_profile_order_stable", fp_profile_reorder == fp_a)

    vfp_kwargs = dict(
        platform="telegram",
        locale="en",
        length_profile="short",
        caption="Contact us today.",
        hashtags=["export", "steel"],
        cta="Contact us today.",
        link=None,
        optimizer_version=OPTIMIZER_VERSION,
        policy_version=POLICY_CATALOG_VERSION,
    )
    v1 = compute_variant_fingerprint(**vfp_kwargs)
    v2 = compute_variant_fingerprint(**vfp_kwargs)
    record("variant_fp_same_input_same_hash", v1 == v2)
    v3 = compute_variant_fingerprint(**{**vfp_kwargs, "caption": "Contact us tomorrow."})
    record("variant_fp_caption_change_differs", v3 != v1)

    # -------------------------------------- 4. transformation determinism ----
    dedup_draft = VariantDraft(
        platform="telegram",
        locale="en",
        length_profile="standard",
        paragraphs=["Great deal. Great deal. Buy today."],
        hashtags=[],
    )
    ctx = OperationContext(source_text="Great deal. Buy today.")
    d_out, d_changed, _, _ = _op_deduplicate_exact_sentences(dedup_draft, {}, ctx)
    record(
        "transform_duplicate_sentence_removed",
        d_changed and d_out.caption_text().count("Great deal.") == 1,
        d_out.caption_text(),
    )

    trunc_draft = VariantDraft(
        platform="telegram",
        locale="en",
        length_profile="short",
        paragraphs=[
            "First sentence stays whole. Second sentence is long. Third sentence dropped."
        ],
        hashtags=[],
    )
    t_out, t_changed, _, _ = _op_truncate_at_sentence_boundary(
        trunc_draft, {"max_chars": 40}, ctx
    )
    caption = t_out.caption_text()
    record(
        "transform_truncate_at_sentence_boundary",
        t_changed and caption.endswith(".") and "First sentence stays whole." in caption,
        caption,
    )
    # No partial word: every truncated sentence is a verbatim source sentence.
    src_sentences = set(split_sentences(trunc_draft.paragraphs[0]))
    kept_sentences = split_sentences(caption)
    record(
        "transform_truncate_no_paraphrase",
        all(s in src_sentences for s in kept_sentences),
        str(kept_sentences),
    )

    # Determinism: same pipeline twice → identical caption + operation sequence.
    from app.services.content_optimizer.length_profiles import build_pipeline
    from app.services.content_optimizer.platform_strategies import get_strategy
    from app.services.publishing_intelligence.platform_policies import get_policy

    strategy = get_strategy("instagram")
    policy = get_policy("instagram") or {}
    base_draft = VariantDraft(
        platform="instagram",
        locale="en",
        length_profile="standard",
        paragraphs=[
            "Discover durable steel components for export buyers.",
            "We ship worldwide. Contact us today for a quote.",
        ],
        hashtags=["export", "steel", "export"],
    )
    steps = build_pipeline(strategy, "standard", policy)
    op_ctx = OperationContext(source_text=" ".join(base_draft.paragraphs), policy=policy)
    out1, recs1 = run_pipeline(base_draft, steps, op_ctx)
    out2, recs2 = run_pipeline(base_draft, steps, op_ctx)
    record(
        "transform_pipeline_deterministic_caption",
        out1.caption_text() == out2.caption_text(),
    )
    record(
        "transform_pipeline_deterministic_ops",
        [r.operation_key for r in recs1] == [r.operation_key for r in recs2],
    )

    # ------------------------------------------- 5. provenance validator -----
    corpus = build_corpus(
        [
            "Buy durable steel now. Price is $100. Visit https://example.com/a today.",
            "Contact us for a quote.",
        ]
    )
    ok_source_only = validate_variant(
        caption="Buy durable steel now. Contact us for a quote.",
        hashtags=[],
        cta=None,
        link=None,
        corpus=corpus,
    )
    record("provenance_source_only_ok", ok_source_only.ok, str(ok_source_only.extras))

    invented = validate_variant(
        caption="Buy amazing durable steel now.",
        hashtags=[],
        cta=None,
        link=None,
        corpus=corpus,
    )
    record("provenance_invented_word_rejected", not invented.ok, str(invented.extras))

    changed_number = validate_variant(
        caption="Buy durable steel now. Price is $250.",
        hashtags=[],
        cta=None,
        link=None,
        corpus=corpus,
    )
    record("provenance_changed_number_rejected", not changed_number.ok, str(changed_number.extras))

    changed_url = validate_variant(
        caption="Visit https://example.com/b today.",
        hashtags=[],
        cta=None,
        link="https://example.com/b",
        corpus=corpus,
    )
    record("provenance_changed_url_rejected", not changed_url.ok, str(changed_url.extras))

    formatting_only = validate_variant(
        caption="buy   durable    steel now!!!   Contact us for a quote...",
        hashtags=[],
        cta=None,
        link=None,
        corpus=corpus,
    )
    record("provenance_formatting_only_ok", formatting_only.ok, str(formatting_only.extras))

    # ---------------------------------- 6. platform strategies no invention --
    strat_source = make_source(
        "Discover durable steel components for export buyers worldwide.\n\n"
        "We manufacture to spec and ship globally. Contact us today for a quote.",
        hashtags=["export", "steel", "b2b"],
        links=["https://example.com/catalog"],
    )
    corpus_texts = [strat_source.locale_sources["en"].text]
    corpus_texts.extend(ht.render_hashtag(t) for t in strat_source.hashtags)
    corpus_texts.extend(strat_source.links)
    strat_corpus = build_corpus(corpus_texts)
    for platform in ("telegram", "facebook", "instagram", "tiktok", "linkedin"):
        for profile in ("short", "standard", "extended"):
            build = ContentOptimizerService._build_variant(
                strat_source, platform, "en", profile, {},
            )
            proof = validate_variant(
                caption=build.caption,
                hashtags=build.hashtags,
                cta=build.cta,
                link=build.link,
                corpus=strat_corpus,
            )
            record(
                f"strategy_no_invention_{platform}_{profile}",
                build.provenance_ok and proof.ok,
                str(proof.extras),
            )
    # A generated variant must have a non-empty caption with lexical content.
    tg_build = ContentOptimizerService._build_variant(
        strat_source, "telegram", "en", "standard", {},
    )
    record(
        "strategy_generated_caption_non_empty",
        tg_build.status == "generated" and any(c.isalnum() for c in tg_build.caption),
        tg_build.status,
    )

    # --------------------------------------------- 7. CTA selection only -----
    cta_source_text = "We ship worldwide. Contact us today for a quote and details."
    picked = select_existing_cta(cta_source_text, [], prefer="last")
    record(
        "cta_from_source_only",
        bool(picked) and picked in cta_source_text,
        str(picked),
    )
    record("cta_source_detected", source_has_cta(cta_source_text))

    template_cta = select_existing_cta(
        "No call to action in this body at all here.",
        ["Order now via our catalog."],
    )
    record(
        "cta_from_template_when_no_source",
        template_cta == "Order now via our catalog.",
        str(template_cta),
    )

    none_cta = select_existing_cta("Purely descriptive body with nothing actionable.", [])
    record("cta_none_when_absent", none_cta is None, str(none_cta))

    # ----------------------------------------------- 8. hashtag no invention -
    parsed = ht.parse_hashtag_field("#export, #Export #steel #b2b")
    record("hashtag_parse_dedupe_casefold", parsed == ["export", "steel", "b2b"], str(parsed))

    deduped = ht.dedupe_hashtags(["export", "Export", "steel"])
    record("hashtag_dedupe", deduped == ["export", "steel"], str(deduped))

    supported = ht.filter_supported(["good", "bad-ok", "123", "with space"])
    # Only tokens starting with a letter and single-word are kept.
    record("hashtag_filter_supported_no_invention", "good" in supported and "123" not in supported, str(supported))
    record(
        "hashtag_filter_subset_of_input",
        set(supported).issubset({"good", "bad-ok", "123", "with space"}),
        str(supported),
    )

    limited = ht.limit_hashtags(["a", "b", "c", "d"], 2)
    record("hashtag_limit_truncates", limited == ["a", "b"], str(limited))

    # ------------------------------------------- 9. operation catalog keys ---
    ops = list_operations()
    op_keys = {o["key"] for o in ops}
    expected_ops = {
        "normalize_whitespace",
        "normalize_line_breaks",
        "deduplicate_exact_sentences",
        "deduplicate_exact_hashtags",
        "move_hashtags_to_end",
        "limit_hashtag_count",
        "truncate_at_sentence_boundary",
        "truncate_at_paragraph_boundary",
        "select_first_n_sentences",
        "select_existing_cta",
    }
    record(
        "operation_catalog_expected_keys",
        expected_ops.issubset(op_keys),
        str(sorted(expected_ops - op_keys)),
    )
    record(
        "operation_catalog_shape",
        all({"key", "category", "reason_key"} <= set(o.keys()) for o in ops),
    )
    record("operation_catalog_matches_registry", op_keys == set(OPERATIONS.keys()))

    # ---------------------------------------- 10. configuration versions -----
    cfg = ContentOptimizerService.get_configuration()
    record("config_optimizer_version", cfg.get("optimizer_version") == OPTIMIZER_VERSION, str(cfg.get("optimizer_version")))
    record(
        "config_source_fp_version",
        cfg.get("source_fingerprint_version") == SOURCE_FINGERPRINT_VERSION,
    )
    record(
        "config_variant_fp_version",
        cfg.get("variant_fingerprint_version") == VARIANT_FINGERPRINT_VERSION,
    )
    record("config_policy_version_present", bool(cfg.get("policy_catalog_version")))
    record(
        "config_exposes_limits_and_guarantees",
        isinstance(cfg.get("limits"), dict) and bool(cfg.get("guarantees")),
    )
    record(
        "config_supported_locales",
        set(cfg.get("supported_locales") or []) >= {"en", "ru", "uz"},
        str(cfg.get("supported_locales")),
    )

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
