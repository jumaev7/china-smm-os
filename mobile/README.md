# China SMM OS — Mobile Operator App (Phase 2)

Read-only Expo operator client. Authenticates against the production China SMM OS
backend, renders mobile-control + workspace attention data, and **hard-blocks**
all consequential mutations.

## Placement

Located at `/mobile` (repo root sibling of `frontend/` and `backend/`).

**Why:** The repository is not an `apps/` monorepo. A top-level `mobile/` package
keeps Expo tooling, Metro, and `node_modules` isolated from the Next.js frontend
and Python backend builds. No existing build pipelines were restructured.

## Stack

- Expo (SDK 57) + React Native + TypeScript
- Expo Router (file-based navigation)
- TanStack Query (server state)
- `expo-secure-store` (refresh token)
- `expo-local-authentication` (local biometric lock)
- `fetch` HTTP transport

No Redux. No push. No EAS production signing in this phase.

## Architecture

```
mobile/
  app/           Expo Router screens (login, lock, tabs)
  api/           HTTP client, auth, reads, mutation stubs + guard
  auth/          AuthProvider, token memory, refresh single-flight, biometrics
  storage/       SecureStore session helpers
  components/    Attention cards, action renderer, offline banner
  hooks/         Queries, network, theme
  config/        env + MOBILE_MUTATIONS_ENABLED
  types/         Backend contract mirrors
  utils/         errors, logging scrub, deep-link allowlist
  __tests__/     Unit tests (logic-first)
```

## Setup

```bash
cd mobile
cp .env.example .env
# edit EXPO_PUBLIC_API_BASE_URL
npm install
npx expo start
```

Then open with Expo Go (Android/iOS) or an emulator/simulator.

### SecureStore / biometrics

`expo-secure-store` and `expo-local-authentication` work in Expo Go for Phase 2.
If a future native module requires a dev client:

```bash
npx expo run:android
# or
npx expo run:ios
```

## Environment

| Variable | Purpose |
|----------|---------|
| `EXPO_PUBLIC_API_BASE_URL` | Backend origin, e.g. `https://api.example.com` |

Public only. **Never** put `SECRET_KEY`, admin secrets, Meta/Telegram/Cloudflare
tokens, DB URLs, or R2 credentials in mobile config.

Production builds require HTTPS (enforced in the API client when not `__DEV__`).
Certificate pinning is optional future hardening — not required now.

## Authentication flow

1. Login screen → `POST /api/v1/auth/login` (email + password)
2. Access token kept **in memory**
3. Refresh token stored in **SecureStore**
4. Password never persisted or logged
5. Cold start: read refresh → `POST /api/v1/auth/refresh` → `GET /api/v1/auth/me`
6. Refresh failure → clear SecureStore → login
7. Logout → best-effort `POST /auth/logout` + clear local session

### Refresh logic

- Single in-flight refresh (`auth/refreshQueue.ts`)
- Concurrent 401s wait on the same promise (no stampede)
- Permanent refresh failure → session invalid → logout
- No blind mutation retries (mutations are disabled)

## Secure storage

| Key | Store | Contents |
|-----|-------|----------|
| `csmm.refresh_token` | SecureStore | Refresh JWT |
| `csmm.biometric_enabled` | SecureStore | `"1"` / `"0"` preference |

**Not stored:** password, access token, arbitrary tenant authorization overrides.

## Biometrics

- Optional local lock after ~60s background
- Toggle on Profile tab
- Does **not** authenticate to the backend
- If hardware/enrollment unavailable → soft-pass (no permanent lockout)

## Navigation

Bottom tabs: **Today · Approvals · Problems · System · Profile**

## Screens

| Tab | Source |
|-----|--------|
| Today | `GET /api/v1/mobile-control/home` |
| Approvals | `GET /api/v1/operator-workspace/items?category=content_internal_review` |
| Problems | Workspace items for publishing/integration/alert categories |
| System | `GET /api/v1/mobile-control/system` |

