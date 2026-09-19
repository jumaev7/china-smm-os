"""Immutable Media Vault storage primitives (I2c.1b / V1).

Dormant content-addressed storage under the ``vault/v1/`` namespace.

Capabilities (local backend):
  - SHA-256 over actual media bytes (streaming; no whole-file load required)
  - Exclusive object creation with no in-place overwrite
  - Safe concurrent creation (filesystem races, not an in-memory lock)
  - Existing-object integrity verification before reuse
  - Explicit corruption / missing / invalid-key detection (fail closed)

Not in V1:
  - Snapshot acceptance, provider execution, pinning, GC, or vault deletion
  - Storage-enforced R2 bucket locks / Object Lock (separate ops authorization)

Filesystem trust assumptions
----------------------------
Application-level immutability does **not** protect against privileged
administrators, disk loss, external storage modification, or compromised
hosts. Local atomic install relies on OS no-replace semantics
(``os.link`` on POSIX; ``MoveFileW`` without replace on Windows).

Cloudflare R2 status (V1): **UNVERIFIED**. When ``USE_S3`` is enabled, vault
operations fail closed. Do not claim storage-enforced immutability.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Iterator, Union

from app.core.config import settings

VAULT_NAMESPACE = "vault/v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_CHUNK = 1024 * 1024  # 1 MiB streaming chunks


class VaultError(Exception):
    """Base vault error (fail closed)."""


class VaultInvalidKeyError(VaultError):
    """Invalid SHA-256, path traversal, or malformed vault key."""


class VaultCorruptionError(VaultError):
    """Stored bytes do not match expected hash and/or size."""


class VaultMissingError(VaultError):
    """Expected vault object is absent."""


class VaultUnsupportedBackendError(VaultError):
    """Backend cannot prove safe exclusive create (e.g. R2 in V1)."""


class VaultMutationForbidden(VaultError):
    """Mutable StorageService APIs must not mutate vault objects."""


class VaultObjectTypeError(VaultError):
    """Path exists but is not a regular file."""


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    MISSING = "missing"
    HASH_MISMATCH = "hash_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    INVALID_KEY = "invalid_key"
    UNEXPECTED_TYPE = "unexpected_type"
    UNSUPPORTED_BACKEND = "unsupported_backend"


@dataclass(frozen=True)
class VaultObjectDescriptor:
    """Typed descriptor for a content-addressed vault object."""

    sha256: str
    byte_size: int
    storage_key: str
    verified: bool
    status: VerificationStatus = VerificationStatus.VERIFIED
    reused: bool = False


BytesSource = Union[bytes, bytearray, memoryview, BinaryIO, Path]


def normalize_sha256(value: str) -> str:
    """Return lowercase hex SHA-256 or raise VaultInvalidKeyError."""
    if not isinstance(value, str):
        raise VaultInvalidKeyError("SHA-256 must be a string")
    digest = value.strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise VaultInvalidKeyError("Invalid SHA-256 digest")
    return digest


def canonical_vault_key(sha256: str) -> str:
    """Derive the only allowed final key form: vault/v1/{sha256hex}."""
    digest = normalize_sha256(sha256)
    return f"{VAULT_NAMESPACE}/{digest}"


def is_vault_storage_key(key: str | None) -> bool:
    """True when *key* is under the vault namespace (any form)."""
    if not key or not isinstance(key, str):
        return False
    normalized = key.replace("\\", "/").lstrip("/")
    return normalized == VAULT_NAMESPACE or normalized.startswith(f"{VAULT_NAMESPACE}/")


def parse_vault_key(key: str) -> str:
    """Validate a vault storage key and return its SHA-256 component.

    Rejects absolute paths, traversal, extra components, and non-hex digests.
    Callers must not supply arbitrary final keys — only hash-derived keys.
    """
    if not isinstance(key, str) or not key:
        raise VaultInvalidKeyError("Empty vault key")
    if os.path.isabs(key) or (len(key) >= 2 and key[1] == ":"):
        raise VaultInvalidKeyError("Absolute paths are not allowed")
    normalized = key.replace("\\", "/").lstrip("/")
    if ".." in normalized.split("/"):
        raise VaultInvalidKeyError("Path traversal is not allowed")
    if normalized != key.replace("\\", "/") and key.startswith(("/", "\\")):
        raise VaultInvalidKeyError("Absolute paths are not allowed")
    parts = normalized.split("/")
    if len(parts) != 3 or parts[0] != "vault" or parts[1] != "v1":
        raise VaultInvalidKeyError("Vault key must be vault/v1/{sha256}")
    if parts[2].startswith(".") or not parts[2]:
        raise VaultInvalidKeyError("Untrusted vault object name")
    return normalize_sha256(parts[2])


def refuse_mutable_vault_mutation(key: str | None, operation: str) -> None:
    """Raise if a mutable StorageService operation targets a vault key."""
    if is_vault_storage_key(key):
        raise VaultMutationForbidden(
            f"Vault objects cannot be {operation} via mutable StorageService APIs"
        )


def sha256_stream(
    source: BytesSource,
    *,
    chunk_size: int = _DEFAULT_CHUNK,
) -> tuple[str, int]:
    """Compute SHA-256 over actual bytes without loading the whole payload.

    Never substitutes URL hashes, metadata hashes, or S3 ETags.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    hasher = hashlib.sha256()
    total = 0
    if isinstance(source, (bytes, bytearray, memoryview)):
        view = memoryview(source)
        for offset in range(0, len(view), chunk_size):
            chunk = view[offset : offset + chunk_size]
            hasher.update(chunk)
            total += len(chunk)
        return hasher.hexdigest(), total

    if isinstance(source, Path):
        with source.open("rb") as fh:
            return sha256_stream(fh, chunk_size=chunk_size)

    read = getattr(source, "read", None)
    if read is None:
        raise TypeError("source must be bytes, Path, or a binary file object")
    while True:
        chunk = read(chunk_size)
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TypeError("stream read() must return bytes")
        hasher.update(chunk)
        total += len(chunk)
    return hasher.hexdigest(), total


