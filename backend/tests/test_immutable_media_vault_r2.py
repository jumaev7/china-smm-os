"""I2c.1c / V1-R2 — Cloudflare R2 immutable storage adapter tests.

Environments:
  - MOCKED: in-process FakeR2Client (default; proves adapter logic)
  - Actual Cloudflare R2: UNVERIFIED (no authorized non-prod bucket used)

No production buckets, credentials, publication, registry, or provider publish calls.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.core.immutable_storage import (
    VAULT_NAMESPACE,
    ImmutableVault,
    R2ImmutableVault,
    R2_MAX_SINGLE_PUT_BYTES,
    VaultAmbiguousStateError,
    VaultCorruptionError,
    VaultInvalidKeyError,
    VaultMutationForbidden,
    VaultObjectTooLargeError,
    VaultProviderError,
    VaultUnsupportedBackendError,
    VerificationStatus,
    canonical_vault_key,
    get_immutable_vault,
    is_vault_storage_key,
    refuse_mutable_vault_mutation,
)
from app.core.storage import StorageService


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _FakeBody:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, n: int = -1):
        return self._buf.read(n)

    def close(self):
        self._buf.close()


class FakeR2Client:
    """Minimal S3-compatible mock with conditional PutObject semantics.

    This is MOCKED behavior — not an S3 emulator and not live Cloudflare R2.
    """

    def __init__(self, *, support_if_none_match: bool = True):
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []
        self.support_if_none_match = support_if_none_match
        self.fail_get = False
        self.put_error: Exception | None = None
        self.put_error_once: Exception | None = None
        self.lock = threading.Lock()
        self.meta = MagicMock()
        members = {"IfNoneMatch": object()} if support_if_none_match else {}
        self.meta.service_model.operation_model.return_value.input_shape.members = members

    def put_object(self, **kwargs):
        with self.lock:
            self.put_calls.append(dict(kwargs))
            if self.put_error_once is not None:
                err = self.put_error_once
                self.put_error_once = None
                raise err
            if self.put_error is not None:
                raise self.put_error
            if not self.support_if_none_match:
                raise _client_error("InvalidArgument", 400)
            if kwargs.get("IfNoneMatch") != "*":
                raise _client_error("InvalidArgument", 400)
            key = kwargs["Key"]
            body = kwargs["Body"]
            if hasattr(body, "read"):
                data = body.read()
            else:
                data = bytes(body)
            if key in self.objects:
                raise _client_error("PreconditionFailed", 412)
            self.objects[key] = data
            return {"ETag": '"fake-etag-not-sha256"'}

    def get_object(self, **kwargs):
        with self.lock:
            key = kwargs["Key"]
            self.get_calls.append(key)
            if self.fail_get:
                raise RuntimeError("simulated get failure")
            if key not in self.objects:
                raise _client_error("NoSuchKey", 404)
            data = self.objects[key]
            return {"Body": _FakeBody(data), "ContentLength": len(data)}


def _client_error(code: str, status: int):
    try:
        from botocore.exceptions import ClientError
    except ImportError:  # pragma: no cover
        exc = Exception(code)
        exc.response = {  # type: ignore[attr-defined]
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        return exc
    return ClientError(
        {"Error": {"Code": code, "Message": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "PutObject",
    )


@pytest.fixture
def fake_r2() -> FakeR2Client:
    return FakeR2Client()


@pytest.fixture
def r2_vault(fake_r2: FakeR2Client) -> R2ImmutableVault:
    return R2ImmutableVault(client=fake_r2, bucket="test-vault-bucket")


# ---------------------------------------------------------------------------
# A–D
# ---------------------------------------------------------------------------

def test_A_first_conditional_creation(r2_vault: R2ImmutableVault, fake_r2: FakeR2Client):
    data = b"r2-first-object"
    desc = r2_vault.put(data)
    assert desc.verified is True
    assert desc.reused is False
    assert desc.sha256 == _sha(data)
    assert desc.storage_key == f"{VAULT_NAMESPACE}/{desc.sha256}"
    assert fake_r2.objects[desc.storage_key] == data
    assert fake_r2.put_calls[-1]["IfNoneMatch"] == "*"


def test_B_identical_object_reuse(r2_vault: R2ImmutableVault, fake_r2: FakeR2Client):
    data = b"identical-r2-payload"
    first = r2_vault.put(data)
    puts_after_first = len(fake_r2.put_calls)
    second = r2_vault.put(data)
    assert second.reused is True
    assert second.verified is True
    assert second.storage_key == first.storage_key
    # Reuse via verify should not issue another PutObject
    assert len(fake_r2.put_calls) == puts_after_first
    assert len(fake_r2.objects) == 1


def test_C_different_bytes_different_keys(r2_vault: R2ImmutableVault):
    a = r2_vault.put(b"alpha-r2")
    b = r2_vault.put(b"beta-r2-different")
    assert a.storage_key != b.storage_key


def test_D_existing_key_cannot_be_overwritten(r2_vault: R2ImmutableVault, fake_r2: FakeR2Client):
    data = b"protected-r2-original"
    desc = r2_vault.put(data)
    # Force a second put path that hits PreconditionFailed
    fake_r2.objects[desc.storage_key] = data
    # Clear verify fast-path by making put go through conditional path:
    # put same data again → reuse without overwrite
    reused = r2_vault.put(data)
    assert reused.reused is True
    assert fake_r2.objects[desc.storage_key] == data

    # Simulate concurrent loser: object exists, put_object returns 412
    # Inject different body attempt at same key via direct put_object without vault
    with pytest.raises(Exception):
        fake_r2.put_object(
            Bucket="test-vault-bucket",
            Key=desc.storage_key,
            Body=b"EVIL-OVERWRITE",
            IfNoneMatch="*",
            ContentLength=14,
        )
    assert fake_r2.objects[desc.storage_key] == data


# ---------------------------------------------------------------------------
# E–F concurrency
# ---------------------------------------------------------------------------

def test_E_concurrent_identical_uploads(fake_r2: FakeR2Client):
    data = b"concurrent-r2-" + os.urandom(32)
    expected = _sha(data)
    barrier = threading.Barrier(8)
    results: list = []
    errors: list = []

    def worker():
        v = R2ImmutableVault(client=fake_r2, bucket="test-vault-bucket")
        barrier.wait(timeout=10)
        try:
            results.append(v.put(data))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert len(results) == 8
    assert all(r.sha256 == expected and r.verified for r in results)
    assert sum(1 for r in results if not r.reused) == 1
    assert sum(1 for r in results if r.reused) == 7
    assert len(fake_r2.objects) == 1
    assert fake_r2.objects[canonical_vault_key(expected)] == data


def test_F_concurrent_conflicting_writes(fake_r2: FakeR2Client):
    payloads = [f"r2-payload-{i}-".encode() + os.urandom(16) for i in range(6)]

    def worker(data: bytes):
        return R2ImmutableVault(client=fake_r2, bucket="test-vault-bucket").put(data)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(worker, p) for p in payloads]
        descs = [f.result(timeout=30) for f in as_completed(futs)]

    assert len({d.storage_key for d in descs}) == 6
    assert len(fake_r2.objects) == 6


# ---------------------------------------------------------------------------
# G–J missing / corrupt / hash / size
# ---------------------------------------------------------------------------

def test_G_missing_object(r2_vault: R2ImmutableVault):
    result = r2_vault.verify_object(sha256=_sha(b"never-written-r2"))
    assert result.verified is False
    assert result.status == VerificationStatus.MISSING


def test_H_existing_corrupted_object(r2_vault: R2ImmutableVault, fake_r2: FakeR2Client):
    data = b"good-then-corrupt-r2"
    desc = r2_vault.put(data)
    fake_r2.objects[desc.storage_key] = b"CORRUPTED-R2-CONTENT"
    with pytest.raises(VaultCorruptionError):
        r2_vault.put(data)
    assert fake_r2.objects[desc.storage_key] == b"CORRUPTED-R2-CONTENT"
    result = r2_vault.verify_object(sha256=desc.sha256)
    assert result.verified is False
    assert result.status == VerificationStatus.HASH_MISMATCH


def test_I_sha256_mismatch_rejected(r2_vault: R2ImmutableVault):
    with pytest.raises(VaultCorruptionError):
        r2_vault.put(b"actual-r2-bytes", expected_sha256="0" * 64)


def test_J_byte_size_mismatch(r2_vault: R2ImmutableVault):
    data = b"size-check-r2"
    desc = r2_vault.put(data)
    bad = r2_vault.verify_object(sha256=desc.sha256, expected_size=len(data) + 1)
    assert bad.verified is False
    assert bad.status == VerificationStatus.SIZE_MISMATCH


# ---------------------------------------------------------------------------
# K–L conditional rejected / unsupported backend
# ---------------------------------------------------------------------------

def test_K_conditional_request_rejected_by_backend():
    client = FakeR2Client(support_if_none_match=True)
    client.put_error = _client_error("InvalidArgument", 400)
    vault = R2ImmutableVault(client=client, bucket="test-vault-bucket")
    with pytest.raises(VaultUnsupportedBackendError):
        vault.put(b"reject-conditional")


def test_L_unsupported_backend_fails_closed():
    client = FakeR2Client(support_if_none_match=False)
    vault = R2ImmutableVault(client=client, bucket="test-vault-bucket")
    with pytest.raises(VaultUnsupportedBackendError):
        vault.put(b"no-if-none-match")


# ---------------------------------------------------------------------------
# M–O timeout / ambiguity / verify download failure
# ---------------------------------------------------------------------------

def test_M_timeout_before_write(fake_r2: FakeR2Client):
    class ReadTimeoutError(Exception):
        pass

    fake_r2.put_error = ReadTimeoutError("timeout before accept")
    vault = R2ImmutableVault(client=fake_r2, bucket="test-vault-bucket")
    with pytest.raises(VaultAmbiguousStateError):
        vault.put(b"timeout-before-write-bytes")
    assert fake_r2.objects == {}


def test_N_timeout_after_possible_successful_write(fake_r2: FakeR2Client):
    data = b"timeout-after-possible-success"
    key = canonical_vault_key(_sha(data))

    class ReadTimeoutError(Exception):
        pass

    real_put = fake_r2.put_object

    def put_then_timeout(**kwargs):
        # Provider may have accepted the object even if client times out.
        real_put(**kwargs)
        raise ReadTimeoutError("timeout after accept")

    fake_r2.put_object = put_then_timeout  # type: ignore[method-assign]
    vault = R2ImmutableVault(client=fake_r2, bucket="test-vault-bucket")
    desc = vault.put(data)
    assert desc.verified is True
    assert desc.storage_key == key
    assert fake_r2.objects[key] == data


def test_O_verification_download_failure(r2_vault: R2ImmutableVault, fake_r2: FakeR2Client):
    data = b"verify-download-fail"
    desc = r2_vault.put(data)
    fake_r2.fail_get = True
    with pytest.raises(VaultProviderError):
        r2_vault.verify_object(sha256=desc.sha256)


# ---------------------------------------------------------------------------
# P–Q large file / unsupported large object
# ---------------------------------------------------------------------------

def test_P_large_file_memory_behavior(r2_vault: R2ImmutableVault, tmp_path: Path, fake_r2: FakeR2Client):
    big = tmp_path / "big-r2.bin"
    size = 3 * 1024 * 1024
    with big.open("wb") as fh:
        fh.write(b"Y" * size)

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
        desc = r2_vault.put(cf)
    finally:
        cf.close()
    assert desc.byte_size == size
    assert desc.verified
    assert peak["n"] <= 1024 * 1024
    assert peak["n"] < size
    assert fake_r2.put_calls[-1]["IfNoneMatch"] == "*"


def test_Q_unsupported_large_object_rejected(r2_vault: R2ImmutableVault, fake_r2: FakeR2Client):
    vault = R2ImmutableVault(
        client=fake_r2,
        bucket="test-vault-bucket",
        max_single_put_bytes=1024,
    )
    with pytest.raises(VaultObjectTooLargeError):
        vault.put(b"x" * 2048)
    assert fake_r2.objects == {}
    assert fake_r2.put_calls == []


def test_Q_documented_max_constant():
    assert R2_MAX_SINGLE_PUT_BYTES == (5 * 1024 * 1024 * 1024) - (5 * 1024 * 1024)


# ---------------------------------------------------------------------------
# R invalid digest / key
# ---------------------------------------------------------------------------

def test_R_invalid_digest_and_key_rejected(r2_vault: R2ImmutableVault):
    with pytest.raises(VaultInvalidKeyError):
        canonical_vault_key("nope")
    result = r2_vault.verify_object(storage_key="vault/v1/../etc/passwd")
    assert result.verified is False
    assert result.status == VerificationStatus.INVALID_KEY


# ---------------------------------------------------------------------------
# S–U mutable upload / overwrite / deletion unchanged
# ---------------------------------------------------------------------------

async def _mutable_flow(vault_root: Path) -> None:
    svc = StorageService()
    key = await svc.save_file(b"mutable-r2-side", "a.jpg", "clients/demo")
    assert not is_vault_storage_key(key)
    await svc.save_at_key("clients/demo/exact.bin", b"one")
    await svc.save_at_key("clients/demo/exact.bin", b"two")
    assert (vault_root / "clients/demo/exact.bin").read_bytes() == b"two"
    await svc.delete_file(key)
    assert not (vault_root / key).exists()


def test_S_T_U_mutable_paths_unchanged(tmp_path: Path, monkeypatch):
    root = tmp_path / "media"
    root.mkdir()
    monkeypatch.setattr(settings, "USE_S3", False)
    monkeypatch.setattr(settings, "MEDIA_LOCAL_PATH", str(root))
    asyncio.run(_mutable_flow(root))


def test_S_mutable_s3_upload_still_unconditional(monkeypatch):
    """Mutable _save_s3 must not gain IfNoneMatch / vault semantics."""
    monkeypatch.setattr(settings, "USE_S3", True)
    monkeypatch.setattr(settings, "S3_BUCKET", "mutable-bucket")
    monkeypatch.setattr(settings, "S3_ACCESS_KEY", "test-key")
    monkeypatch.setattr(settings, "S3_SECRET_KEY", "test-secret")
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", "https://example.invalid")

    mock_client = MagicMock()
    mock_client.put_object.return_value = {}
    with patch("boto3.client", return_value=mock_client):
        svc = StorageService()

        async def run():
            return await svc.save_file(b"mut", "x.bin", "clients/x")

        key = asyncio.run(run())
    assert key.startswith("clients/x/")
    kwargs = mock_client.put_object.call_args.kwargs
    assert "IfNoneMatch" not in kwargs
    assert kwargs.get("Body") == b"mut"
    with pytest.raises(VaultMutationForbidden):
        refuse_mutable_vault_mutation(f"{VAULT_NAMESPACE}/{'a' * 64}", "written")


# ---------------------------------------------------------------------------
# V vault deletion blocked
# ---------------------------------------------------------------------------

async def _vault_delete_blocked(fake_r2: FakeR2Client) -> None:
    vault = R2ImmutableVault(client=fake_r2, bucket="test-vault-bucket")
    desc = vault.put(b"do-not-delete-r2")
    assert desc.storage_key in fake_r2.objects
    svc = StorageService()
    with pytest.raises(VaultMutationForbidden):
        await svc.delete_file(desc.storage_key)
    assert desc.storage_key in fake_r2.objects
    with pytest.raises(VaultMutationForbidden):
        await svc.save_at_key(desc.storage_key, b"overwrite")
    assert fake_r2.objects[desc.storage_key] == b"do-not-delete-r2"
    assert not hasattr(vault, "delete")
    assert not hasattr(vault, "delete_object")


def test_V_vault_deletion_blocked(fake_r2: FakeR2Client, monkeypatch):
    monkeypatch.setattr(settings, "USE_S3", True)
    asyncio.run(_vault_delete_blocked(fake_r2))


# ---------------------------------------------------------------------------
# X–Z no publication / registry / provider publish
# ---------------------------------------------------------------------------

def test_X_Y_Z_no_publication_registry_provider_side_effects(r2_vault: R2ImmutableVault):
    import app.core.immutable_storage as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    for needle in (
        "publish_intentional",
        "PublishAttempt",
        "publish_retry",
        "WriteCoordinationRegistry",
        "IntentionalPublication",
        "PublishService",
    ):
        assert needle not in src
    r2_vault.put(b"no-side-effects")


def test_facade_selects_r2(fake_r2: FakeR2Client):
    v = get_immutable_vault(use_s3=True, s3_client=fake_r2)
    assert v.backend_name == "r2"
    desc = v.put(b"via-facade")
    assert desc.verified is True


def test_live_r2_marked_unverified():
    assert R2ImmutableVault.live_r2_status == "UNVERIFIED"
    assert R2ImmutableVault.provider_status == "DOCUMENTED_CONDITIONAL_PUT"


def test_precondition_failed_reuses_after_race(fake_r2: FakeR2Client):
    data = b"race-reuse-bytes"
    key = canonical_vault_key(_sha(data))
    # First writer wins outside vault; second vault put hits 412 then verifies.
    fake_r2.objects[key] = data
    vault = R2ImmutableVault(client=fake_r2, bucket="test-vault-bucket")
    desc = vault.put(data)
    assert desc.reused is True
    assert desc.verified is True


def test_upload_succeeds_but_verification_hash_fails(fake_r2: FakeR2Client):
    data = b"verify-after-put-fail"
    key = canonical_vault_key(_sha(data))

    real_put = fake_r2.put_object

    def corrupt_on_put(**kwargs):
        real_put(**kwargs)
        # External corruption immediately after accept
        fake_r2.objects[kwargs["Key"]] = b"TAMPERED"

    fake_r2.put_object = corrupt_on_put  # type: ignore[method-assign]
    vault = R2ImmutableVault(client=fake_r2, bucket="test-vault-bucket")
    with pytest.raises(VaultCorruptionError):
        vault.put(data)
    assert fake_r2.objects[key] == b"TAMPERED"
