# Mobile Operator Control Plane

## Purpose

Personal **owner/operator** mobile control — not a full dashboard clone.

Phase 1 (this document + backend) prepares a thin control plane so a future React Native / Expo app can:

- see what needs attention
- approve eligible content
- acknowledge / resolve eligible alerts
- retry safe publishes
- inspect sanitized system + integration posture

All **canonical decisions and mutations** remain in existing backend services. The mobile client must not duplicate business logic.

Auto-Ack shadow mode is **out of scope** and must not be modified by mobile work.

## Scope (four tabs)

| Tab | Shows | Mutations |
|-----|--------|-----------|
| **Today** | Urgent critical/high items, attention counts, unread badge | Via Workspace actions only |
| **Approvals** | `content_internal_review` | `approve_content` when offered in `actions[]` |
| **Problems** | publishing / scheduling / integration / telegram / automation | ack / resolve / retry when offered |
| **System** | Sanitized API/DB/scheduler/AI/Telegram + integration attention | Read-only |

Keep on **web**:

- configuration, campaigns, OAuth, bulk edit, analytics exploration, admin diagnostics

## API contract (Phase 1)

### Reuse (preferred)

| Need | Endpoint |
|------|----------|
| Login / refresh / logout / me | `POST/GET /api/v1/auth/{login,refresh,logout,me}` |
| Attention queue | `GET /api/v1/operator-workspace/{summary,items,metrics}` |
| Safe mutations | `POST /api/v1/operator-workspace/items/{attention_id}/actions/{action_id}` |
| Notifications (poll) | `GET/PATCH /api/v1/notifications*` |
| Integration health | `GET /api/v1/integrations/health` (`live_check=false`) |

### Thin aggregation (new)

| Need | Endpoint |
|------|----------|
| Home / Today bootstrap | `GET /api/v1/mobile-control/home` |
| System tab | `GET /api/v1/mobile-control/system` |

**Home guarantees**

- No provider live calls
- No mutations
- Tenant / client scope via same Workspace collectors
- Bounded `urgent_items` (`urgent_limit` 1–25, default 10)
- `capabilities` flags for slower-updating clients

**Do not call from mobile UI**

- Public `GET /api/v1/system/health` (too rich / unauthenticated surface)
- Admin diagnostics / platform-ops deep health
- Host backup scripts / R2 credentials
- Public client-review token routes (operator must not impersonate client)

### Action audit source

Mutations accept:

- body `source`: `"web" | "mobile"`
- or header `X-Client-Source: mobile|web`

Stored in `PlatformAuditLog.details.source` (default `web`). Autonomous Auto-Ack remains a separate event path — not `source=mobile`.

### Confirmation tiers (UX metadata)

Additive on `actions[]` — does **not** weaken backend gates:

| Tier | Examples |
|------|----------|
| `low` | open, acknowledge informational alert |
| `medium` | approve_content, resolve_alert, retry_publish |
| `high` | reserved (operator_review retry, OAuth, destructive) — **not exposed** in Phase 1 |

## Item detail model

Mobile uses existing `OperatorAttentionItem`:

- `id`, `attention_type`, `client_id` / `company_name`, `title`, `reason`, `priority`
- `responsible_party`, timestamps, `current_state`, `resource_id` / `content_id`
- `actions[]` (eligibility recomputed server-side)
- `action_path` as web deep-link fallback
- `metadata` without secrets / raw provider payloads

After mutation: honor `refresh_recommended`, `attention_still_relevant`, and HTTP **409** stale responses by re-fetching.

## Reject / request-changes gap

| Flow | Status |
|------|--------|
| Internal approve | Canonical — Workspace `approve_content` / `ContentService.approve` |
| Internal reject / request-changes | **No dedicated operator action** (`capabilities.internal_content_reject=false`) |
| Client approve / request-changes | Public review token — **not** operator mobile |

Do **not** invent status PATCH from mobile. Treat dedicated internal reject as a **Phase 2 backend gap** if product requires it.

## Authentication (native)

Current model:

- JWT access (`type=access`) + JWT refresh (`type=refresh`), HS256
- Refresh hash stored on `TenantUser.refresh_token_hash` (single active refresh per user)
- Logout clears hash (server-side revoke of that refresh)
- Bearer auth — no CSRF cookie dependency for native clients

**Client storage**

- Refresh/session material: iOS Keychain / Android Keystore (Expo SecureStore)
- Never store Meta / OpenAI / Telegram / provider secrets on device

**Biometrics (client-only)**

- Face ID / biometrics unlock local secure storage
- Does **not** replace API authentication
- Re-auth (password / refresh) for consequential actions after inactivity is recommended

**Known limitation (migration required for multi-device)**

One refresh hash per user → second device login revokes the first. Multi-device sessions + push device registry need schema approval (see below).

## System health (safe)

Exposed via `/mobile-control/system` (and home embed):

