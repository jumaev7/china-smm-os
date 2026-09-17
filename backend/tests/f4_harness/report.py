"""Machine- and human-readable F4 comparison reports."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compare import Classification, ScenarioOutcome
from .constants import (
    F1_F3_CANDIDATE_SHA,
    F4_INTRODUCTION_SHA,
    NEW_BASELINE_SHA,
    OLD_CRITICAL_FILE_SHA256,
    OLD_IMAGE_EVIDENCE,
    OLD_IMAGE_ID,
    OLD_SOURCE_SHA,
)
from .source_pin import current_candidate_sha


def build_report(
    *,
    outcomes: list[ScenarioOutcome],
    isolation: dict[str, Any],
    schema_results: dict[str, Any],
    source_pin: dict[str, Any],
    suite_totals: dict[str, Any],
    provider_summary: dict[str, Any],
    api_regression: dict[str, Any],
    failure_injection: dict[str, Any],
    registry_neutrality: dict[str, Any],
    known_safety: list[str],
    diff_scope: list[str],
) -> dict[str, Any]:
    by_class: dict[str, list[str]] = {c.value: [] for c in Classification}
    failed = []
    unresolved = []
    passed = []
    for o in outcomes:
        by_class[o.classification.value].append(o.scenario_id)
        if o.verdict == "PASS":
            passed.append(o.scenario_id)
        elif o.verdict == "UNRESOLVED":
            unresolved.append(o.scenario_id)
        else:
            failed.append(o.scenario_id)

    gates = {
        "zero_unexplained_extra_provider_writes": provider_summary.get(
            "unexplained_extra_writes", 0
        )
        == 0,
        "zero_unexpected_registry_mutations": registry_neutrality.get(
            "unexpected_mutations", 0
        )
        == 0,
        "zero_unexpected_execution_activation": registry_neutrality.get(
            "execution_activation", 0
        )
        == 0,
        "zero_cross_tenant_leakage": api_regression.get("cross_tenant_leaks", 0) == 0,
        "zero_unintended_differences": len(by_class[Classification.UNINTENDED.value])
        == 0
        and not failed,
        "zero_material_unresolved": len(unresolved) == 0,
    }
    f4_safety_go = all(gates.values()) and not failed and not unresolved
    candidate_sha = current_candidate_sha()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # Immutable historical F1–F3 reference (not the revision under test).
        "pre_sha": NEW_BASELINE_SHA,
        "historical_f1_f3_baseline_sha": F1_F3_CANDIDATE_SHA,
        "f4_introduction_sha": F4_INTRODUCTION_SHA,
        # Explicit revision whose behavior this report captures.
        "candidate_sha": candidate_sha,
        "artifact_provenance": {
            "old_source_sha": OLD_SOURCE_SHA,
            "historical_f1_f3_baseline_sha": F1_F3_CANDIDATE_SHA,
            "f4_introduction_sha": F4_INTRODUCTION_SHA,
            "candidate_sha": candidate_sha,
            "note": (
                "pre_sha / historical_f1_f3_baseline_sha remain the immutable "
                "F1–F3 pin from harness introduction. candidate_sha is HEAD at "
                "report generation (may include I1+). Do not treat pre_sha as "
                "the code under test after F4 landed."
            ),
        },
        "old_image_id": OLD_IMAGE_ID,
        "old_source_sha": OLD_SOURCE_SHA,
        "old_image_evidence": OLD_IMAGE_EVIDENCE,
        "old_critical_file_sha256": OLD_CRITICAL_FILE_SHA256,
        "source_pin": source_pin,
        "isolation": isolation,
        "schema_compatibility": schema_results,
        "scenarios": [o.to_dict() for o in outcomes],
        "classification_index": by_class,
        "intended": by_class[Classification.INTENDED.value],
        "unintended": by_class[Classification.UNINTENDED.value],
        "unresolved": by_class[Classification.UNRESOLVED.value],
        "equivalent": by_class[Classification.EQUIVALENT.value],
        "common_mode_safety": by_class[Classification.COMMON_MODE_SAFETY.value],
        "provider_call_comparison": provider_summary,
        "registry_neutrality": registry_neutrality,
        "api_regression": api_regression,
        "failure_injection": failure_injection,
        "suite_totals": suite_totals,
        "known_common_mode_safety_concerns": known_safety,
        "diff_scope_audit": diff_scope,
        "scenario_verdicts": {
            "passed": passed,
            "failed": failed,
            "unresolved": unresolved,
            "skipped_note": "Skipped/unexecuted scenarios are not counted as passing",
        },
        "gates": gates,
        "verdicts": {
            "f4_harness_implementation": "GO" if outcomes else "NO-GO",
            "f4_behavioral_equivalence": (
                "GO"
                if f4_safety_go
                and not by_class[Classification.UNINTENDED.value]
                else "NO-GO"
            ),
            "f4_safety_acceptance": "GO" if f4_safety_go else "NO-GO",
            "production_source_landing": "NO-GO",
            "production_image_build": "NO-GO",
            "runtime_deployment": "NO-GO",
            "shadow_enablement": "NO-GO",
            "registry_authority": "NO-GO",
            "provider_io_changes": "NO-GO",
            "claim_execution_activation": "NO-GO",
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# F4 — Old vs New Backend Regression Report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Identities",
        "",
        f"- Candidate under test (HEAD): `{report.get('candidate_sha', report['pre_sha'])}`",
        f"- Historical F1–F3 baseline (immutable): `{report.get('historical_f1_f3_baseline_sha', report['pre_sha'])}`",
        f"- F4 introduction: `{report.get('f4_introduction_sha', 'n/a')}`",
        f"- Old image: `{report['old_image_id']}`",
        f"- Old source-equivalent: `{report['old_source_sha']}`",
        "",
        "> `pre_sha` in JSON remains the historical F1–F3 pin for compatibility; "
        "`candidate_sha` is the actual revision whose behavior is recorded.",
        "",
        "## Isolation",
        "",
        "```json",
        json.dumps(report["isolation"], indent=2),
        "```",
        "",
        "## Schema compatibility",
        "",
        "```json",
        json.dumps(report["schema_compatibility"], indent=2),
        "```",
        "",
        "## Scenario matrix",
        "",
        "| Scenario | Class | Verdict | Difference |",
        "|---|---|---|---|",
    ]
    for s in report["scenarios"]:
        diff = (s.get("difference") or "").replace("|", "/")[:120]
        lines.append(
            f"| `{s['scenario_id']}` | {s['classification']} | {s['verdict']} | {diff} |"
        )
    lines.extend(
        [
            "",
            "## Gates",
            "",
            "```json",
            json.dumps(report["gates"], indent=2),
            "```",
            "",
            "## Verdicts",
            "",
            "```json",
            json.dumps(report["verdicts"], indent=2),
            "```",
            "",
            "## Known common-mode safety concerns",
            "",
        ]
    )
    for item in report["known_common_mode_safety_concerns"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict[str, Any], directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "f4_comparison_report.json"
    md_path = directory / "f4_comparison_report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
