"""Verify git blob pins for the old source-equivalent commit."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .constants import OLD_CRITICAL_FILE_SHA256, OLD_SOURCE_SHA

REPO_ROOT = Path(__file__).resolve().parents[3]


def _git_show_bytes(path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{OLD_SOURCE_SHA}:{path}"],
        cwd=str(REPO_ROOT),
    )


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
    # Confirm commit exists and is ancestor of HEAD when possible.
    tip = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{OLD_SOURCE_SHA}^{{commit}}"],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()
    results["commit_resolves"] = tip == OLD_SOURCE_SHA
    if tip != OLD_SOURCE_SHA:
        results["ok"] = False
    return results
