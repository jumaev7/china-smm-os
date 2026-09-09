"""Append-only durable fake-invocation sink (Phase 3C.1C-D2-B2a).

Observation evidence ONLY — proves fake provider invocation count across
process restart. NEVER consulted to decide:

- whether provider may be called
- whether barrier may be crossed
- whether command may be retried

Correctness authority remains PostgreSQL command/barrier state.

No secrets. No payloads. No tokens. Staging/test paths only.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

EventType = Literal["fake_invoke"]


@dataclass(frozen=True, slots=True)
class FakeInvocationRecord:
    """Scrubbed durable fake invocation evidence."""

    command_id: str
    attempt_id: str
    fake_mode: str
    timestamp: float
    invocation_ordinal: int
    event_type: EventType = "fake_invoke"

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


class FakeInvocationSinkError(RuntimeError):
    """Durable sink write/read failure."""


class DurableFakeInvocationSink:
    """Append-only local file sink with flush + fsync.

    Not a replay authority. Duplicate records (if a bug re-invokes) are
    retained so tests can expose them — no sink-level dedupe that would
    permit provider replay semantics.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        if self.path.is_dir():
            raise FakeInvocationSinkError(
                f"sink path must be a file, got directory: {self.path}",
            )
        # Refuse production-looking default roots.
        resolved = str(self.path.resolve())
        lowered = resolved.lower().replace("\\", "/")
        if "/production/" in lowered or lowered.endswith("/.env.production"):
            raise FakeInvocationSinkError(
                "refusing production-looking sink path",
            )
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        *,
        command_id: UUID | str,
        attempt_id: UUID | str,
        fake_mode: str,
        invocation_ordinal: int,
        event_type: EventType = "fake_invoke",
        timestamp: float | None = None,
    ) -> FakeInvocationRecord:
        record = FakeInvocationRecord(
            command_id=str(command_id),
            attempt_id=str(attempt_id),
            fake_mode=str(fake_mode),
            timestamp=float(time.time() if timestamp is None else timestamp),
            invocation_ordinal=int(invocation_ordinal),
            event_type=event_type,
        )
        line = record.to_json_line() + "\n"
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError as exc:
                raise FakeInvocationSinkError(
                    f"failed to append fake invocation sink: {exc}",
                ) from exc
        return record

    def read_all(self) -> list[FakeInvocationRecord]:
        if not self.path.exists():
            return []
        records: list[FakeInvocationRecord] = []
        with self._lock:
            text = self.path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            raw: dict[str, Any] = json.loads(line)
            records.append(
                FakeInvocationRecord(
                    command_id=str(raw["command_id"]),
                    attempt_id=str(raw["attempt_id"]),
                    fake_mode=str(raw["fake_mode"]),
                    timestamp=float(raw["timestamp"]),
                    invocation_ordinal=int(raw["invocation_ordinal"]),
                    event_type=raw.get("event_type", "fake_invoke"),  # type: ignore[arg-type]
                ),
            )
        return records

    def count_for_command(self, command_id: UUID | str) -> int:
        target = str(command_id)
        return sum(1 for r in self.read_all() if r.command_id == target)

    def total_count(self) -> int:
        return len(self.read_all())