All requests send `X-Client-Source: mobile`.

If `backup.status=unavailable`, UI shows:
**“Backup status not available in mobile control plane”** (not a failure).

## Actions[] + mutation boundary

Backend `actions[]` are rendered with metadata (id, confirmation tier, external
side effect, requires confirmation). Controls are **disabled**.

```ts
// config/constants.ts
export const MOBILE_MUTATIONS_ENABLED = false as const;
```

`api/mutations.ts` calls `assertMutationsEnabled()` **before** any HTTP.
Tests prove approve / retry / acknowledge / resolve never call `fetch`.

## Offline / errors

- Offline banner + “Last updated …” + cached marker
- Pull-to-refresh + foreground invalidation (45s stale time, no aggressive polling)
- 401 → refresh → logout if needed
- 403 / 409 / 429 / 5xx / network mapped to safe copy (no raw provider payloads)

## Lifecycle security

- Background → optional biometric lock after threshold
- Sensitive cover on lock screen
- Access token memory-only
- Production logging scrubbed (no tokens / Authorization / passwords)

## Deep links

Internal route allowlist only. No action execution. No OAuth callbacks in Phase 2.

## Production API canary (manual)

1. Set `EXPO_PUBLIC_API_BASE_URL` to the production API origin (HTTPS)
2. `cd mobile && npm install && npx expo start`
3. Open Expo Go / emulator
4. Login manually with a real operator account (no saved credentials in repo)
5. Verify Today / Approvals / Problems / System load tenant-scoped data
6. Confirm every action shows “Available in next phase” and does nothing
7. Background ~60s → biometric lock (if enrolled)
8. Kill app → relaunch → session restores via refresh
9. Toggle offline / airplane → banner + cached indication
10. Logout → returns to login; SecureStore refresh cleared

## Manual acceptance checklist

- [ ] Expo Go / device connected
- [ ] API URL set
- [ ] Manual login works
- [ ] Face ID / biometric local unlock works (or soft-pass if unavailable)
- [ ] Today loads
- [ ] Approvals loads
- [ ] Problems loads
- [ ] System loads
- [ ] Offline indicator works
- [ ] Logout works
- [ ] Restart restores session through refresh
- [ ] All real actions visibly disabled
- [ ] No production business state changed

## Tests

```bash
cd mobile
npm test
```

Coverage includes login/refresh, SecureStore persistence, refresh stampede,
401 handling, mutation hard-block (no HTTP), logging scrub, deep-link allowlist,
biometric soft-pass contract, and display helpers.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Network error on login | `EXPO_PUBLIC_API_BASE_URL`, device can reach API, HTTPS in prod |
| 403 on home | User role must be owner/manager/operator |
| Session drops | Refresh token revoked; sign in again |
| Biometrics looping | Toggle off on Profile; enrollment changes soft-pass |
| Expo module missing | `npx expo install <pkg>` matching SDK |

## Future Phase 3 — enabling real actions safely

1. Keep server-side eligibility checks as source of truth
2. Flip `MOBILE_MUTATIONS_ENABLED` to `true` behind an explicit release flag
3. Wire `api/mutations.ts` → existing
   `POST /operator-workspace/items/{id}/actions/{action_id}` with
   `source: "mobile"` / `X-Client-Source: mobile`
4. Require confirmation_tier UX for medium/high + external_side_effect
5. Add integration tests that a successful approve hits HTTP **only** when enabled
6. Ship as a deliberate release — not a silent config change

## Push boundary (Phase 3+)

**Not in this phase:** Expo push tokens, FCM, APNs, device registration, DB migrations.

## Non-interference

This package is client-only. It does not modify Auto-Ack, Integration Health,
scheduler, production env, or backend services.

## Validation commands

```bash
cd mobile
npx tsc --noEmit
npm test
npx expo-doctor || true
npm audit --omit=dev || true
```
