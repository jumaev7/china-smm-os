"""Unit tests for Publishing Intelligence — fingerprint, scoring, checks (no DB)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    from app.services.publishing_intelligence.checks import run_all_checks
    from app.services.publishing_intelligence.checks.caption import run_caption_checks
    from app.services.publishing_intelligence.checks.cta import run_cta_checks
    from app.services.publishing_intelligence.checks.hashtag import run_hashtag_checks
    from app.services.publishing_intelligence.checks.media import run_media_checks
    from app.services.publishing_intelligence.content_fingerprint import (
        compute_content_fingerprint,
    )
    from app.services.publishing_intelligence.cta_catalog import detect_ctas
    from app.services.publishing_intelligence.platform_policies import (
        CATEGORY_WEIGHTS,
        SUPPORTED_PLATFORMS,
        list_policies,
    )
    from app.services.publishing_intelligence.schemas import ReviewContext
    from app.services.publishing_intelligence.score_engine import (
        compute_category_scores,
        compute_overall_score,
    )

    def ctx(**overrides) -> ReviewContext:
        base = dict(
            content_id=uuid4(),
            tenant_id=uuid4(),
            status="draft",
            platforms=["instagram", "telegram"],
            captions={"en": "Discover our new export catalog. Contact us today for a quote."},
            primary_language="en",
            hashtags_raw="#export #china #b2b",
            hashtags=["export", "china", "b2b"],
            scheduled_for=None,
            approved_at=None,
            client_review_status=None,
            media={
                "id": uuid4(),
                "file_type": "image",
                "mime_type": "image/jpeg",
                "file_size": 120000,
                "thumbnail_present": True,
                "upload_complete": True,
                "has_storage_path": True,
            },
            content_type="image",
            keywords=[],
            cta_hint=None,
            link=None,
        )
        base.update(overrides)
        return ReviewContext(**base)

    # --- Fingerprint ---
    a = ctx()
    b = ctx(
        content_id=a.content_id,
        tenant_id=uuid4(),  # tenant-independent
        captions=dict(a.captions),
        hashtags=list(a.hashtags),
        platforms=list(reversed(a.platforms)),  # order stable via sort
        media=dict(a.media) if a.media else None,
    )
    # Same media id ordering
    if b.media and a.media:
        b.media["id"] = a.media["id"]
    fp_a = compute_content_fingerprint(a)
    fp_b = compute_content_fingerprint(b)
    record("fingerprint_identical_content", fp_a == fp_b, f"{fp_a[:16]} vs {fp_b[:16]}")

    edited = ctx(
        content_id=a.content_id,
        tenant_id=a.tenant_id,
        captions={"en": a.captions["en"] + " EDIT"},
        hashtags=list(a.hashtags),
        platforms=list(a.platforms),
        media=dict(a.media) if a.media else None,
    )
    if edited.media and a.media:
        edited.media["id"] = a.media["id"]
    record(
        "fingerprint_relevant_edit_changes",
        compute_content_fingerprint(edited) != fp_a,
    )

    # Irrelevant: different content_id alone shouldn't affect payload (not in fingerprint)
    # status change is relevant; internal equivalent - changing nothing else
    media_order_a = ctx(platforms=["telegram", "instagram", "facebook"])
    media_order_b = ctx(platforms=["facebook", "instagram", "telegram"])
    # Align other fields
    media_order_b.captions = dict(media_order_a.captions)
    media_order_b.hashtags = list(media_order_a.hashtags)
    if media_order_a.media and media_order_b.media:
        media_order_b.media["id"] = media_order_a.media["id"]
    record(
        "fingerprint_platform_ordering_stable",
        compute_content_fingerprint(media_order_a) == compute_content_fingerprint(media_order_b),
    )

    # --- Scoring determinism ---
    c = ctx()
    checks1 = run_all_checks(c)
    checks2 = run_all_checks(c)
    cats1 = compute_category_scores(checks1)
    cats2 = compute_category_scores(checks2)
    o1, _ = compute_overall_score(cats1)
    o2, _ = compute_overall_score(cats2)
    record("score_determinism", o1 == o2, f"{o1} vs {o2}")
    record("score_range", 0 <= o1 <= 100, str(o1))

    empty = ctx(captions={}, hashtags=[], hashtags_raw="", media=None, platforms=[])
    empty_checks = run_all_checks(empty)
    empty_cats = compute_category_scores(empty_checks)
    # N/A should not unfairly crash
    empty_score, meta = compute_overall_score(empty_cats)
    record("score_zero_content_edge", 0 <= empty_score <= 100, str(empty_score))
    record("na_denominator_defined", "denominator_weight" in meta or "reason" in meta, str(meta)[:120])

    # Critical compliance failure caps
    secret_ctx = ctx(captions={"en": "Here is our api_key SECRETTOKEN123 and password leak"})
    secret_checks = run_all_checks(secret_ctx)
    secret_cats = compute_category_scores(secret_checks)
    secret_score, _ = compute_overall_score(secret_cats)
    record("critical_failure_score_cap", secret_score <= 40, str(secret_score))

    # Platform variation
    ig = ctx(platforms=["instagram"], media=None)
    tg = ctx(platforms=["telegram"], media=None)
    ig_score, _ = compute_overall_score(compute_category_scores(run_all_checks(ig)))
    tg_score, _ = compute_overall_score(compute_category_scores(run_all_checks(tg)))
    record("platform_specific_score_variation", ig_score != tg_score, f"ig={ig_score} tg={tg_score}")

    # --- Caption ---
    missing = run_caption_checks(ctx(captions={}))
    record("caption_missing", any(c.check_key == "caption_present" and c.status == "failed" for c in missing))
    short = run_caption_checks(ctx(captions={"en": "Hi"}))
    record("caption_too_short", any(c.check_key == "caption_minimum_length" and c.status == "warning" for c in short))
    upper = run_caption_checks(ctx(captions={"en": "THIS IS ALL CAPS SHOUTING FOR ATTENTION NOW!!!"}))
    record("caption_excessive_uppercase", any(c.check_key == "excessive_uppercase" and c.status == "warning" for c in upper))

    # --- CTA ---
    for lang, phrase in (
        ("en", "Contact us today for your free quote"),
        ("ru", "Свяжитесь с нами для заказа"),
        ("uz", "Biz bilan bog'laning hozir"),
        ("zh", "联系我们获取报价"),
    ):
        hits = detect_ctas(phrase)
        record(f"cta_detect_{lang}", len(hits) >= 1, str([h.family for h in hits]))

    no_cta = run_cta_checks(ctx(captions={"en": "Our factory produces steel pipes for export markets worldwide."}))
    record("cta_missing_warning", any(c.check_key == "cta_present" and c.status == "warning" for c in no_cta))

    info = run_cta_checks(ctx(captions={"en": "Announcement: office closed tomorrow for maintenance."}))
    record("cta_not_applicable_informational", any(c.status == "not_applicable" for c in info))

    # --- Hashtags ---
    dups = run_hashtag_checks(ctx(hashtags=["export", "export", "china"], hashtags_raw="#export #export #china"))
    record("hashtag_duplicates", any(c.check_key == "duplicate_hashtags" and c.status == "warning" for c in dups))
    invalid = run_hashtag_checks(ctx(hashtags=["good", "bad-tag!"], hashtags_raw="#good #bad-tag!"))
    record("hashtag_invalid_format", any(c.check_key == "invalid_format" and c.status == "failed" for c in invalid))

    # --- Media ---
    no_media_ig = run_media_checks(ctx(platforms=["instagram"], media=None))
    record(
        "media_missing_when_required",
        any(c.check_key == "media_present_when_required" and c.status == "failed" for c in no_media_ig),
    )
    incomplete = run_media_checks(
        ctx(
            media={
                "id": uuid4(),
                "file_type": "image",
                "mime_type": "image/jpeg",
                "file_size": 10,
                "thumbnail_present": False,
                "upload_complete": False,
                "has_storage_path": False,
            }
        )
    )
    record(
        "media_incomplete_processing",
        any(c.check_key == "media_processing_complete" and c.status == "failed" for c in incomplete),
    )
    unknown_meta = [c for c in incomplete if c.check_key == "aspect_ratio_recommended"]
    record(
        "media_unknown_metadata_warning",
        bool(unknown_meta) and unknown_meta[0].evidence.get("unknown_metadata") == "aspect_ratio",
    )

    # --- Policies ---
    policies = list_policies()
    record("policies_supported_platforms", set(SUPPORTED_PLATFORMS).issubset(set(policies["platforms"].keys())))
    record("category_weights_sum_100", sum(CATEGORY_WEIGHTS.values()) == 100, str(sum(CATEGORY_WEIGHTS.values())))

    # --- Scheduling future ---
    past = ctx(
        status="scheduled",
        scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    past_checks = run_all_checks(past)
    record(
        "scheduled_time_in_past_fails",
        any(c.check_key == "scheduled_time_in_future" and c.status == "failed" for c in past_checks),
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
