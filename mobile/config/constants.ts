/**
 * Phase 3B mobile mutation gates (fail closed).
 *
 * Hierarchy for execution (`assertActionAllowed` / `isMobileMutationAllowed`):
 * 1. MOBILE_MUTATIONS_KILL_SWITCH === true → block ALL mutations (including allowlist)
 * 2. action_id not in MOBILE_ALLOWED_MUTATIONS → block
 * 3. otherwise → allow that action only (backend actions[] + server checks still apply)
 *
 * MOBILE_MUTATIONS_UNLOCK_ALL is a legacy "enable every mutation helper" switch.
 * It must stay false — flipping it must NOT be required for allowlisted actions,
 * and must NOT unlock retry/resolve/etc. Enablement is MOBILE_ALLOWED_MUTATIONS only.
 */

/**
 * Emergency kill switch. When true, blocks ALL mobile mutations including
 * the Phase 3 allowlist. Keep false unless an incident requires it.
 */
export const MOBILE_MUTATIONS_KILL_SWITCH = false as const;

/**
 * Legacy unlock-all flag. When true, would mean "generic mutation suite on".
 * Remains false — do NOT flip to unlock retry/resolve/etc.
 * Phase 3 enablement is MOBILE_ALLOWED_MUTATIONS only.
 */
export const MOBILE_MUTATIONS_UNLOCK_ALL = false as const;

/**
 * @deprecated Alias of MOBILE_MUTATIONS_UNLOCK_ALL.
 * Name historically read as "mutations on/off"; that was misleading once
 * Phase 3A allowlisted approve_content while this stayed false.
 * Prefer MOBILE_MUTATIONS_UNLOCK_ALL or MOBILE_ALLOWED_MUTATIONS.
 */
export const MOBILE_MUTATIONS_ENABLED = MOBILE_MUTATIONS_UNLOCK_ALL;

/**
 * Phase 3B per-action allowlist (fail closed).
 * Only listed action_ids may execute; everything else stays blocked.
 */
export const MOBILE_ALLOWED_MUTATIONS = [
  'approve_content',
  'acknowledge_alert',
] as const;

export type MobileAllowedMutation = (typeof MOBILE_ALLOWED_MUTATIONS)[number];

/** True when approve_content is allowed under kill switch + allowlist. */
export const MOBILE_APPROVE_CONTENT_ENABLED =
  !MOBILE_MUTATIONS_KILL_SWITCH &&
  (MOBILE_ALLOWED_MUTATIONS as readonly string[]).includes('approve_content');

/** True when acknowledge_alert is allowed under kill switch + allowlist. */
export const MOBILE_ACKNOWLEDGE_ALERT_ENABLED =
  !MOBILE_MUTATIONS_KILL_SWITCH &&
  (MOBILE_ALLOWED_MUTATIONS as readonly string[]).includes('acknowledge_alert');

/** Client source header for backend audit differentiation. */
export const CLIENT_SOURCE = 'mobile' as const;

/** Access token treated as expired this many ms before actual expiry when known. */
export const ACCESS_TOKEN_SKEW_MS = 30_000;

/** Biometric re-lock after app has been backgrounded this long. */
export const BIOMETRIC_LOCK_AFTER_MS = 60_000;

/** TanStack Query stale time for operator reads. */
export const QUERY_STALE_TIME_MS = 45_000;

/** HTTP request timeout. */
export const REQUEST_TIMEOUT_MS = 25_000;

/** Allowed internal deep-link route prefixes (no arbitrary URLs / no action exec). */
export const INTERNAL_ROUTE_ALLOWLIST = [
  '/(tabs)/today',
  '/(tabs)/approvals',
  '/(tabs)/problems',
  '/(tabs)/system',
  '/(tabs)/settings',
  '/login',
] as const;

export const SECURE_STORE_KEYS = {
  refreshToken: 'csmm.refresh_token',
  biometricEnabled: 'csmm.biometric_enabled',
} as const;

export const MUTATION_BLOCKED_MESSAGE =
  'This action is not enabled on mobile yet';

export const MUTATION_KILL_SWITCH_MESSAGE =
  'Mobile mutations temporarily disabled';
