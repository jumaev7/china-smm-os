"""Media-readiness checks using verified MediaFile metadata only (no OCR/vision)."""
from __future__ import annotations

from app.services.publishing_intelligence.checks._helpers import check
from app.services.publishing_intelligence.platform_policies import get_policy
from app.services.publishing_intelligence.schemas import CheckResult, ReviewContext

# Soft internal size guidance (bytes) — not claimed as hard unless adapter enforces.
_MAX_FILE_SIZE = {
    "image": 25 * 1024 * 1024,
    "video": 100 * 1024 * 1024,
}


def run_media_checks(ctx: ReviewContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    media_required = any(
        (get_policy(p) or {}).get("media_required") for p in ctx.platforms
    )

    if not ctx.media:
        results.append(
            check(
                "media_present_when_required",
                "media_readiness",
                "failed" if media_required else "not_applicable",
                score=0 if media_required else None,
                weight=3 if media_required else 1,
                severity="error" if media_required else "info",
                evidence={"media_required": media_required, "platforms": sorted(ctx.platforms)},
                recommendation_key="add_required_platform_media" if media_required else None,
            )
        )
        for key in (
            "media_processing_complete",
            "supported_media_type",
            "file_size_within_limit",
            "aspect_ratio_recommended",
            "resolution_minimum",
            "video_duration_fit",
            "thumbnail_ready",
            "missing_alt_text",
        ):
            status = "not_applicable"
            if key == "aspect_ratio_recommended" or key == "resolution_minimum" or key == "video_duration_fit":
                status = "not_applicable"
            results.append(
                check(
                    key,
                    "media_readiness",
                    status,
                    evidence={"reason": "no_media"},
                )
            )
        return results

    m = ctx.media
    file_type = (m.get("file_type") or "").lower()
    mime = (m.get("mime_type") or "").lower()
    size = int(m.get("file_size") or 0)
    upload_complete = bool(m.get("upload_complete"))
    thumbnail_present = bool(m.get("thumbnail_present"))

    results.append(
        check(
            "media_present_when_required",
            "media_readiness",
            "passed",
            score=100,
            weight=3,
            evidence={"media_id": str(m.get("id") or ""), "file_type": file_type},
        )
    )

    results.append(
        check(
            "media_processing_complete",
            "media_readiness",
            "passed" if upload_complete else "failed",
            score=100 if upload_complete else 0,
            weight=3,
            severity="error" if not upload_complete else "info",
            evidence={"upload_complete": upload_complete, "has_storage_path": bool(m.get("has_storage_path"))},
            recommendation_key="complete_media_upload" if not upload_complete else None,
        )
    )

    supported = True
    for platform in ctx.platforms:
        policy = get_policy(platform)
        if not policy:
            continue
        allowed = policy.get("supported_media_types") or []
        if file_type and file_type not in allowed:
            supported = False
            break
    results.append(
        check(
            "supported_media_type",
            "media_readiness",
            "passed" if supported else "failed",
            score=100 if supported else 10,
            weight=3,
            severity="error" if not supported else "info",
            evidence={"file_type": file_type, "mime_type": mime, "platforms": sorted(ctx.platforms)},
            recommendation_key="use_supported_media_type" if not supported else None,
        )
    )

    limit = _MAX_FILE_SIZE.get(file_type, _MAX_FILE_SIZE["image"])
    size_ok = size <= 0 or size <= limit
    results.append(
        check(
            "file_size_within_limit",
            "media_readiness",
            "passed" if size_ok else "warning",
            score=100 if size_ok else 45,
            weight=2,
            severity="warning" if not size_ok else "info",
            evidence={
                "file_size": size,
                "recommended_max": limit,
                "note": "Internal size guidance — verify adapter limits before publish",
            },
            recommendation_key="reduce_media_file_size" if not size_ok else None,
        )
    )

    # Aspect ratio / resolution / duration require metadata not stored on MediaFile
    for key, label in (
        ("aspect_ratio_recommended", "aspect_ratio"),
        ("resolution_minimum", "width_height"),
        ("video_duration_fit", "duration"),
    ):
        if key == "video_duration_fit" and file_type != "video":
            results.append(
                check(key, "media_readiness", "not_applicable", evidence={"reason": "not_video"})
            )
        else:
            results.append(
                check(
                    key,
                    "media_readiness",
                    "warning",
                    score=70,
                    weight=1,
                    severity="warning",
                    evidence={
                        "unknown_metadata": label,
                        "note": "Metadata unavailable in Phase 1 — not fabricated",
                    },
                    recommendation_key="verify_media_metadata",
                    recommendation_params={"field": label},
                )
            )

    # Thumbnail recommended for video
    if file_type == "video":
        results.append(
            check(
                "thumbnail_ready",
                "media_readiness",
                "passed" if thumbnail_present else "warning",
                score=100 if thumbnail_present else 60,
                weight=1,
                evidence={"thumbnail_present": thumbnail_present},
                recommendation_key="add_video_thumbnail" if not thumbnail_present else None,
            )
        )
    else:
        results.append(
            check("thumbnail_ready", "media_readiness", "not_applicable", evidence={"reason": "not_video"})
        )

    # Alt text not modeled — unknown
    results.append(
        check(
            "missing_alt_text",
            "media_readiness",
            "not_applicable",
            evidence={"reason": "alt_text_not_modeled"},
        )
    )
    return results
