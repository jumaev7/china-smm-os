"""F4 — old-versus-new publishing regression harness (isolated tests only)."""

from .constants import (
    F1_F3_CANDIDATE_SHA,
    F4_INTRODUCTION_SHA,
    NEW_BASELINE_SHA,
    OLD_CRITICAL_FILE_SHA256,
    OLD_IMAGE_ID,
    OLD_SOURCE_SHA,
)
from .compare import Classification, ScenarioOutcome, classify_scenario
from .report import build_report, write_reports

__all__ = [
    "OLD_IMAGE_ID",
    "OLD_SOURCE_SHA",
    "OLD_CRITICAL_FILE_SHA256",
    "NEW_BASELINE_SHA",
    "F1_F3_CANDIDATE_SHA",
    "F4_INTRODUCTION_SHA",
    "Classification",
    "ScenarioOutcome",
    "classify_scenario",
    "build_report",
    "write_reports",
]
