"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { authApi, type AuthMeResponse, type AuthUser, type TenantUserRole } from "@/lib/api";
import {
  TENANT_BUSINESS_PATHS,
  TENANT_ROUTE_ROLE_REQUIREMENTS,
} from "@/lib/route-permissions";
import {
  cleanupDocumentInteractionBlockers,
  scheduleDocumentInteractionCleanup,
} from "@/lib/dom-cleanup";
import {
  ADMIN_AUTH_TOKEN_KEY,
  ADMIN_SESSION_CHANGED,
  AUTH_HYDRATION_FAILSAFE_MS,
  AUTH_HYDRATION_FORCE_FINISH,
  AUTH_REFRESH_KEY,
  AUTH_TOKEN_KEY,
  clearActiveSession,
  notifyTenantSessionChanged,
  readActiveSession,
  reconcileStaleActiveSession,
  setActiveSession,
  TENANT_SESSION_CHANGED,
  TENANT_USER_KEY,
  writeTenantUserSnapshot,
} from "@/lib/session-sync";

const HYDRATION_TIMEOUT_MS = AUTH_HYDRATION_FAILSAFE_MS;

export { AUTH_TOKEN_KEY, AUTH_REFRESH_KEY };

export const TENANT_PROTECTED_PREFIXES = TENANT_BUSINESS_PATHS;

export const ROUTE_ROLE_REQUIREMENTS = TENANT_ROUTE_ROLE_REQUIREMENTS;

type AuthContextValue = {
  user: AuthUser | null;
  tenantName: string | null;
  permissions: string[];
  loading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
  setSession: (accessToken: string, refreshToken: string) => void;
  clearSession: () => void;
  hasRole: (...roles: TenantUserRole[]) => boolean;
  hasPermission: (permission: string) => boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

function clearTenantState(
  setUser: (v: AuthUser | null) => void,
  setTenantName: (v: string | null) => void,
  setPermissions: (v: string[]) => void,
) {
  setUser(null);
  setTenantName(null);
  setPermissions([]);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [tenantName, setTenantName] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const clearSession = useCallback(() => {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_REFRESH_KEY);
    localStorage.removeItem(TENANT_USER_KEY);
    if (readActiveSession() === "tenant") {
      clearActiveSession();
    }
    clearTenantState(setUser, setTenantName, setPermissions);
    notifyTenantSessionChanged();
  }, []);

  const setSession = useCallback((accessToken: string, refreshToken: string) => {
    localStorage.setItem(AUTH_TOKEN_KEY, accessToken);
    localStorage.setItem(AUTH_REFRESH_KEY, refreshToken);
  }, []);

  const applyMe = useCallback((data: AuthMeResponse) => {
    setUser(data.user);
    setTenantName(data.tenant.company_name);
    setPermissions(data.permissions ?? data.user.permissions ?? []);
    writeTenantUserSnapshot({ user: data.user, tenant: data.tenant });
  }, []);

  const refreshMe = useCallback(async () => {
    const token = readStoredToken();
    if (!token) {
      clearSession();
      return;
    }
    try {
      const { data } = await authApi.me();
      applyMe(data);
    } catch {
      clearSession();
    }
  }, [applyMe, clearSession]);

  const finishHydration = useCallback(() => {
    setLoading(false);
  }, []);

  useLayoutEffect(() => {
    reconcileStaleActiveSession();
    const token = readStoredToken();

    if (!token) {
      clearTenantState(setUser, setTenantName, setPermissions);
      finishHydration();
      return;
    }

    finishHydration();
  }, [finishHydration]);

  useEffect(() => {
    let alive = true;

    const safetyTimer = window.setTimeout(() => {
      if (!alive) return;
      finishHydration();
    }, HYDRATION_TIMEOUT_MS);

    (async () => {
      reconcileStaleActiveSession();
      const token = readStoredToken();

      if (!token) {
        if (alive) {
          clearTenantState(setUser, setTenantName, setPermissions);
          finishHydration();
        }
        return;
      }

      const active = readActiveSession();
      if (active === "admin" && localStorage.getItem(ADMIN_AUTH_TOKEN_KEY)) {
        if (alive) {
          clearTenantState(setUser, setTenantName, setPermissions);
          finishHydration();
        }
        return;
      }

      try {
        const { data } = await authApi.me();
        if (alive) {
          applyMe(data);
          if (!readActiveSession()) {
            setActiveSession("tenant");
          }
        }
      } catch {
        if (alive) clearSession();
      } finally {
        if (alive) finishHydration();
      }
    })();

    return () => {
      alive = false;
      window.clearTimeout(safetyTimer);
    };
  }, [applyMe, clearSession, finishHydration]);

  useEffect(() => {
    const syncFromStorage = () => {
      reconcileStaleActiveSession();
      if (!readStoredToken()) {
        clearTenantState(setUser, setTenantName, setPermissions);
        setLoading(false);
      }
    };
    const forceFinish = () => {
      finishHydration();
    };
    window.addEventListener(ADMIN_SESSION_CHANGED, syncFromStorage);
    window.addEventListener(TENANT_SESSION_CHANGED, syncFromStorage);
    window.addEventListener(AUTH_HYDRATION_FORCE_FINISH, forceFinish);
    return () => {
      window.removeEventListener(ADMIN_SESSION_CHANGED, syncFromStorage);
      window.removeEventListener(TENANT_SESSION_CHANGED, syncFromStorage);
      window.removeEventListener(AUTH_HYDRATION_FORCE_FINISH, forceFinish);
    };
  }, [finishHydration]);

  const login = useCallback(
    async (email: string, password: string) => {
      const { data } = await authApi.login({ email, password });
      setSession(data.access_token, data.refresh_token);
      setActiveSession("tenant");
      setUser(data.user);
      setTenantName(data.tenant.company_name);
      setPermissions(data.user.permissions ?? []);
      writeTenantUserSnapshot({ user: data.user, tenant: data.tenant });
      notifyTenantSessionChanged();
      cleanupDocumentInteractionBlockers();
      scheduleDocumentInteractionCleanup();
    },
    [setSession],
  );

  const logout = useCallback(async () => {
    try {
      if (readStoredToken()) await authApi.logout();
    } catch {
      // ignore logout errors
    } finally {
      clearSession();
      router.push("/login");
    }
  }, [clearSession, router]);

  const hasRole = useCallback(
    (...roles: TenantUserRole[]) => {
      if (!user) return false;
      if (user.role === "owner") return true;
      return roles.includes(user.role);
    },
    [user],
  );

  const hasPermission = useCallback(
    (permission: string) => {
      if (permissions.includes("tenant.full")) return true;
      return permissions.includes(permission);
    },
    [permissions],
  );

  const value = useMemo(
    () => ({
      user,
      tenantName,
      permissions,
      loading,
      isAuthenticated: !!user && !!readStoredToken(),
      login,
      logout,
      refreshMe,
      setSession,
      clearSession,
      hasRole,
      hasPermission,
    }),
    [
      user,
      tenantName,
      permissions,
      loading,
      login,
      logout,
      refreshMe,
      setSession,
      clearSession,
      hasRole,
      hasPermission,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function isTenantProtectedPath(pathname: string): boolean {
  return TENANT_PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export function getRequiredRoles(pathname: string): TenantUserRole[] | null {
  for (const [route, roles] of Object.entries(ROUTE_ROLE_REQUIREMENTS)) {
    if (pathname === route || pathname.startsWith(`${route}/`)) return roles;
  }
  return null;
}
