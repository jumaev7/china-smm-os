# China SMM OS Production Runbook

This runbook deploys the existing named Cloudflare Tunnel with production-built containers. It does not change Cloudflare DNS or purchase infrastructure.

## Safety boundary

- Development remains on `docker-compose.yml`.
- Production uses `docker-compose.production.yml` only.
- PostgreSQL, backend, and frontend do not publish host ports in production.
- Cloudflare Tunnel is the only public ingress.
- R2 is the only production media store.
- Never commit `.env.production`.

## One-time preparation

1. Run `powershell -ExecutionPolicy Bypass -File scripts/prepare-production-env.ps1`
   to copy the existing integration credentials and generate independent secrets.
2. Alternatively copy `.env.production.example` to `.env.production` and replace every placeholder.
3. URL-encode the PostgreSQL password inside `DATABASE_URL`.
4. In the named Cloudflare Tunnel configure:
   - `app.chinasmmos.com` -> `http://frontend:3000`
   - `api.chinasmmos.com` -> `http://backend:8000`
5. Keep `media.chinasmmos.com` attached to the R2 bucket, not to the tunnel.

## Validate without starting anything

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
```

The env file is used for Compose interpolation only. Secrets are explicitly
assigned per service; the Cloudflare token and PostgreSQL password are not
injected into application containers.

## Backup and migrate

Take a database backup before every migration. Then run:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml --profile tools run --rm migrate
```

## Start production

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
docker compose --env-file .env.production -f docker-compose.production.yml ps
```

## Smoke checks

- `https://api.chinasmmos.com/health` returns HTTP 200.
- `https://app.chinasmmos.com/login` loads without mixed-content errors.
- Tenant and admin authentication both work.
- A client review link opens from outside the host computer.
- One approved test item completes through the scheduler exactly once.

Run the repeatable health audit:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/production-health.ps1
```

Create and validate a production database backup:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/backup-production.ps1
```

## Publishing resilience recovery

Transient Facebook/Instagram/Telegram publish failures are classified and retried
automatically with bounded exponential backoff (`PUBLISH_MAX_ATTEMPTS`,
`PUBLISH_RETRY_BASE_SECONDS`, `PUBLISH_RETRY_MAX_SECONDS`). Meta `Retry-After`
is respected when present.

Do **not** expect automatic retries for authentication, permission, validation,
or unsupported-media failures — those are terminal and need operator action.

### Operator checklist

1. Open **Publishing → Queue** (or content Publish history) and check attempt
   badges: `retrying`, `operator_review`, `exhausted`, `in_progress`, `failed`.
2. For `retrying`, wait for `next_retry_at` or use guarded **Retry**.
3. For `operator_review` (usually Meta timed out while in progress):
   - Confirm in Meta Business Suite whether a live post already exists.
   - Only then use **Retry** — the UI asks for confirmation to avoid duplicates.
4. For `exhausted`: fix the underlying issue (token, media, permissions), then Retry.
5. Already-published destinations are blocked from creating a second external post
   (idempotency key + live `external_post_id` check).

### Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Stuck `publishing` / `in_progress` | Worker restart mid-publish | Wait for stale recovery (`PUBLISH_STALE_ATTEMPT_MINUTES`) or cancel/recover from queue |
| Meta `operator_review` | Ambiguous in-progress timeout | Verify live post; retry only if absent |
| Repeated `rate_limited` | Meta throttling | Let backoff run; raise base/max seconds only if needed |
| Auth/permission failures | Expired token / missing scopes | Reconnect Meta; do not force duplicate publishes |
| Duplicate approval/webhook | Same content approved twice | Dedup suppresses second live post |

API (authenticated, tenant-scoped):

- `GET /api/v1/publishing/attempts?status=retrying|failed|operator_review|exhausted|in_progress`
- `POST /api/v1/publishing/attempts/{id}/retry`
- `GET /api/v1/publishing/alerts` — deduplicated operator alerts (`state`, `severity`, `platform`, `client_id` filters)
- `GET /api/v1/publishing/alerts/counts` — open critical/warning counts
- `POST /api/v1/publishing/alerts/{id}/acknowledge`
- `POST /api/v1/publishing/alerts/{id}/resolve` — optional `{ "note": "..." }`

### Publish operator alerts

Publishing failures and recoveries create **deduplicated** tenant-scoped alerts
(`publish_operator_alerts`) so operators do not need to poll the queue.

Events: `operator_review`, `exhausted`, `terminal_failure`, `stale_in_progress`,
`recovery`, `repeated_failure`. Open failure alerts for a destination auto-resolve
when that same content/platform/account publishes successfully.

Outbound Telegram/email delivery is **disabled by default**. Enable only after
migration `20260923_publish_alert_telegram_delivery` is applied, in-app alerts
are verified, and a tenant-admin has configured an **explicit numeric chat ID
allowlist** (never client intake groups or publish channels):

