"""Pinned identities for the old production backend vs F1–F3 candidate."""

from __future__ import annotations

# Production image observed in R3.1/R3.2 preflight (not present on every host).
OLD_IMAGE_ID = (
    "sha256:34d2977e2d1de13fa8bf0ad2e79692e0f18c537609c6e66796dadbefafd8bff4"
)

# Source tip established by multi-file in-image hash match (R3.1 report).
# Git ancestry alone is NOT the identity proof; blob SHA256 pins below are.
OLD_SOURCE_SHA = "338d3f966fa7c5fd2795201e555512f1eebcadc9"

# F4 baseline (F1+F2+F3 landed).
NEW_BASELINE_SHA = "d1ccee82e3106ea469ac086ed99bd5f840b75fe0"

# sha256 of `git show ${OLD_SOURCE_SHA}:<path>` for critical publish surface.
# Recomputed by tests; mismatch → STOP (source pin broken).
OLD_CRITICAL_FILE_SHA256: dict[str, str] = {
    "backend/app/services/publish_service.py": (
        "c64ca9ea84bf973c2152eb6530b12b47e698875cbe6679b78dad4598dc4c1079"
    ),
    "backend/app/services/publish_resilience.py": (
        "102e55176ba70d0f080cfd1c039a969d28c4a85bb1c608de683263e20111263e"
    ),
    "backend/app/api/v1/publishing.py": (
        "d6183f4e28ad9f540c0988b720277f48c90ff7830c6fea479f3518e2b9f62f30"
    ),
    "backend/app/core/config.py": (
        "52050ba25103813d50fa81a809c1e5a28f19f0ae353450e5b67fc93ca7386527"
    ),
    "backend/app/main.py": (
        "74602c7b7ecd1e47f1406750922acc507cf3da2e358951fa0e894367c84599a3"
    ),
}

# R3.1 authenticated evidence (host report) — image not required locally when
# these blob pins verify and prior multi-file match is accepted.
OLD_IMAGE_EVIDENCE = {
    "image_id": OLD_IMAGE_ID,
    "source_equivalent_commit": OLD_SOURCE_SHA,
    "evidence": (
        "R3.1 production preflight: docker image inspect matched "
        f"{OLD_IMAGE_ID}; in-container sha256 of critical /app files matched "
        f"git blobs at {OLD_SOURCE_SHA} (multi-file hash pin). "
        "R1–R3 modules absent from running image."
    ),
    "local_image_required": False,
    "note": (
        "Harness compares behavior of source-equivalent old algorithms "
        "extracted from OLD_SOURCE_SHA against current HEAD. Full container "
        "re-execution is optional when the image is available."
    ),
}

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/"
    "f4_old_vs_new_regression"
)

# Production / staging DB names that must never appear in harness URLs.
FORBIDDEN_DB_NAME_SUBSTRINGS = (
    "china_smm_os",
    "production",
    "prod",
    "staging",
)

DISABLED_FEATURE_FLAGS = (
    "PUBLISH_WRITE_COORDINATION_SHADOW",
    "PUBLISH_WRITE_COORDINATION_ENABLED",
    "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED",
    "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED",
    "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED",
    "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED",
    "PUBLISH_RETRY_COMMANDS_ENABLED",
    "PUBLISH_RETRY_COMMAND_WORKER_ENABLED",
    "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED",
    "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED",
    "SCHEDULED_PUBLISH_ENABLED",
)
