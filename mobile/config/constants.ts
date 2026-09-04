/**
 * Phase 2 fail-closed mutation gate.
 * Must remain false until Phase 3 explicitly enables operator actions.
 */
export const MOBILE_MUTATIONS_ENABLED = false as const;

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
  'Mobile mutations disabled in Phase 2';