| Variable | Default | Purpose |
|---|---|---|
| `PUBLISH_ALERT_REPEATED_FAILURE_THRESHOLD` | `3` | Failures on a destination before `repeated_failure` |
| `PUBLISH_ALERT_REPEATED_FAILURE_WINDOW_MINUTES` | `60` | Sliding window for the threshold |
| `PUBLISH_ALERT_TELEGRAM_ENABLED` | `false` | **Master kill switch** for Telegram outbox enqueue + send |
| `PUBLISH_ALERT_EMAIL_ENABLED` | `false` | Opt-in email stub (no SMTP yet — stays no-op) |
| `PUBLISH_ALERT_DELIVERY_COOLDOWN_SECONDS` | `300` | Min gap between outbound orchestration per alert |
| `PUBLISH_ALERT_TELEGRAM_WORKER_ENABLED` | `false` | Run the durable Telegram delivery worker |
| `PUBLISH_ALERT_TELEGRAM_WORKER_POLL_SECONDS` | `5` | Worker poll interval |
| `PUBLISH_ALERT_TELEGRAM_WORKER_BATCH_SIZE` | `10` | Max outbox rows claimed per tick |
| `PUBLISH_ALERT_TELEGRAM_MAX_ATTEMPTS` | `8` | Max send attempts per delivery |
| `PUBLISH_ALERT_TELEGRAM_RETRY_BASE_SECONDS` | `30` | Exponential backoff base |
| `PUBLISH_ALERT_TELEGRAM_RETRY_MAX_SECONDS` | `3600` | Backoff cap (also respects Telegram retry-after) |
| `PUBLISH_ALERT_TELEGRAM_LEASE_SECONDS` | `120` | Claim lease for concurrent workers |
| `PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED` | `false` | Global gate for recovery messages (tenant flag also required) |
| `PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED` | `false` | Allow tenant owners to mint Connect Telegram deep links |
| `PUBLISH_ALERT_TELEGRAM_ENROLLMENT_TOKEN_TTL_SECONDS` | `600` | Enrollment token TTL (clamped 60–1800) |
| `PUBLISH_ALERT_TELEGRAM_ENROLLMENT_POLL_SECONDS` | `3` | UI poll interval while waiting for `/start` |
| `PUBLISH_ALERT_TELEGRAM_MAX_CONFIRMED_RECIPIENTS` | `1` | Max confirmed operator recipients per tenant |
| `TELEGRAM_BOT_USERNAME` | *(empty)* | Public bot username for deep links (validated; `getMe` fallback) |
| `PUBLISH_ALERT_APP_BASE_URL` | `https://app.chinasmmos.com` | Deep-link origin in Telegram messages |

**Enrollment vs delivery:** Enabling enrollment (`PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED=true`)
only lets an authenticated tenant owner generate a short-lived Connect Telegram deep link
and confirm a private-chat candidate after `/start`. It does **not** enable alert delivery,
does not create outbox rows, and does not use `TELEGRAM_ADMIN_ID` / client intake groups /
publishing destinations as recipients. Keep delivery kill switches false until a recipient
is confirmed and outbound send is intentionally approved:

- `PUBLISH_ALERT_TELEGRAM_ENABLED=false`
- `PUBLISH_ALERT_TELEGRAM_WORKER_ENABLED=false`
- `PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED=false`

Migration `20260924_telegram_operator_enrollment` creates `publish_alert_telegram_enrollments`
(hash-only tokens, single-use consume, private-chat only). Webhook handling lives in
`telegram-webhook-worker` (same bot webhook path); the delivery worker stays idle while its
flag is false.

Telegram delivery uses a durable outbox (`publish_alert_telegram_deliveries`) with
dedupe keys so worker restarts cannot double-send. Recipients come only from
`tenant_publish_alert_telegram_settings` (numeric chat ID + allowlist). The shared
`TELEGRAM_BOT_TOKEN` is used to send; `TELEGRAM_ADMIN_ID` is **not** used as the
operator-alert destination.

Failed alert delivery never blocks publishing or creates social posts.

UI: **Publishing → Alerts** (`/publishing/alerts`) — in-app inbox plus separate
Telegram delivery settings / Connect Telegram enrollment / recent outbox attempts.

API (tenant owner/manager for mutating Telegram settings):

- `GET/PUT /api/v1/publishing/alerts/telegram-settings`
- `POST/GET /api/v1/publishing/alerts/telegram-enrollment` (+ revoke/confirm/reject)
- `GET /api/v1/publishing/alerts/telegram-recipients` (+ remove)
- `GET /api/v1/publishing/alerts/telegram-deliveries`
- `POST /api/v1/publishing/alerts/telegram-deliveries/{id}/cancel`
- `POST /api/v1/publishing/alerts/telegram-deliveries/{id}/retry`
- `POST /api/v1/publishing/alerts/telegram-deliveries/test` — requires `confirm=true`;
  refused while the global kill switch is false

Compose service `publish-alert-telegram-worker` runs
`python scripts/run_publish_alert_telegram_worker.py` and **idles** while
`PUBLISH_ALERT_TELEGRAM_WORKER_ENABLED=false` (no claims, no Telegram API calls).
Enable the worker flag only after tenant recipients are configured and the global
kill switch is intentionally turned on.

Never enable live Meta smoke flags unless intentionally publishing for real.

## Rollback

Do not delete volumes. Redeploy the last known-good image/commit, then run `up -d` again. Restore PostgreSQL only if the migration itself changed data incompatibly.
