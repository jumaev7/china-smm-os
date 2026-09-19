# Immutable Media Vault — V1 storage primitives (+ V1-R2 adapter)

Dormant content-addressed media storage. Not wired to acceptance, publish,
or provider execution.

## Boundary

| Surface | Behavior |
|---|---|
| `app.core.immutable_storage` | Vault create / verify only |
| `StorageService.save_file` / `save_at_key` / `delete_file` | Mutable media unchanged; **refuse** `vault/v1/` keys |
| Key format | `vault/v1/{sha256hex}` derived from verified content hash only |

## Local install

1. Exclusive temp create (`O_CREAT\|O_EXCL`)
2. Streamed write + `fsync`
3. Re-read staged bytes → SHA-256 + size
4. No-replace install (POSIX `link`; Windows `MoveFileW` without replace)
5. Final-object verification
6. Temp cleanup (failed creators never delete another writer's final)

## Cloudflare R2 adapter (V1-R2)

| Capability | Status | Evidence |
|---|---|---|
| PutObject `If-None-Match: *` | Documented | [R2 S3 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/) — PutObject conditional ops ✅ |
| Concurrent conditional creates | Documented pattern | Winner creates; loser gets `412 PreconditionFailed` → verify + reuse |
| GetObject byte readback | Documented | Used for SHA-256 verification (ETag is **not** SHA-256) |
| CompleteMultipartUpload conditionals | **Not documented** on R2 feature table | Objects above single-Put limit **rejected** (fail closed) |
| Single PutObject max | Documented | ~5 GiB (platform: 4.995 GiB) |
| Object Lock / bucket retention | ❌ Unimplemented on R2 | Do not claim storage-enforced lock immutability |
| Live R2 integration | **UNVERIFIED** | Requires authorized non-production bucket; not claimed here |

Exclusive create uses **only** conditional `PutObject` with `IfNoneMatch="*"`.
HEAD-then-unconditional-PUT is never used. Corrupted objects are never overwritten.

Mutable `StorageService._save_s3` remains unconditional PutObject and must never
be used as a vault fallback.

## Trust

Application-level immutability does not protect against privileged admins,
disk loss, or external modification of storage.

## Out of scope (later)

Vault delete, GC, media pinning, snapshots, provider adapters, multipart
exclusive create (pending documented R2 guarantees + live validation).