- overall / api / database / scheduler / ai_services / telegram_bot (abstract statuses)
- integration attention count
- uptime seconds
- backup: **`unavailable`** until a read-only bridge is approved

Not exposed: IPs, SSH, secrets, env, pool internals, revenue totals, Cloudflare tokens, backup paths.

## Backup status

Ops host command `ops/backup/china-smm-os-backup-status` is **not** tenant-API-safe.

Phase 1: `backup.status = unavailable`, `backup_status_live = false`.

Future: read-only JSON status file / privileged bridge — **no** restore / delete / download from mobile.

## Push architecture (design only — do not send)

```
domain event → notification policy → delivery provider → registered device token
```

**Categories**

| Level | Examples |
|-------|----------|
| CRITICAL | production health critical, backup failed/stale, vault failure, operator_review needing human |
| HIGH | content approval needing owner, publishing issue, integration disconnected |
| NORMAL | optional digests |

**Do not push:** transient timeouts, every scheduler tick, every successful publish.

**Provider recommendation:** **Expo Push Notifications** (with FCM/APNs under Expo) — best fit for Expo client; avoids maintaining dual native push stacks initially.

**Payload safety:** lock-screen text is generic (“China SMM OS needs your attention”, “2 approvals waiting”). Detail loads after app auth.

**Device registration:** requires DB migration — **not** created in Phase 1.

### Proposed schema (approval required)

```
MOBILE PUSH DEVICE MIGRATION REQUIRED

mobile_push_devices:
  id              UUID PK
  user_id         UUID NOT NULL → tenant_users
  tenant_id       UUID NOT NULL → tenants
  device_id       TEXT NOT NULL          -- stable app-install id
  platform        TEXT NOT NULL          -- ios|android
  push_token_hash TEXT NOT NULL          -- hash; raw token encrypted-at-rest if stored
  app_version     TEXT NULL
  created_at      TIMESTAMPTZ NOT NULL
  last_seen_at    TIMESTAMPTZ NOT NULL
  revoked_at      TIMESTAMPTZ NULL
  UNIQUE (user_id, device_id)
  INDEX (tenant_id, revoked_at)
  INDEX (push_token_hash) WHERE revoked_at IS NULL

Retention: revoke on logout; prune revoked > 90d.
Security: tenant-scoped registration; no cross-tenant fan-out; minimal push payload.
```

Optional later: `tenant_user_sessions` for multi-device refresh rotation (replacing single `refresh_token_hash`).

## Offline / idempotency

- Show `last_updated_at` / `generated_at`
- Never mark mutation success before HTTP success
- Disable double-submit while pending
- Safe to retry **reads**; do **not** blindly retry mutations
- On 409: refresh item / home and re-evaluate `actions[]`
- Server publish path uses internal idempotency keys; HTTP `Idempotency-Key` is not general yet

## Security threat model (practical)

| Threat | Safeguard |
|--------|-----------|
| Lost phone | Biometric gate + short access TTL + logout revoke refresh |
| Token theft | Refresh rotation + server hash revoke |
| MITM | TLS only; certificate pinning optional later |
| Notification leakage | Generic push copy |
| Cross-tenant abuse | JWT tenant + Workspace scope_select |
| Double-submit | UI disable + server eligibility / idempotent ack |
| Malicious deep link | Validate attention ids; never trust client eligibility |
| Compromised push token | Hash tokens; revoke; tenant-scoped send |

No MDM required for Phase 1 personal owner app.

## Compatibility

- Additive JSON fields only
- UI driven by `actions[]` + `capabilities`
- Stable reason codes / action ids
- `minimum_app_version` only if later forced

## Performance targets

Home/system: no provider calls; reuse Workspace collectors; bound urgent list.

| Clients | Expected behavior |
|---------|-------------------|
| 22 | Sub-second typical on warm DB |
| 50–200 | Still status-filtered actionable sets; watch pathological warn ≥5000 |
| 300 | Same; prefer summary + paged items for Approvals/Problems tabs |

## Technology recommendation

**React Native + Expo** (managed / Expo Router).

Rationale: shared TypeScript with web team, one iOS+Android codebase, Expo SecureStore + LocalAuthentication, Expo Push, OTA updates for JS, lower maintenance than bare RN / dual native / Flutter. PWA is insufficient for reliable background push + secure storage UX.

## Phase 2 mobile app milestone (first ship)

1. Expo app skeleton (auth login/refresh/logout, SecureStore, biometric unlock)
2. Tabs: Today / Approvals / Problems / System wired to mobile-control + Workspace
3. Action sheet driven by `actions[]` with confirmation tiers + `X-Client-Source: mobile`
4. Polling notifications unread badge (no push yet)
5. Offline banner + stale 409 handling
6. Do **not** enable push until device migration approved

## Production

Development only for Phase 1. No deploy, no production env changes, no Auto-Ack enablement, no real push.
