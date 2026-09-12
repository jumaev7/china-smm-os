"""Staging-only lifecycle coordination (Phase 3C.1C-D2-B2b2-0B+0C).

Provides durable markers + optional hold/release for crash-campaign proofs.

Authorization: constructible ONLY with VerifiedRetryCommandStagingContext
(minted after backend=fake → staging identity → china_smm_os_staging).

Does NOT live in Claim/Preparation/Barrier/Finalization services.
Does NOT authorize provider replay. Does NOT implement Phase E.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal
from uuid import UUID

from app.services.publish_retry_command_executor import ExecutorHooks
from app.services.publish_retry_command_staging_identity import (
    StagingIdentityError,
    VerifiedRetryCommandStagingContext,
    assert_verified_staging_context,
)

logger = logging.getLogger(__name__)

StagingLifecyclePoint = Literal[
    "after_prepare",
    "after_barrier",
    "before_provider",
    "provider_entered",
    "after_provider",
    "before_finalize",
]

ALLOWED_LIFECYCLE_POINTS: Final[frozenset[str]] = frozenset(
    {
        "after_prepare",
        "after_barrier",
        "before_provider",
        "provider_entered",
        "after_provider",
        "before_finalize",
    }
)

# Preferred mounted staging evidence root (compose). Tests may override.
DEFAULT_STAGING_EVIDENCE_ROOT: Final[str] = "/var/lib/retry-command-staging"

_SAFE_CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_POLL_SECONDS: Final[float] = 0.1


class StagingLifecycleCoordinationError(RuntimeError):
    """Fail-closed staging coordination configuration / path error."""

    def __init__(self, reason: str, *, detail: str | None = None) -> None:
        self.reason = reason
        self.detail = detail
        message = reason if detail is None else f"{reason}: {detail}"
        super().__init__(message)


class StagingLifecycleHoldTimeoutError(StagingLifecycleCoordinationError):
    """Hold timed out waiting for an external release file.

    Staging campaign failure only. Does not mutate provider status, does not
    authorize another provider call, and does not trigger Phase E.
    """


def _strip(value: Any) -> str:
    return str(value or "").strip()


def validate_staging_evidence_path(
    path: str | Path,
    *,
    evidence_root: str | Path,
    what: str,
) -> Path:
    """Resolve and refuse unsafe / out-of-root paths."""
    raw = _strip(path)
    if not raw:
        raise StagingLifecycleCoordinationError(
            "empty_coordination_path",
            detail=what,
        )
    root = Path(_strip(evidence_root)).expanduser()
    if not _strip(evidence_root):
        raise StagingLifecycleCoordinationError(
            "empty_evidence_root",
            detail=what,
        )
    try:
        root_resolved = root.resolve()
        candidate = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise StagingLifecycleCoordinationError(
            "path_resolve_failed",
            detail=f"{what}: {exc}",
        ) from exc

    def _is_fs_root(p: Path) -> bool:
        # POSIX `/` and Windows drive roots like `C:\`.
        try:
            return p == p.anchor or str(p).rstrip("\\/") == str(p.anchor).rstrip("\\/")
        except Exception:  # noqa: BLE001
            return False

    if _is_fs_root(candidate) or str(candidate) in {"/", "\\"}:
        raise StagingLifecycleCoordinationError(
            "path_is_filesystem_root",
            detail=what,
        )
    if _is_fs_root(root_resolved) or str(root_resolved) in {"/", "\\"}:
        raise StagingLifecycleCoordinationError(
            "evidence_root_is_filesystem_root",
            detail=str(root_resolved),
        )

    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise StagingLifecycleCoordinationError(
            "path_outside_evidence_root",
            detail=f"{what}: {candidate} not under {root_resolved}",
        ) from exc

    lowered = str(candidate).lower().replace("\\", "/")
    if "/production/" in lowered or lowered.endswith("/.env.production"):
        raise StagingLifecycleCoordinationError(
            "production_looking_path",
            detail=what,
        )
    return candidate


def normalize_campaign_id(raw: str | None) -> str:
    text = _strip(raw) or "default"
    if not _SAFE_CAMPAIGN_ID.match(text):
        raise StagingLifecycleCoordinationError(
            "invalid_campaign_id",
            detail=repr(text),
        )
    return text


def normalize_hold_point(raw: str | None) -> StagingLifecyclePoint | None:
    text = _strip(raw)
    if not text:
        return None
    if text not in ALLOWED_LIFECYCLE_POINTS:
        raise StagingLifecycleCoordinationError(
            "unsupported_hold_point",
            detail=repr(text),
        )
    return text  # type: ignore[return-value]


def durable_write_marker(path: Path, payload: str) -> None:
    """Atomically write marker with flush + fsync (+ parent dir fsync).

    Sequence: write temp → flush → fsync → close → rename → fsync directory.
    External readers may treat the final path as authoritative only after return.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        # Best-effort directory fsync (important on Docker bind mounts).
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except OSError as exc:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise StagingLifecycleCoordinationError(
            "marker_write_failed",
            detail=f"{path}: {exc}",
        ) from exc