def _iter_chunks(
    source: BytesSource,
    *,
    chunk_size: int = _DEFAULT_CHUNK,
) -> Iterator[bytes]:
    if isinstance(source, (bytes, bytearray, memoryview)):
        view = memoryview(source)
        for offset in range(0, len(view), chunk_size):
            yield bytes(view[offset : offset + chunk_size])
        return
    if isinstance(source, Path):
        with source.open("rb") as fh:
            yield from _iter_chunks(fh, chunk_size=chunk_size)
        return
    read = getattr(source, "read", None)
    if read is None:
        raise TypeError("source must be bytes, Path, or a binary file object")
    while True:
        chunk = read(chunk_size)
        if not chunk:
            break
        yield bytes(chunk)


def _fsync_fd(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError:
        # Some platforms / mounts do not support fsync; durability best-effort.
        pass


def _fsync_dir(directory: Path) -> None:
    if os.name == "nt":
        # Directory fsync is not generally available on Windows.
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        _fsync_fd(fd)
    finally:
        os.close(fd)


def _install_no_replace(stage: Path, final: Path) -> None:
    """Install *stage* as *final* without replacing an existing object.

    POSIX: hard-link then unlink stage (fails if final exists).
    Windows: MoveFileW without MOVEFILE_REPLACE_EXISTING (error 183 if exists).

    Never uses ordinary overwrite rename or open(\"wb\") on the final path.
    """
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise FileExistsError(str(final))

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.MoveFileW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        kernel32.MoveFileW.restype = wintypes.BOOL
        ok = kernel32.MoveFileW(str(stage), str(final))
        if not ok:
            err = ctypes.get_last_error()
            # ERROR_ALREADY_EXISTS = 183
            if err == 183 or final.exists():
                raise FileExistsError(str(final))
            raise OSError(err, f"MoveFileW failed installing vault object ({err})")
        return

    os.link(stage, final)
    try:
        stage.unlink(missing_ok=True)
    except OSError:
        pass


def _assert_regular_file(path: Path) -> None:
    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        raise VaultMissingError(str(path)) from exc
    if stat.S_ISLNK(st.st_mode):
        raise VaultObjectTypeError("Symlink vault objects are not allowed")
    if not stat.S_ISREG(st.st_mode):
        raise VaultObjectTypeError("Vault object must be a regular file")


def _resolve_under(root: Path, relative_key: str) -> Path:
    """Resolve *relative_key* under *root*; reject escape via symlinks/.."""
    if os.path.isabs(relative_key) or ".." in relative_key.replace("\\", "/").split("/"):
        raise VaultInvalidKeyError("Path traversal is not allowed")
    root_resolved = root.resolve()
    candidate = (root / relative_key).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise VaultInvalidKeyError("Path escapes vault root") from exc
    return candidate


class LocalImmutableVault:
    """Local filesystem vault with exclusive create + hash verification."""

    def __init__(self, base_path: Path | str):
        self.base_path = Path(base_path)
        self.vault_root = self.base_path / VAULT_NAMESPACE
        self.vault_root.mkdir(parents=True, exist_ok=True)

    def path_for_key(self, storage_key: str) -> Path:
        digest = parse_vault_key(storage_key)
        return _resolve_under(self.base_path, canonical_vault_key(digest))

    def verify_object(
        self,
        *,
        sha256: str | None = None,
        storage_key: str | None = None,
        expected_size: int | None = None,
    ) -> VaultObjectDescriptor:
        """Read and hash stored bytes. verified=True only after a real check."""
        try:
            if storage_key is not None:
                digest = parse_vault_key(storage_key)
            elif sha256 is not None:
                digest = normalize_sha256(sha256)
            else:
                raise VaultInvalidKeyError("sha256 or storage_key required")
        except VaultInvalidKeyError:
            return VaultObjectDescriptor(
                sha256=(sha256 or "").lower() if sha256 else "",
                byte_size=0,
                storage_key=storage_key or "",
                verified=False,
                status=VerificationStatus.INVALID_KEY,
            )

        key = canonical_vault_key(digest)
        path = self.path_for_key(key)
        if not path.exists():
            return VaultObjectDescriptor(
                sha256=digest,
                byte_size=0,
                storage_key=key,
                verified=False,
                status=VerificationStatus.MISSING,
            )
        try:
            _assert_regular_file(path)
        except VaultObjectTypeError:
            return VaultObjectDescriptor(
                sha256=digest,
                byte_size=0,
                storage_key=key,
                verified=False,
                status=VerificationStatus.UNEXPECTED_TYPE,
            )
        except VaultMissingError:
            return VaultObjectDescriptor(
                sha256=digest,
                byte_size=0,
                storage_key=key,
                verified=False,
                status=VerificationStatus.MISSING,
            )

        actual_digest, actual_size = sha256_stream(path)
        if expected_size is not None and actual_size != expected_size:
            return VaultObjectDescriptor(
                sha256=digest,
                byte_size=actual_size,
                storage_key=key,
                verified=False,
                status=VerificationStatus.SIZE_MISMATCH,
            )
        if actual_size != path.stat().st_size:
            return VaultObjectDescriptor(
                sha256=digest,
                byte_size=actual_size,
                storage_key=key,
                verified=False,
                status=VerificationStatus.SIZE_MISMATCH,
            )
        if actual_digest != digest:
            return VaultObjectDescriptor(
                sha256=digest,
                byte_size=actual_size,
                storage_key=key,
                verified=False,
                status=VerificationStatus.HASH_MISMATCH,
            )
        return VaultObjectDescriptor(
            sha256=digest,
            byte_size=actual_size,
            storage_key=key,
            verified=True,
            status=VerificationStatus.VERIFIED,
        )

    def _stage_path(self, digest: str) -> Path:
        token = secrets.token_hex(8)
        name = f".tmp.{digest[:16]}.{os.getpid()}.{token}"
        return _resolve_under(self.base_path, f"{VAULT_NAMESPACE}/{name}")

    def _write_stage(self, stage: Path, source: BytesSource) -> tuple[str, int]:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(str(stage), flags, 0o644)
        hasher = hashlib.sha256()
        total = 0
        try:
            for chunk in _iter_chunks(source):
                os.write(fd, chunk)
                hasher.update(chunk)
                total += len(chunk)
            _fsync_fd(fd)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                stage.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        else:
            os.close(fd)

        # Staged-byte checksum verification (re-read, do not trust write alone).
        rehash, resize = sha256_stream(stage)
        if rehash != hasher.hexdigest() or resize != total:
            stage.unlink(missing_ok=True)
            raise VaultCorruptionError("Staged bytes failed checksum verification")
        return rehash, total

    def _cleanup_stage(self, stage: Path) -> None:
        try:
            if stage.exists():
                stage.unlink(missing_ok=True)
        except OSError:
            pass

    def put(
        self,
        source: BytesSource,
        *,
        expected_sha256: str | None = None,
        chunk_size: int = _DEFAULT_CHUNK,
    ) -> VaultObjectDescriptor:
        """Create or reuse a vault object for *source* bytes.

        Concurrent identical uploads resolve to one key. Existing objects are
        verified before reuse; corruption is never overwritten.
        """
        del chunk_size  # hashing uses module default; reserved for API stability
        # Hash input first when possible without double-reading Path/stream once.
        if isinstance(source, (bytes, bytearray, memoryview)):
            digest, size = sha256_stream(source)
            payload: BytesSource = source
        elif isinstance(source, Path):
            digest, size = sha256_stream(source)
            payload = source
        else:
            # Streams are single-pass: stage while hashing, then install.
            return self._put_stream_single_pass(source, expected_sha256=expected_sha256)

        if expected_sha256 is not None and normalize_sha256(expected_sha256) != digest:
            raise VaultCorruptionError("Input bytes do not match expected SHA-256")

        key = canonical_vault_key(digest)
        final = self.path_for_key(key)

        if final.exists():
            return self._reuse_existing(digest, key, size)

        stage = self._stage_path(digest)
        try:
            staged_digest, staged_size = self._write_stage(stage, payload)
            if staged_digest != digest or staged_size != size:
                raise VaultCorruptionError("Staging hash mismatch")
            try:
                _install_no_replace(stage, final)
            except FileExistsError:
                self._cleanup_stage(stage)
                return self._reuse_existing(digest, key, size)
            _fsync_dir(final.parent)
            # Final-object verification
            verified = self.verify_object(sha256=digest, expected_size=size)
            if not verified.verified:
                raise VaultCorruptionError(
                    f"Final object verification failed: {verified.status.value}"
                )
            return VaultObjectDescriptor(
                sha256=digest,
                byte_size=size,
                storage_key=key,
                verified=True,
                status=VerificationStatus.VERIFIED,
                reused=False,
            )
        finally:
            self._cleanup_stage(stage)

    def _put_stream_single_pass(
        self,
        source: BinaryIO,
        *,
        expected_sha256: str | None = None,
    ) -> VaultObjectDescriptor:
        """Stage from a one-shot stream: hash while writing, then install."""
        token = secrets.token_hex(8)
        stage = _resolve_under(
            self.base_path,
            f"{VAULT_NAMESPACE}/.tmp.stream.{os.getpid()}.{token}",
        )
        try:
            digest, size = self._write_stage(stage, source)
            if expected_sha256 is not None and normalize_sha256(expected_sha256) != digest:
                raise VaultCorruptionError("Input bytes do not match expected SHA-256")
            key = canonical_vault_key(digest)
            final = self.path_for_key(key)
            if final.exists():
                self._cleanup_stage(stage)
                return self._reuse_existing(digest, key, size)
            try:
                _install_no_replace(stage, final)
            except FileExistsError:
                self._cleanup_stage(stage)
                return self._reuse_existing(digest, key, size)
            _fsync_dir(final.parent)
            verified = self.verify_object(sha256=digest, expected_size=size)
            if not verified.verified:
                raise VaultCorruptionError(
                    f"Final object verification failed: {verified.status.value}"
                )
            return VaultObjectDescriptor(
                sha256=digest,
                byte_size=size,
                storage_key=key,
                verified=True,
                status=VerificationStatus.VERIFIED,
                reused=False,
            )
        finally:
            self._cleanup_stage(stage)

    def _reuse_existing(
        self,
        digest: str,
        key: str,
        expected_size: int,
    ) -> VaultObjectDescriptor:
        verified = self.verify_object(sha256=digest, expected_size=expected_size)
        if not verified.verified:
            # Fail closed — never overwrite a corrupted object.
            raise VaultCorruptionError(
                f"Existing vault object failed verification: {verified.status.value}"
            )
        return VaultObjectDescriptor(
            sha256=digest,
            byte_size=verified.byte_size,
            storage_key=key,
            verified=True,
            status=VerificationStatus.VERIFIED,
            reused=True,
        )


class UnsupportedImmutableVault:
    """Fail-closed vault backend for unverified providers (R2 / S3)."""

    provider_status = "UNVERIFIED"

    def put(self, *args, **kwargs) -> VaultObjectDescriptor:
        raise VaultUnsupportedBackendError(
            "Immutable vault R2/S3 backend is UNVERIFIED in V1; "
            "refusing vault writes (fail closed). "
            "Bucket locks / retention require separate authorization."
        )

    def verify_object(self, *args, **kwargs) -> VaultObjectDescriptor:
        return VaultObjectDescriptor(
            sha256="",
            byte_size=0,
            storage_key="",
            verified=False,
            status=VerificationStatus.UNSUPPORTED_BACKEND,
        )

    def path_for_key(self, storage_key: str) -> Path:
        parse_vault_key(storage_key)
        raise VaultUnsupportedBackendError(
            "Immutable vault R2/S3 backend is UNVERIFIED in V1"
        )


class ImmutableVault:
    """Facade selecting local or fail-closed unsupported cloud backend."""

    def __init__(
        self,
        *,
        base_path: Path | str | None = None,
        use_s3: bool | None = None,
    ):
        self.use_s3 = settings.USE_S3 if use_s3 is None else use_s3
        if self.use_s3:
            self._backend: LocalImmutableVault | UnsupportedImmutableVault = (
                UnsupportedImmutableVault()
            )
            self.backend_name = "r2_s3_unverified"
        else:
            root = Path(base_path if base_path is not None else settings.MEDIA_LOCAL_PATH)
            self._backend = LocalImmutableVault(root)
            self.backend_name = "local"

    def put(self, source: BytesSource, **kwargs) -> VaultObjectDescriptor:
        return self._backend.put(source, **kwargs)

    def verify_object(self, **kwargs) -> VaultObjectDescriptor:
        return self._backend.verify_object(**kwargs)

    def path_for_key(self, storage_key: str) -> Path:
        return self._backend.path_for_key(storage_key)


def get_immutable_vault(
    *,
    base_path: Path | str | None = None,
    use_s3: bool | None = None,
) -> ImmutableVault:
    """Factory for vault access (dormant; unused by publish/media paths in V1)."""
    return ImmutableVault(base_path=base_path, use_s3=use_s3)
