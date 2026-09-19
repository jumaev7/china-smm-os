# Immutable Media Vault — V1 storage primitives

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

## R2 / S3

**UNVERIFIED** in V1. Vault ops fail closed when `USE_S3=True`.
Bucket locks and retention require separate authorization. Do not claim
storage-enforced immutability.

## Trust

Application-level immutability does not protect against privileged admins,
disk loss, or external modification of storage.

## Out of scope (later)

Vault delete, GC, media pinning, snapshots, provider adapters.