def release_filename(point: str) -> str:
    return f"release_{point}"


@dataclass
class StagingLifecycleCoordinator:
    """Durable marker + optional hold/release for one staging worker process.

    Fake outcome mode remains independent (success/ambiguous/…). Hold point is
    orthogonal staging coordination configuration.
    """

    staging_context: VerifiedRetryCommandStagingContext
    evidence_root: Path
    marker_dir: Path
    control_dir: Path
    campaign_id: str = "default"
    hold_point: StagingLifecyclePoint | None = None
    hold_timeout_seconds: float | None = None
    poll_seconds: float = _POLL_SECONDS
    _bound_command_id: str | None = field(default=None, init=False, repr=False)
    _bound_attempt_id: str | None = field(default=None, init=False, repr=False)
    _bound_worker_id: str | None = field(default=None, init=False, repr=False)
    _held_points: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            assert_verified_staging_context(
                self.staging_context,
                what="StagingLifecycleCoordinator",
            )
        except StagingIdentityError as exc:
            raise StagingLifecycleCoordinationError(
                exc.reason,
                detail=exc.detail,
            ) from exc
        self.campaign_id = normalize_campaign_id(self.campaign_id)
        if self.hold_point is not None:
            self.hold_point = normalize_hold_point(self.hold_point)
        if self.poll_seconds <= 0:
            raise StagingLifecycleCoordinationError("invalid_poll_seconds")
        if self.hold_timeout_seconds is not None and self.hold_timeout_seconds < 0:
            raise StagingLifecycleCoordinationError("invalid_hold_timeout")

    @classmethod
    def from_verified_settings(
        cls,
        staging_context: VerifiedRetryCommandStagingContext,
        settings_obj: Any,
        *,
        evidence_root: str | Path | None = None,
        marker_dir: str | Path | None = None,
        control_dir: str | Path | None = None,
        campaign_id: str | None = None,
        hold_point: str | None = None,
        hold_timeout_seconds: float | None = None,
    ) -> StagingLifecycleCoordinator | None:
        """Build coordinator when staging coordination is configured.

        Returns None when marker/control/hold are all unset (coordination off).
        Fail-closed when hold is set without usable paths.
        """
        assert_verified_staging_context(
            staging_context,
            what="StagingLifecycleCoordinator.from_verified_settings",
        )
        cfg = settings_obj
        evidence_raw = _strip(
            evidence_root
            if evidence_root is not None
            else getattr(cfg, "PUBLISH_RETRY_COMMAND_STAGING_EVIDENCE_ROOT", "")
        )
        marker_raw = _strip(
            marker_dir
            if marker_dir is not None
            else getattr(cfg, "PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR", "")
        )
        control_raw = _strip(
            control_dir
            if control_dir is not None
            else getattr(cfg, "PUBLISH_RETRY_COMMAND_STAGING_CONTROL_DIR", "")
        )
        campaign_raw = (
            campaign_id
            if campaign_id is not None
            else getattr(cfg, "PUBLISH_RETRY_COMMAND_STAGING_CAMPAIGN_ID", None)
        )
        hold_raw = (
            hold_point
            if hold_point is not None
            else getattr(cfg, "PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT", None)
        )
        timeout_cfg = (
            hold_timeout_seconds
            if hold_timeout_seconds is not None
            else getattr(
                cfg,
                "PUBLISH_RETRY_COMMAND_STAGING_HOLD_TIMEOUT_SECONDS",
                None,
            )
        )

        hold = normalize_hold_point(hold_raw)
        if not evidence_raw and not marker_raw and not control_raw and hold is None:
            return None

        if not evidence_raw:
            if marker_raw:
                mp = Path(marker_raw).expanduser()
                # Compose layout: .../markers → evidence is parent.
                # Isolated test layout: MARKER_DIR alone → treat it as evidence root.
                evidence_raw = (
                    str(mp.parent) if mp.name == "markers" else str(mp)
                )
            elif control_raw:
                cp = Path(control_raw).expanduser()
                evidence_raw = (
                    str(cp.parent) if cp.name == "control" else str(cp)
                )
            else:
                evidence_raw = DEFAULT_STAGING_EVIDENCE_ROOT

        if not marker_raw:
            marker_raw = str(Path(evidence_raw) / "markers")
        elif (
            Path(marker_raw).expanduser().resolve()
            == Path(evidence_raw).expanduser().resolve()
        ):
            # Test/legacy: MARKER_DIR == evidence root → nest markers/
            marker_raw = str(Path(evidence_raw) / "markers")

        if not control_raw:
            control_raw = str(Path(evidence_raw) / "control")
        elif (
            Path(control_raw).expanduser().resolve()
            == Path(evidence_raw).expanduser().resolve()
        ):
            control_raw = str(Path(evidence_raw) / "control")

        if hold is not None and (not marker_raw or not control_raw):
            raise StagingLifecycleCoordinationError(
                "hold_requires_marker_and_control_dirs",
            )

        root = validate_staging_evidence_path(
            evidence_raw,
            evidence_root=evidence_raw,
            what="evidence_root",
        )
        # Re-validate children under the same root.
        marker_path = validate_staging_evidence_path(
            marker_raw,
            evidence_root=root,
            what="marker_dir",
        )
        control_path = validate_staging_evidence_path(
            control_raw,
            evidence_root=root,
            what="control_dir",
        )

        timeout: float | None
        if timeout_cfg is None or _strip(timeout_cfg) == "":
            timeout = None
        else:
            timeout = float(timeout_cfg)
            if timeout <= 0:
                timeout = None

        return cls(
            staging_context=staging_context,
            evidence_root=root,
            marker_dir=marker_path,
            control_dir=control_path,
            campaign_id=normalize_campaign_id(campaign_raw),
            hold_point=hold,
            hold_timeout_seconds=timeout,
        )

    def bind(
        self,
        *,
        command_id: UUID | str | None = None,
        attempt_id: UUID | str | None = None,
        worker_id: str | None = None,
    ) -> None:
        """Attach per-command metadata for subsequent markers (observability)."""
        if command_id is not None:
            self._bound_command_id = str(command_id)
        if attempt_id is not None:
            self._bound_attempt_id = str(attempt_id)
        if worker_id is not None:
            self._bound_worker_id = str(worker_id)

    def marker_path(self, point: str) -> Path:
        point = normalize_hold_point(point) or point
        if point not in ALLOWED_LIFECYCLE_POINTS:
            raise StagingLifecycleCoordinationError(
                "unsupported_lifecycle_point",
                detail=repr(point),
            )
        return self.marker_dir / self.campaign_id / point

    def release_path(self, point: str) -> Path:
        point = normalize_hold_point(point) or point
        if point not in ALLOWED_LIFECYCLE_POINTS:
            raise StagingLifecycleCoordinationError(
                "unsupported_lifecycle_point",
                detail=repr(point),
            )
        return self.control_dir / self.campaign_id / release_filename(point)

    def write_release(self, point: str) -> Path:
        """External campaign helper: create one-shot release file (durable)."""
        path = self.release_path(point)
        durable_write_marker(path, f"release=1\npoint={point}\n")
        return path

    def consume_release(self, point: str) -> bool:
        """Remove release file if present. Returns True when consumed."""
        path = self.release_path(point)
        try:
            if path.is_file():
                path.unlink()
                return True
        except OSError as exc:
            raise StagingLifecycleCoordinationError(
                "release_consume_failed",
                detail=str(exc),
            ) from exc
        return False

    def clear_campaign_artifacts(self) -> None:
        """Remove this campaign's marker + control files (stale isolation)."""
        for root in (self.marker_dir / self.campaign_id, self.control_dir / self.campaign_id):
            if not root.exists():
                continue
            for child in root.iterdir():
                if child.is_file():
                    try:
                        child.unlink()
                    except OSError:
                        logger.warning(
                            "[StagingLifecycle] failed to clear %s",
                            child,
                            exc_info=True,
                        )

    def _marker_payload(self, point: str) -> str:
        # Minimal metadata only — no secrets / payloads / bodies.
        lines = [
            f"point={point}",
            f"campaign_id={self.campaign_id}",
        ]
        if self._bound_command_id:
            lines.append(f"command_id={self._bound_command_id}")
        if self._bound_attempt_id:
            lines.append(f"attempt_id={self._bound_attempt_id}")
        if self._bound_worker_id:
            lines.append(f"worker_id={self._bound_worker_id}")
        lines.append(f"pid={os.getpid()}")
        return "\n".join(lines) + "\n"

    def write_marker(self, point: str) -> Path:
        path = self.marker_path(point)
        durable_write_marker(path, self._marker_payload(point))
        logger.info(
            "[StagingLifecycle] marker durable point=%s path=%s campaign=%s",
            point,
            path,
            self.campaign_id,
        )
        return path

    async def wait_for_release(self, point: str) -> None:
        """Async poll for campaign-scoped release file; consume once observed."""
        path = self.release_path(point)
        deadline: float | None = None
        if self.hold_timeout_seconds is not None:
            deadline = asyncio.get_running_loop().time() + float(
                self.hold_timeout_seconds
            )
        logger.info(
            "[StagingLifecycle] holding at point=%s waiting for %s timeout=%s",
            point,
            path,
            self.hold_timeout_seconds,
        )
        while True:
            if path.is_file():
                self.consume_release(point)
                logger.info(
                    "[StagingLifecycle] release observed point=%s — continuing once",
                    point,
                )
                return
            if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                raise StagingLifecycleHoldTimeoutError(
                    "hold_timeout",
                    detail=f"point={point} path={path}",
                )
            await asyncio.sleep(self.poll_seconds)

    async def mark_and_maybe_hold(
        self,
        point: str,
        *,
        command_id: UUID | str | None = None,
        attempt_id: UUID | str | None = None,
        worker_id: str | None = None,
    ) -> None:
        """Write durable marker; optionally hold until release (exactly once)."""
        if point not in ALLOWED_LIFECYCLE_POINTS:
            raise StagingLifecycleCoordinationError(
                "unsupported_lifecycle_point",
                detail=repr(point),
            )
        self.bind(
            command_id=command_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
        )
        self.write_marker(point)
        if self.hold_point == point:
            if point in self._held_points:
                # No replay of hold for the same process/point.
                return
            self._held_points.add(point)
            await self.wait_for_release(point)

    def build_executor_hooks(self) -> ExecutorHooks:
        """DI hooks for executor lifecycle points (excludes provider_entered)."""

        def _hook(point: StagingLifecyclePoint):
            def _inner():
                return self.mark_and_maybe_hold(point)

            return _inner

        return ExecutorHooks(
            after_prepare=_hook("after_prepare"),
            after_barrier=_hook("after_barrier"),
            before_provider=_hook("before_provider"),
            after_provider=_hook("after_provider"),
            before_finalize=_hook("before_finalize"),
        )
