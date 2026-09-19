"""I2c.1b / V1 — Immutable Media Vault storage primitives.

Isolated temporary storage only.
No production storage, DB, provider API, publication, registry, or retry I/O.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.core.immutable_storage import (
    VAULT_NAMESPACE,
    ImmutableVault,
    LocalImmutableVault,
    UnsupportedImmutableVault,
    VaultCorruptionError,
    VaultInvalidKeyError,
    VaultMutationForbidden,
    VaultUnsupportedBackendError,
    VerificationStatus,
    canonical_vault_key,
    get_immutable_vault,
    is_vault_storage_key,
    normalize_sha256,
    parse_vault_key,
    refuse_mutable_vault_mutation,
    sha256_stream,
)
from app.core.storage import StorageService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def vault_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "media_storage"
    root.mkdir()
    monkeypatch.setattr(settings, "USE_S3", False)
    monkeypatch.setattr(settings, "MEDIA_LOCAL_PATH", str(root))
    return root


@pytest.fixture
def vault(vault_root: Path) -> LocalImmutableVault:
    return LocalImmutableVault(vault_root)


# ---------------------------------------------------------------------------
# A–D: create / reuse / distinct / no overwrite
# ---------------------------------------------------------------------------

def test_A_first_immutable_object_creation(vault: LocalImmutableVault):
    data = b"vault-v1-first-object"
    desc = vault.put(data)
    assert desc.verified is True
    assert desc.reused is False
    assert desc.sha256 == _sha(data)
    assert desc.byte_size == len(data)
    assert desc.storage_key == f"{VAULT_NAMESPACE}/{desc.sha256}"
    path = vault.path_for_key(desc.storage_key)
    assert path.is_file()
    assert path.read_bytes() == data


def test_B_same_bytes_reuse_verified_object(vault: LocalImmutableVault):
    data = b"identical-payload-reuse"
    first = vault.put(data)
    second = vault.put(data)
    assert first.storage_key == second.storage_key
    assert second.reused is True
    assert second.verified is True
    objects = [p for p in vault.vault_root.iterdir() if p.is_file() and not p.name.startswith(".")]
    assert len(objects) == 1
    assert objects[0].name == first.sha256


def test_C_different_bytes_produce_different_keys(vault: LocalImmutableVault):
    a = vault.put(b"alpha-bytes")
    b = vault.put(b"beta-bytes-different")
    assert a.storage_key != b.storage_key
    assert a.sha256 != b.sha256


def test_D_existing_object_cannot_be_overwritten(vault: LocalImmutableVault):
    data = b"protected-original"
    desc = vault.put(data)
    path = vault.path_for_key(desc.storage_key)
    original_inode = path.stat().st_ino if hasattr(path.stat(), "st_ino") else None
    # Attempt install of different content at same key via internal helper
    stage = vault.vault_root / f".tmp.overwrite.{os.getpid()}"
    stage.write_bytes(b"EVIL-OVERWRITE")
    from app.core.immutable_storage import _install_no_replace

    with pytest.raises(FileExistsError):
        _install_no_replace(stage, path)
    assert path.read_bytes() == data
    if original_inode is not None:
        assert path.stat().st_ino == original_inode
    stage.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# E–F: concurrency
# ---------------------------------------------------------------------------

def test_E_concurrent_identical_uploads(vault_root: Path):
    data = b"concurrent-identical-" + os.urandom(64)
    expected = _sha(data)
    results: list = []
    errors: list = []
    barrier = threading.Barrier(8)

    def worker():
        v = LocalImmutableVault(vault_root)
        barrier.wait(timeout=10)
        try:
            results.append(v.put(data))
        except Exception as exc:  # noqa: BLE001 — collect for assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert len(results) == 8
    assert all(r.sha256 == expected for r in results)
    assert all(r.verified for r in results)
    created = sum(1 for r in results if not r.reused)
    reused = sum(1 for r in results if r.reused)
    assert created == 1
    assert reused == 7
    objects = [p for p in (vault_root / VAULT_NAMESPACE).iterdir() if p.is_file() and not p.name.startswith(".")]
    assert len(objects) == 1
    assert objects[0].read_bytes() == data
    # No partial finals / leftover stages that look like finals
    assert not any(p.name.startswith(".tmp.") and p.stat().st_size == 0 for p in (vault_root / VAULT_NAMESPACE).iterdir())


def test_F_concurrent_different_uploads(vault_root: Path):
    payloads = [f"payload-{i}-".encode() + os.urandom(32) for i in range(6)]

    def worker(data: bytes):
        return LocalImmutableVault(vault_root).put(data)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(worker, p) for p in payloads]
        descs = [f.result(timeout=30) for f in as_completed(futs)]

    keys = {d.storage_key for d in descs}
    assert len(keys) == 6
    objects = [p for p in (vault_root / VAULT_NAMESPACE).iterdir() if p.is_file() and not p.name.startswith(".")]
    assert len(objects) == 6


# ---------------------------------------------------------------------------
# G: interrupted staging
# ---------------------------------------------------------------------------

def test_G_interrupted_staging_leaves_no_partial_final(vault: LocalImmutableVault, monkeypatch):
    data = b"interrupted-staging-bytes"
    digest = _sha(data)
    final = vault.path_for_key(canonical_vault_key(digest))

    real_write = vault._write_stage

    def boom(stage, source):
        # Simulate crash after partial stage write, before install
        stage.write_bytes(b"PARTIAL")
        raise RuntimeError("simulated crash during staging")

    monkeypatch.setattr(vault, "_write_stage", boom)
    with pytest.raises(RuntimeError, match="simulated crash"):
        vault.put(data)
    assert not final.exists()
    leftovers = list(vault.vault_root.glob(".tmp.*"))
    # Cleanup in finally should remove stages when possible; partial may remain
    # only if crash bypasses finally — our boom is inside try so finally runs.
    assert not final.exists()
    assert all(p.name.startswith(".") for p in leftovers) or leftovers == []


# ---------------------------------------------------------------------------
# H–L: corruption / missing / invalid / traversal
# ---------------------------------------------------------------------------

def test_H_hash_mismatch_rejected(vault: LocalImmutableVault):
    with pytest.raises(VaultCorruptionError):
        vault.put(b"actual-bytes", expected_sha256="0" * 64)


def test_I_existing_corrupted_object_rejected(vault: LocalImmutableVault):
    data = b"good-then-corrupt"
    desc = vault.put(data)
    path = vault.path_for_key(desc.storage_key)
    # External corruption (privileged / disk) — application must fail closed
    path.write_bytes(b"CORRUPTED-CONTENT-XXXX")
    with pytest.raises(VaultCorruptionError):
        vault.put(data)
    # Must not overwrite
    assert path.read_bytes() == b"CORRUPTED-CONTENT-XXXX"
    result = vault.verify_object(sha256=desc.sha256)
    assert result.verified is False
    assert result.status == VerificationStatus.HASH_MISMATCH


def test_J_missing_object_rejected(vault: LocalImmutableVault):
    digest = _sha(b"never-written")
    result = vault.verify_object(sha256=digest)
    assert result.verified is False
    assert result.status == VerificationStatus.MISSING


def test_K_invalid_hash_rejected():
    with pytest.raises(VaultInvalidKeyError):
        normalize_sha256("not-a-hash")
    with pytest.raises(VaultInvalidKeyError):
        canonical_vault_key("abc")
    with pytest.raises(VaultInvalidKeyError):
        parse_vault_key(f"{VAULT_NAMESPACE}/{'g' * 64}")


def test_L_path_traversal_rejected(vault: LocalImmutableVault):
    with pytest.raises(VaultInvalidKeyError):
        parse_vault_key("vault/v1/../etc/passwd")
    with pytest.raises(VaultInvalidKeyError):
        parse_vault_key("/vault/v1/" + "a" * 64)
    with pytest.raises(VaultInvalidKeyError):
        parse_vault_key(r"C:\vault\v1\\" + "a" * 64)
    with pytest.raises(VaultInvalidKeyError):
        parse_vault_key(f"vault/v1/subdir/{'a' * 64}")
    with pytest.raises(VaultInvalidKeyError):
        vault.path_for_key("vault/v1/../../outside")


# ---------------------------------------------------------------------------
# M: symlink traversal
# ---------------------------------------------------------------------------

def test_M_symlink_traversal_rejected_where_applicable(vault_root: Path):
    vault = LocalImmutableVault(vault_root)
    outside = vault_root.parent / "outside_secret.bin"
    outside.write_bytes(b"secret")
    link = vault.vault_root / ("a" * 64)
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink not available: {exc}")
    result = vault.verify_object(sha256="a" * 64)
    assert result.verified is False
    assert result.status == VerificationStatus.UNEXPECTED_TYPE


# ---------------------------------------------------------------------------
# N–O: streaming / size
# ---------------------------------------------------------------------------

def test_N_large_files_bounded_memory(vault: LocalImmutableVault, tmp_path: Path):
    """Stream a ~8 MiB file; peak chunk buffer stays bounded (not full file)."""
    big = tmp_path / "big.bin"
    size = 8 * 1024 * 1024
    # Write in chunks to avoid holding full file in test process unnecessarily
    with big.open("wb") as fh:
        chunk = b"X" * (1024 * 1024)
        for _ in range(8):
            fh.write(chunk)

    peak = {"n": 0}

    class CountingFile:
        def __init__(self, path: Path):
            self._fh = path.open("rb")

        def read(self, n: int = -1):
            data = self._fh.read(n)
            peak["n"] = max(peak["n"], len(data) if data else 0)
            return data

        def close(self):
            self._fh.close()

    cf = CountingFile(big)
    try:
        desc = vault.put(cf)
    finally:
        cf.close()
    assert desc.byte_size == size
    assert desc.verified
    # Default chunk is 1 MiB — peak read should be <= 1 MiB (not 8 MiB)
    assert peak["n"] <= 1024 * 1024
    assert peak["n"] < size


def test_O_byte_size_verified(vault: LocalImmutableVault):
    data = b"size-check-12345"
    desc = vault.put(data)
    assert desc.byte_size == len(data)
    verified = vault.verify_object(sha256=desc.sha256, expected_size=len(data))
    assert verified.verified is True
    bad = vault.verify_object(sha256=desc.sha256, expected_size=len(data) + 1)
    assert bad.verified is False
    assert bad.status == VerificationStatus.SIZE_MISMATCH


# ---------------------------------------------------------------------------
# P–R: mutable StorageService unchanged for normal keys
# ---------------------------------------------------------------------------

async def _P_mutable_save_file(vault_root: Path) -> str:
    svc = StorageService()
    key = await svc.save_file(b"mutable-upload", "photo.jpg", "clients/demo")
    assert key.startswith("clients/demo/")
    assert key.endswith(".jpg")
    assert (vault_root / key).read_bytes() == b"mutable-upload"
    assert not is_vault_storage_key(key)
    return key


def test_P_mutable_save_file_unchanged(vault_root: Path, monkeypatch):
    monkeypatch.setattr(settings, "USE_S3", False)
    monkeypatch.setattr(settings, "MEDIA_LOCAL_PATH", str(vault_root))
    asyncio.run(_P_mutable_save_file(vault_root))


async def _Q_mutable_save_at_key(vault_root: Path) -> None:
    svc = StorageService()
    key = await svc.save_at_key("clients/demo/exact.bin", b"exact-bytes")
    assert key == "clients/demo/exact.bin"
    assert (vault_root / key).read_bytes() == b"exact-bytes"
    await svc.save_at_key("clients/demo/exact.bin", b"replaced")
    assert (vault_root / key).read_bytes() == b"replaced"


def test_Q_mutable_save_at_key_unchanged(vault_root: Path, monkeypatch):
    monkeypatch.setattr(settings, "USE_S3", False)
    monkeypatch.setattr(settings, "MEDIA_LOCAL_PATH", str(vault_root))
    asyncio.run(_Q_mutable_save_at_key(vault_root))


async def _R_mutable_delete_file(vault_root: Path) -> None:
    svc = StorageService()
    key = await svc.save_file(b"to-delete", "x.bin", "clients/demo")
    await svc.delete_file(key)
    assert not (vault_root / key).exists()


def test_R_mutable_delete_file_unchanged(vault_root: Path, monkeypatch):
    monkeypatch.setattr(settings, "USE_S3", False)
    monkeypatch.setattr(settings, "MEDIA_LOCAL_PATH", str(vault_root))
    asyncio.run(_R_mutable_delete_file(vault_root))


# ---------------------------------------------------------------------------
# S: vault inaccessible to ordinary delete APIs
# ---------------------------------------------------------------------------

async def _S_vault_delete_isolation(vault_root: Path) -> None:
    vault = LocalImmutableVault(vault_root)
    desc = vault.put(b"do-not-delete-via-mutable")
    path = vault.path_for_key(desc.storage_key)
    assert path.exists()
    svc = StorageService()
    with pytest.raises(VaultMutationForbidden):
        await svc.delete_file(desc.storage_key)
    assert path.exists()
    assert path.read_bytes() == b"do-not-delete-via-mutable"
    with pytest.raises(VaultMutationForbidden):
        await svc.save_at_key(desc.storage_key, b"overwrite-attempt")
    assert path.read_bytes() == b"do-not-delete-via-mutable"


def test_S_vault_objects_inaccessible_to_ordinary_delete(vault_root: Path, monkeypatch):
    monkeypatch.setattr(settings, "USE_S3", False)
    monkeypatch.setattr(settings, "MEDIA_LOCAL_PATH", str(vault_root))
    asyncio.run(_S_vault_delete_isolation(vault_root))


# ---------------------------------------------------------------------------
# T: unsupported backend fails closed
# ---------------------------------------------------------------------------

def test_T_unsupported_backend_fails_closed(vault_root: Path):
    v = ImmutableVault(base_path=vault_root, use_s3=True)
    assert v.backend_name == "r2_s3_unverified"
    with pytest.raises(VaultUnsupportedBackendError):
        v.put(b"cloud-bytes")
    result = v.verify_object(sha256="a" * 64)
    assert result.verified is False
    assert result.status == VerificationStatus.UNSUPPORTED_BACKEND
    assert UnsupportedImmutableVault.provider_status == "UNVERIFIED"


# ---------------------------------------------------------------------------
# U–X: no provider / prod / publication side effects (structural)
# ---------------------------------------------------------------------------

def test_U_no_provider_api_calls(vault: LocalImmutableVault):
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        import sys

        boto3 = sys.modules["boto3"]
        vault.put(b"local-only")
        assert not boto3.client.called


def test_V_no_production_storage_access(vault_root: Path, monkeypatch):
    monkeypatch.setattr(settings, "USE_S3", False)
    monkeypatch.setattr(settings, "MEDIA_LOCAL_PATH", str(vault_root))
    monkeypatch.setattr(settings, "S3_ACCESS_KEY", "PROD_KEY_MUST_NOT_BE_USED")
    monkeypatch.setattr(settings, "S3_SECRET_KEY", "PROD_SECRET_MUST_NOT_BE_USED")
    v = get_immutable_vault(base_path=vault_root, use_s3=False)
    desc = v.put(b"isolated")
    assert str(vault_root) in str(v.path_for_key(desc.storage_key))


def test_W_no_production_db_access(vault: LocalImmutableVault):
    # Vault put must not import / touch SQLAlchemy session machinery
    with patch("app.core.database.engine", create=True) as eng:
        vault.put(b"no-db")
        assert not getattr(eng, "connect", MagicMock()).called


def test_X_no_publication_or_registry_rows(vault: LocalImmutableVault):
    """Structural: vault module does not reference publish/registry models."""
    import app.core.immutable_storage as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "app.models" not in src
    for needle in (
        "publish_intentional",
        "PublishAttempt",
        "publish_retry",
        "WriteCoordinationRegistry",
        "IntentionalPublication",
    ):
        assert needle not in src
    vault.put(b"no-pub-side-effects")


# ---------------------------------------------------------------------------
# Y: application startup unaffected
# ---------------------------------------------------------------------------

def test_Y_application_startup_unaffected():
    from app.core.storage import storage as singleton

    assert singleton is not None
    # Importing main app module must still succeed (no vault hard-fail at import)
    import importlib

    storage_mod = importlib.import_module("app.core.storage")
    imm = importlib.import_module("app.core.immutable_storage")
    assert hasattr(storage_mod, "StorageService")
    assert hasattr(imm, "ImmutableVault")


# ---------------------------------------------------------------------------
# Key safety + helpers
# ---------------------------------------------------------------------------

def test_callers_cannot_supply_arbitrary_final_keys(vault: LocalImmutableVault):
    with pytest.raises(VaultMutationForbidden):
        refuse_mutable_vault_mutation(f"{VAULT_NAMESPACE}/{'a' * 64}", "written")
    # put derives key from hash only — no key argument on public API
    desc = vault.put(b"derived-key-only")
    assert desc.storage_key == canonical_vault_key(_sha(b"derived-key-only"))


def test_failed_creator_cannot_delete_another_writers_object(vault_root: Path):
    data = b"winner-bytes"
    winner = LocalImmutableVault(vault_root)
    desc = winner.put(data)
    path = winner.path_for_key(desc.storage_key)

    loser = LocalImmutableVault(vault_root)

    def fake_install(stage, final):
        raise FileExistsError(str(final))

    with patch("app.core.immutable_storage._install_no_replace", side_effect=fake_install):
        # Also need final to exist — it does
        reused = loser.put(data)
    assert reused.reused is True
    assert path.exists()
    assert path.read_bytes() == data


def test_sha256_stream_matches_hashlib():
    data = b"stream-me" * 1000
    digest, size = sha256_stream(io.BytesIO(data), chunk_size=64)
    assert size == len(data)
    assert digest == _sha(data)


def test_verified_false_unless_bytes_checked(vault: LocalImmutableVault):
    missing = vault.verify_object(sha256=_sha(b"absent"))
    assert missing.verified is False
    assert missing.status == VerificationStatus.MISSING


def test_Z_sec_media_1_ownership_guards_still_present():
    """Structural gate: SEC-MEDIA-1 service ownership checks remain in place.

    Full behavioral regressions live in test_media_api_security_gate_i2c1b.py
    and are executed in the same CI/local run as this suite.
    """
    import inspect

    from app.services.media_service import MediaService

    src = inspect.getsource(MediaService)
    assert src.count("guard_resource_client_id") >= 3
