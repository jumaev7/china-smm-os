"""Verify git blob pins and historical provenance for the F4 harness."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .constants import (
    F1_F3_CANDIDATE_SHA,
    F4_INTRODUCTION_SHA,
    OLD_CRITICAL_FILE_SHA256,
    OLD_SOURCE_SHA,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()


def _git_show_bytes(path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{OLD_SOURCE_SHA}:{path}"],
        cwd=str(REPO_ROOT),
    )


def _commit_exists(sha: str) -> bool:
    try:
        tip = _git_output("rev-parse", "--verify", f"{sha}^{{commit}}")
        return tip == sha
    except subprocess.CalledProcessError:
        return False


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    try:
        subprocess.check_call(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def current_candidate_sha() -> str:
    """Explicitly record the revision under test (current HEAD)."""
    return _git_output("rev-parse", "HEAD")


def verify_old_source_pins() -> dict[str, Any]:
    results: dict[str, Any] = {
        "old_source_sha": OLD_SOURCE_SHA,
        "files": {},
        "ok": True,
    }
    for path, expected in OLD_CRITICAL_FILE_SHA256.items():
        data = _git_show_bytes(path)
        digest = hashlib.sha256(data).hexdigest()
        match = digest == expected
        results["files"][path] = {
            "expected": expected,
            "actual": digest,
            "match": match,
            "bytes": len(data),
        }
        if not match:
            results["ok"] = False
    # Confirm commit exists (blob identity remains historical — not HEAD).
    tip = _git_output("rev-parse", "--verify", f"{OLD_SOURCE_SHA}^{{commit}}")
    results["commit_resolves"] = tip == OLD_SOURCE_SHA
    if tip != OLD_SOURCE_SHA:
        results["ok"] = False
    return results


def verify_historical_provenance() -> dict[str, Any]:
    """Check immutable historical pins + ancestry relative to current HEAD.

    Does NOT require HEAD == F1–F3 candidate. Records the candidate under test
    explicitly and proves required historical commits are ancestors of HEAD
    (same line of history — rejects unrelated histories).
    """
    candidate = current_candidate_sha()
    pins = {
        "old_source_sha": OLD_SOURCE_SHA,
        "f1_f3_candidate_sha": F1_F3_CANDIDATE_SHA,
        "f4_introduction_sha": F4_INTRODUCTION_SHA,
        "candidate_sha": candidate,
    }
    exists = {
        "old_source": _commit_exists(OLD_SOURCE_SHA),
        "f1_f3_candidate": _commit_exists(F1_F3_CANDIDATE_SHA),
        "f4_introduction": _commit_exists(F4_INTRODUCTION_SHA),
        "candidate": _commit_exists(candidate),
    }
    ancestors = {
        "old_source_is_ancestor_of_head": _is_ancestor(OLD_SOURCE_SHA, candidate),
        "f1_f3_candidate_is_ancestor_of_head": _is_ancestor(
            F1_F3_CANDIDATE_SHA, candidate
        ),
        "f4_introduction_is_ancestor_of_head": _is_ancestor(
            F4_INTRODUCTION_SHA, candidate
        ),
        "f4_introduction_is_descendant_of_f1_f3": _is_ancestor(
            F1_F3_CANDIDATE_SHA, F4_INTRODUCTION_SHA
        ),
    }
    # F4 intro must be present on the line of history (not merely resolvable).
    f4_present = (
        exists["f4_introduction"] and ancestors["f4_introduction_is_ancestor_of_head"]
    )
    ok = (
        all(exists.values())
        and all(ancestors.values())
        and f4_present
        # Candidate may equal F1–F3 (historical F4 run) or any descendant —
        # never require equality with the historical baseline.
        and candidate != ""
    )
    return {
        **pins,
        "commits_exist": exists,
        "ancestry": ancestors,
        "f4_introduction_present": f4_present,
        "head_equals_f1_f3_baseline": candidate == F1_F3_CANDIDATE_SHA,
        "note": (
            "Historical F1–F3 baseline is an immutable reference pin. "
            "Current candidate is HEAD and must be a descendant of that "
            "baseline (and of F4 introduction); equality is not required."
        ),
        "ok": ok,
    }
