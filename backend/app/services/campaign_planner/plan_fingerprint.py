"""Deterministic fingerprints for campaign plans and slots.

Fingerprints are SHA-256 hex digests of canonical JSON with stable key ordering.
They are tenant-independent (never include tenant_id, ids, or secrets) so that the
same planning inputs always produce the same fingerprint — this is the basis for
determinism verification.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def compute_plan_fingerprint(spec: dict[str, Any]) -> str:
    """Fingerprint the normalized planning spec (no ids, no tenant, no secrets)."""
    payload = {
        "planner_version": spec.get("planner_version"),
        "policy_version": spec.get("policy_version"),
        "start_date": spec.get("start_date"),
        "end_date": spec.get("end_date"),
        "timezone": spec.get("timezone"),
        "primary_locale": spec.get("primary_locale"),
        "locales": sorted(spec.get("locales") or []),
        "platforms": sorted(spec.get("platforms") or []),
        "blackout_dates": sorted(spec.get("blackout_dates") or []),
        "cadence": spec.get("cadence") or {},
        # Pillars/phases by stable key (slug/name), not by uuid.
        "pillars": sorted(spec.get("pillars") or [], key=lambda p: str(p.get("key"))),
        "phases": sorted(spec.get("phases") or [], key=lambda p: (str(p.get("start")), str(p.get("key")))),
    }
    return sha256_hex(payload)


def compute_slot_fingerprint(slot: dict[str, Any]) -> str:
    """Fingerprint a single slot's stable identity within a plan."""
    payload = {
        "platform": slot.get("platform"),
        "locale": slot.get("locale"),
        "date": slot.get("date"),
        "time": slot.get("time"),
        "pillar_key": slot.get("pillar_key"),
        "phase_key": slot.get("phase_key"),
        "index": slot.get("index"),
    }
    return sha256_hex(payload)


def compute_plan_output_fingerprint(slots: list[dict[str, Any]]) -> str:
    """Fingerprint the full ordered slot list — proves deterministic output."""
    ordered = [
        {
            "platform": s.get("platform"),
            "locale": s.get("locale"),
            "date": s.get("date"),
            "time": s.get("time"),
            "pillar_key": s.get("pillar_key"),
            "phase_key": s.get("phase_key"),
            "index": s.get("index"),
        }
        for s in slots
    ]
    return sha256_hex(ordered)
