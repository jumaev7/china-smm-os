"""Verification for measurement event → MIP signal mapping.

Run from backend/:  python scripts/verify_measurement_signals.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def main() -> int:
    from app.core.events.types import PlatformEvent
    from app.services.intelligence.collectors.measurement import MeasurementCollector
    from app.services.intelligence.types import PLATFORM_EVENT_TO_SOURCE, SIGNAL_TYPES

    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    record(
        "signal_types_registered",
        "measurement.snapshot_ingested" in SIGNAL_TYPES
        and "measurement.anomaly_detected" in SIGNAL_TYPES
        and "publication.registered" in SIGNAL_TYPES
        and "attribution.recorded" in SIGNAL_TYPES,
    )
    record(
        "event_source_map",
        PLATFORM_EVENT_TO_SOURCE.get("publication.metrics_ingested") == "content"
        and PLATFORM_EVENT_TO_SOURCE.get("publication.registered") == "content",
    )

    collector = MeasurementCollector()
    tenant_id = uuid4()
    now = datetime.now(timezone.utc)
    pub_id = str(uuid4())

    cases = [
        (
            "publication.registered",
            "publication.registered",
            {
                "external_publication_id": pub_id,
                "platform": "mock",
                "content_id": str(uuid4()),
                "is_mock": True,
                "has_assignment": False,
                "caption": "LEAK",
                "access_token": "LEAK",
            },
        ),
        (
            "publication.metrics_ingested",
            "measurement.snapshot_ingested",
            {
                "external_publication_id": pub_id,
                "snapshot_id": str(uuid4()),
                "ingestion_run_id": str(uuid4()),
                "platform": "mock",
                "metric_count": 12,
                "raw_payload": {"secret": "no"},
            },
        ),
        (
            "publication.metrics_failed",
            "measurement.snapshot_failed",
            {"ingestion_run_id": str(uuid4()), "platform": "mock", "failure_code": "adapter_error"},
        ),
        (
            "publication.metrics_stale",
            "measurement.metrics_stale",
            {"external_publication_id": pub_id, "freshness_status": "stale"},
        ),
        (
            "publication.measurement_anomaly_detected",
            "measurement.anomaly_detected",
            {
                "external_publication_id": pub_id,
                "snapshot_id": str(uuid4()),
                "anomaly_count": 2,
                "anomaly_keys": ["extreme_jump", "negative_metric"],
            },
        ),
        (
            "campaign.kpi_progress_updated",
            "campaign.kpi_progress_updated",
            {"campaign_id": str(uuid4()), "kpi_count": 3, "statuses": ["no_data", "not_measurable"]},
        ),
        (
            "attribution.recorded",
            "attribution.recorded",
            {
                "attribution_id": str(uuid4()),
                "external_publication_id": pub_id,
                "attribution_method": "unattributed",
                "confidence": "0.000",
            },
        ),
    ]

    for event_type, expected_signal, payload in cases:
        event = PlatformEvent(
            event_type=event_type,
            occurred_at=now,
            tenant_id=tenant_id,
            resource_type="external_publication",
            resource_id=pub_id,
            payload=payload,
            title=event_type,
        )
        signals = collector.collect(event)
        types = {s.signal_type for s in signals}
        record(f"signal_{event_type}", expected_signal in types, str(sorted(types)))

        safe = True
        for s in signals:
            meta_payload = (s.metadata or {}).get("payload") or {}
            blob = str(meta_payload).lower()
            if any(bad in blob for bad in ("leak", "token", "caption", "jwt", "secret", "raw_payload")):
                safe = False
            if "caption" in meta_payload or "access_token" in meta_payload or "raw_payload" in meta_payload:
                safe = False
        record(f"safe_metadata_{event_type}", safe)

    # Unsupported event yields no signals
    idle = PlatformEvent(
        event_type="content.created",
        occurred_at=now,
        tenant_id=tenant_id,
        resource_type="content",
        resource_id=str(uuid4()),
        payload={},
        title="noop",
    )
    record("unrelated_event_no_signals", collector.collect(idle) == [])

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
