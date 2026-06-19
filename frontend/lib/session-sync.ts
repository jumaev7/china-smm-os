/** Shared auth storage keys — kept here to avoid circular imports between auth stores. */
export const AUTH_TOKEN_KEY = "tenant_auth_token";
export const AUTH_REFRESH_KEY = "tenant_auth_refresh";
export const ADMIN_AUTH_TOKEN_KEY = "admin_auth_token";
export const ADMIN_AUTH_REFRESH_KEY = "admin_auth_refresh";

/** Cached user snapshots for faster header hydration (optional). */
export const TENANT_USER_KEY = "tenant_user";
export const ADMIN_USER_KEY = "admin_user";

/** Per-tab active session — avoids admin/tenant login in one tab clobbering the other. */
export const ACTIVE_SESSION_KEY = "china_smm_active_session";

/** Max time route guards wait before treating auth hydration as settled. */
export const AUTH_HYDRATION_FAILSAFE_MS = 5_000;

export const AUTH_HYDRATION_FORCE_FINISH = "china-smm:auth-hydration-force-finish";

export type ActiveSession = "tenant" | "admin";

function sessionStore(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage;
}

export function readActiveSession(): ActiveSession | null {
  const store = sessionStore();
  if (!store) return null;
  const value = store.getItem(ACTIVE_SESSION_KEY);
  return value === "tenant" || value === "admin" ? value : null;
}

export function setActiveSession(session: ActiveSession): void {
  const store = sessionStore();
  if (!store) return;
  store.setItem(ACTIVE_SESSION_KEY, session);
}

export function clearActiveSession(): void {
  const store = sessionStore();
  if (!store) return;
  store.removeItem(ACTIVE_SESSION_KEY);
}

export const TENANT_SESSION_CHANGED = "china-smm:tenant-session-changed";
export const ADMIN_SESSION_CHANGED = "china-smm:admin-session-changed";

/** Remove persisted admin credentials (does not update React state). */
export function clearAdminSessionStorage(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ADMIN_AUTH_TOKEN_KEY);
  localStorage.removeItem(ADMIN_AUTH_REFRESH_KEY);
  localStorage.removeItem(ADMIN_USER_KEY);
  if (readActiveSession() === "admin") {
    clearActiveSession();
  }
}

/** Remove persisted tenant credentials (does not update React state). */
export function clearTenantSessionStorage(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_REFRESH_KEY);
  localStorage.removeItem(TENANT_USER_KEY);
  if (readActiveSession() === "tenant") {
    clearActiveSession();
  }
}

/** Drop active-session marker when its backing token is missing in this tab. */
export function reconcileStaleActiveSession(): boolean {
  if (typeof window === "undefined") return false;
  const active = readActiveSession();
  if (!active) return false;

  const tenantToken = localStorage.getItem(AUTH_TOKEN_KEY);
  const adminToken = localStorage.getItem(ADMIN_AUTH_TOKEN_KEY);

  if (active === "tenant" && !tenantToken) {
    clearActiveSession();
    return true;
  }
  if (active === "admin" && !adminToken) {
    clearActiveSession();
    return true;
  }
  return false;
}

export function hasStoredTenantToken(): boolean {
  if (typeof window === "undefined") return false;
  return !!localStorage.getItem(AUTH_TOKEN_KEY);
}

export function hasStoredAdminToken(): boolean {
  if (typeof window === "undefined") return false;
  return !!localStorage.getItem(ADMIN_AUTH_TOKEN_KEY);
}

export function hasAnyStoredAuthToken(): boolean {
  if (typeof window === "undefined") return false;
  return hasStoredTenantToken() || hasStoredAdminToken();
}

export type AuthDebugSnapshot = {
  activeSession: ActiveSession | null;
  tenantToken: boolean;
  adminToken: boolean;
};

export function readAuthDebugSnapshot(): AuthDebugSnapshot {
  return {
    activeSession: readActiveSession(),
    tenantToken: hasStoredTenantToken(),
    adminToken: hasStoredAdminToken(),
  };
}

/**
 * Route guards only wait on the auth store that matches the active session (or
 * whichever store still has a stored token). Avoids blocking admin pages on a
 * stuck tenant hydration when activeSession=admin and vice versa.
 */
export function computeSessionAwareAuthReady(
  tenantLoading: boolean,
  adminLoading: boolean,
): boolean {
  const active = readActiveSession();
  if (active === "admin") return !adminLoading;
  if (active === "tenant") return !tenantLoading;

  const hasTenant = hasStoredTenantToken();
  const hasAdmin = hasStoredAdminToken();
  if (hasTenant && !hasAdmin) return !tenantLoading;
  if (hasAdmin && !hasTenant) return !adminLoading;
  if (!hasTenant && !hasAdmin) return !tenantLoading && !adminLoading;
  return !tenantLoading && !adminLoading;
}

/** Route guards call this when hydration exceeds AUTH_HYDRATION_FAILSAFE_MS. */
export function forceAuthHydrationFinish(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(AUTH_HYDRATION_FORCE_FINISH));
}

export function notifyTenantSessionChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(TENANT_SESSION_CHANGED));
}

export function notifyAdminSessionChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(ADMIN_SESSION_CHANGED));
}

export function writeTenantUserSnapshot(user: unknown): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TENANT_USER_KEY, JSON.stringify(user));
}

export function writeAdminUserSnapshot(user: unknown): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(ADMIN_USER_KEY, JSON.stringify(user));
}
