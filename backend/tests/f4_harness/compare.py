"""Difference classification for F4 scenarios."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .capture import ScenarioCapture


class Classification(str, Enum):
    INTENDED = "INTENDED"
    UNINTENDED = "UNINTENDED"
    UNRESOLVED = "UNRESOLVED"
    EQUIVALENT = "EQUIVALENT"
    COMMON_MODE_SAFETY = "COMMON_MODE_SAFETY"


@dataclass
class ScenarioOutcome:
    scenario_id: str
    category: str
    old: dict[str, Any]
    new: dict[str, Any]
    difference: str
    classification: Classification
    acceptance_criterion: str
    evidence: list[str] = field(default_factory=list)
    verdict: str = "PASS"  # PASS | FAIL | UNRESOLVED
    safety_concern: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["classification"] = self.classification.value
        return d


# Documented intended deltas (Follow-up A, F1, F2, F3).
INTENDED_ACCEPTANCE: dict[str, str] = {
    "followup_a_durable_only": (
        "Follow-up A: durable-only success (external_post_id set, response NULL) "
        "suppresses duplicate provider writes on the new path; old prior-reader "
        "did not, but old find_live_success/begin_attempt still skipped. "
        "New prior-reader must suppress; provider_calls must be 0."
    ),
    "f1_mock_with_durable": (
        "F1: mock/test success never suppresses real publishing solely because a "
        "durable ID exists. New must allow provider write; old find_live_success "
        "suppressed — INTENDED delta."
    ),
    "f1_conflict": (
        "F1: conflicting durable vs response IDs suppress additional writes, "
        "preserve both IDs, expose identity_conflict, omit authoritative "
        "platform_post_id, and raise a bounded operator alert."
    ),
    "f2_stranded_default_off": (
        "F2: stranded-list API is unavailable by default (HTTP 404). "
        "Old image lacked the route; default-off 404 is the accepted surface."
    ),
    "f3_no_publish_behavior": (
        "F3: immutable deploy helper only — no publishing behavior change when "
        "shadow/WC/retry flags remain disabled."
    ),
}


def _provider_delta(old: ScenarioCapture, new: ScenarioCapture) -> str:
    if old.provider_calls == new.provider_calls:
        return f"provider_calls={old.provider_calls} (same)"
    return (
        f"provider_calls old={old.provider_calls} new={new.provider_calls}"
    )


def classify_scenario(
    *,
    scenario_id: str,
    category: str,
    old: ScenarioCapture,
    new: ScenarioCapture,
    expected_classification: Classification,
    acceptance_criterion: str,
    evidence: list[str] | None = None,
    require_same_provider_calls: bool | None = None,
    allow_api_diff_keys: set[str] | None = None,
    safety_concern: str | None = None,
) -> ScenarioOutcome:
    """Classify old/new captures; FAIL on unexpected provider/registry deltas."""
    evidence = list(evidence or [])
    evidence.append(_provider_delta(old, new))

    old_c = old.comparable()
    new_c = new.comparable()
    # Drop scenario metadata noise from equality check of core fields.
    compare_keys = (
        "provider_calls",
        "suppression_decision",
        "identity_conflict",
        "external_post_id",
        "response_provider_id",
        "registry_row_count",
        "registry_inserts",
        "registry_updates",
        "shadow_reads",
        "shadow_audit_writes",
        "authority_acquisitions",
    )
    diffs: list[str] = []
    for key in compare_keys:
        if old_c.get(key) != new_c.get(key):
            diffs.append(f"{key}: old={old_c.get(key)!r} new={new_c.get(key)!r}")

    api_old = (old_c.get("api_result") or {}) if isinstance(old_c.get("api_result"), dict) else {}
    api_new = (new_c.get("api_result") or {}) if isinstance(new_c.get("api_result"), dict) else {}
    allow = allow_api_diff_keys or set()
    # Treat absent vs explicit False as equivalent for known boolean fields.
    _BOOL_ABSENT_EQ = {"identity_conflict", "mock", "deduplicated", "success", "ambiguous"}
    for key in sorted(set(api_old) | set(api_new)):
        if key in allow:
            continue
        ov = api_old.get(key)
        nv = api_new.get(key)
        if key in _BOOL_ABSENT_EQ and bool(ov) == bool(nv) and ov in (None, False) and nv in (None, False):
            continue
        if ov != nv:
            diffs.append(f"api.{key}: old={ov!r} new={nv!r}")

    difference = "; ".join(diffs) if diffs else "none"

    # Hard safety gates.
    if new.registry_inserts or new.registry_updates or new.authority_acquisitions:
        return ScenarioOutcome(
            scenario_id=scenario_id,
            category=category,
            old=old_c,
            new=new_c,
            difference=difference + "; unexpected registry mutation",
            classification=Classification.UNINTENDED,
            acceptance_criterion=acceptance_criterion,
            evidence=evidence,
            verdict="FAIL",
            safety_concern="unexpected registry mutation under disabled flags",
        )
    if new.shadow_reads or new.shadow_audit_writes:
        return ScenarioOutcome(
            scenario_id=scenario_id,
            category=category,
            old=old_c,
            new=new_c,
            difference=difference + "; unexpected shadow I/O",
            classification=Classification.UNINTENDED,
            acceptance_criterion=acceptance_criterion,
            evidence=evidence,
            verdict="FAIL",
            safety_concern="shadow activity while PUBLISH_WRITE_COORDINATION_SHADOW=false",
        )

    if require_same_provider_calls is True and old.provider_calls != new.provider_calls:
        if expected_classification != Classification.INTENDED:
            return ScenarioOutcome(
                scenario_id=scenario_id,
                category=category,
                old=old_c,
                new=new_c,
                difference=difference,
                classification=Classification.UNINTENDED,
                acceptance_criterion=acceptance_criterion,
                evidence=evidence + ["unexpected provider_call delta"],
                verdict="FAIL",
            )

    if expected_classification == Classification.EQUIVALENT:
        if diffs:
            return ScenarioOutcome(
                scenario_id=scenario_id,
                category=category,
                old=old_c,
                new=new_c,
                difference=difference,
                classification=Classification.UNINTENDED,
                acceptance_criterion=acceptance_criterion,
                evidence=evidence,
                verdict="FAIL",
            )
        return ScenarioOutcome(
            scenario_id=scenario_id,
            category=category,
            old=old_c,
            new=new_c,
            difference="none",
            classification=Classification.EQUIVALENT,
            acceptance_criterion=acceptance_criterion,
            evidence=evidence,
            verdict="PASS",
            safety_concern=safety_concern,
        )

    if expected_classification == Classification.INTENDED:
        # Must show a documented difference (or explicit acceptance that
        # provider outcome matches while reader path differs).
        if not diffs and "provider outcome equivalent" not in acceptance_criterion.lower():
            return ScenarioOutcome(
                scenario_id=scenario_id,
                category=category,
                old=old_c,
                new=new_c,
                difference="none (expected INTENDED delta missing)",
                classification=Classification.UNRESOLVED,
                acceptance_criterion=acceptance_criterion,
                evidence=evidence,
                verdict="UNRESOLVED",
            )
        return ScenarioOutcome(
            scenario_id=scenario_id,
            category=category,
            old=old_c,
            new=new_c,
            difference=difference or "documented path difference with equivalent safety outcome",
            classification=Classification.INTENDED,
            acceptance_criterion=acceptance_criterion,
            evidence=evidence,
            verdict="PASS",
            safety_concern=safety_concern,
        )

    if expected_classification == Classification.COMMON_MODE_SAFETY:
        return ScenarioOutcome(
            scenario_id=scenario_id,
            category=category,
            old=old_c,
            new=new_c,
            difference=difference or "common-mode behavior",
            classification=Classification.COMMON_MODE_SAFETY,
            acceptance_criterion=acceptance_criterion,
            evidence=evidence,
            verdict="PASS",
            safety_concern=safety_concern
            or "Known unsafe behavior present in both versions — not hidden by equivalence",
        )

    if expected_classification == Classification.UNRESOLVED:
        return ScenarioOutcome(
            scenario_id=scenario_id,
            category=category,
            old=old_c,
            new=new_c,
            difference=difference,
            classification=Classification.UNRESOLVED,
            acceptance_criterion=acceptance_criterion,
            evidence=evidence,
            verdict="UNRESOLVED",
            safety_concern=safety_concern,
        )

    # Default: treat unexpected diffs as unintended failures.
    if diffs:
        return ScenarioOutcome(
            scenario_id=scenario_id,
            category=category,
            old=old_c,
            new=new_c,
            difference=difference,
            classification=Classification.UNINTENDED,
            acceptance_criterion=acceptance_criterion,
            evidence=evidence,
            verdict="FAIL",
        )
    return ScenarioOutcome(
        scenario_id=scenario_id,
        category=category,
        old=old_c,
        new=new_c,
        difference="none",
        classification=Classification.EQUIVALENT,
        acceptance_criterion=acceptance_criterion,
        evidence=evidence,
        verdict="PASS",
        safety_concern=safety_concern,
    )
