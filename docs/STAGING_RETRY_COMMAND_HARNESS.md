# Staging retry-command fake harness (D2-B2a)

Local/CI-only proof path for:

`claim → prepare → barrier → fake provider ×1 → finalize`

**Not** a long-running worker. **Not** production. **No** real providers.

## Required staging identity (all must hold)

1. `APP_ENV=staging` (exactly)
2. `PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=fake`
3. `PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED=true`
4. Authoritative DB proof: `SELECT current_database()` → `china_smm_os_staging`
5. Database name is **not** production denylist `china_smm_os`

Parsed `DATABASE_URL` is preflight-only. Hostname alone never authorizes fake.

Provider secrets must be empty (hard fail): `TELEGRAM_BOT_TOKEN`, `META_APP_SECRET`.

## Example env (local disposable DB)

```env
APP_ENV=staging
DATABASE_URL=postgresql+asyncpg://postgres:password@127.0.0.1:54329/china_smm_os_staging
PUBLISH_RETRY_COMMANDS_ENABLED=true
PUBLISH_RETRY_COMMAND_WORKER_ENABLED=true
PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=true
PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=true
PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=fake
PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED=true
PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE=success
TELEGRAM_BOT_TOKEN=
META_APP_SECRET=
```

Prefer drop/recreate `china_smm_os_staging` between campaigns.

## Entrypoint

```bash
cd backend
python scripts/run_retry_command_staging_harness.py
```

No HTTP route. No FastAPI. No schedule.

## Worker boundary

`PublishRetryCommandWorker` remains D2-B1: `backend=fake` is **not** worker-runnable.
Fake execution is harness-only via `VerifiedRetryCommandStagingContext`.

## Synthetic markers

- Tenant/client name prefix: `staging-retry-`
- Correlation ID prefix: `staging-retry:`

Both required for staging eligibility. Canonical empty allowlist remains production default.

## Crash fidelity notes

- Post-barrier / pre-fake crash → command stays `provider_write_started`; future fake count = 0 (at-most-once, not exactly-once). Phase E owns recovery.
- Post-fake / pre-finalize crash → durable sink count stays 1; fake not called again. Phase E still required.
- Subprocess-level restart proof is deferred to D2-B2b if needed; B2a proves equivalent service-level hooks.
