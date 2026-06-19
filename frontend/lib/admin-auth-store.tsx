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
import { adminAuthApi, type AdminAuthMeResponse, type AdminUser, type AdminRole } from "@/lib/api";
import { PLATFORM_CONSOLE_PATHS } from "@/lib/route-permissions";
import {
  ADMIN_AUTH_REFRESH_KEY,
  ADMIN_AUTH_TOKEN_KEY,
  ADMIN_SESSION_CHANGED,
  ADMIN_USER_KEY,
  AUTH_HYDRATION_FAILSAFE_MS,
  AUTH_HYDRATION_FORCE_FINISH,
  AUTH_TOKEN_KEY,
  clearActiveSession,
  notifyAdminSessionChanged,
  notifyTenantSessionChanged,
  readActiveSession,
  reconcileStaleActiveSession,
  setActiveSession,
  TENANT_SESSION_CHANGED,
  writeAdminUserSnapshot,
} from "@/lib/session-sync";

const HYDRATION_TIMEOUT_MS = AUTH_HYDRATION_FAILSAFE_MS;

export { ADMIN_AUTH_TOKEN_KEY, ADMIN_AUTH_REFRESH_KEY };

/** Platform console routes in the (admin) layout — not the full dashboard permission map. */
export const ADMIN_PROTECTED_PREFIXES = PLATFORM_CONSOLE_PATHS;

type AdminAuthContextValue = {
  user: AdminUser | null;
  permissions: string[];
  loading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
  hasRole: (...roles: AdminRole[]) => boolean;
  hasPermission: (permission: string) => boolean;
};

const AdminAuthContext = createContext<AdminAuthContextValue | null>(null);

function readStoredAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ADMIN_AUTH_TOKEN_KEY);
}

export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AdminUser | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const clearSession = useCallback(() => {
    localStorage.removeItem(ADMIN_AUTH_TOKEN_KEY);
    localStorage.removeItem(ADMIN_AUTH_REFRESH_KEY);
    localStorage.removeItem(ADMIN_USER_KEY);
    if (readActiveSession() === "admin") {
      clearActiveSession();
    }
    setUser(null);
    setPermissions([]);
    notifyAdminSessionChanged();
  }, []);

  const applyMe = useCallback((data: AdminAuthMeResponse) => {
    setUser(data.user);
    setPermissions(data.permissions ?? data.user.permissions ?? []);
    writeAdminUserSnapshot(data.user);
  }, []);

  const refreshMe = useCallback(async () => {
    const token = readStoredAdminToken();
    if (!token) {
      clearSession();
      return;
    }
    try {
      const { data } = await adminAuthApi.me();
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
    const token = readStoredAdminToken();

    if (!token) {
      setUser(null);
      setPermissions([]);
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
      const token = readStoredAdminToken();

      if (!token) {
        if (alive) {
          setUser(null);
          setPermissions([]);
          finishHydration();
        }
        return;
      }

      const active = readActiveSession();
      if (active === "tenant" && localStorage.getItem(AUTH_TOKEN_KEY)) {
        if (alive) {
          setUser(null);
          setPermissions([]);
          finishHydration();
        }
        return;
      }

      try {
        const { data } = await adminAuthApi.me();
        if (alive) {
          applyMe(data);
          if (!readActiveSession()) {
            setActiveSession("admin");
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
      if (!readStoredAdminToken()) {
        setUser(null);
        setPermissions([]);
        setLoading(false);
      }
    };
    const forceFinish = () => {
      finishHydration();
    };
    window.addEventListener(TENANT_SESSION_CHANGED, syncFromStorage);
    window.addEventListener(ADMIN_SESSION_CHANGED, syncFromStorage);
    window.addEventListener(AUTH_HYDRATION_FORCE_FINISH, forceFinish);
    return () => {
      window.removeEventListener(TENANT_SESSION_CHANGED, syncFromStorage);
      window.removeEventListener(ADMIN_SESSION_CHANGED, syncFromStorage);
      window.removeEventListener(AUTH_HYDRATION_FORCE_FINISH, forceFinish);
    };
  }, [finishHydration]);

  const login = useCallback(async (email: string, password: string) => {
    const { data } = await adminAuthApi.login({ email, password });
    localStorage.setItem(ADMIN_AUTH_TOKEN_KEY, data.access_token);
    localStorage.setItem(ADMIN_AUTH_REFRESH_KEY, data.refresh_token);
    setActiveSession("admin");
    setUser(data.user);
    setPermissions(data.user.permissions ?? []);
    writeAdminUserSnapshot(data.user);
    notifyAdminSessionChanged();
  }, []);

  const logout = useCallback(async () => {
    try {
      if (readStoredAdminToken()) await adminAuthApi.logout();
    } catch {
      // ignore
    } finally {
      clearSession();
      router.push("/admin-login");
    }
  }, [clearSession, router]);

  const hasRole = useCallback(
    (...roles: AdminRole[]) => {
      if (!user) return false;
      if (user.role === "super_admin") return true;
      return roles.includes(user.role);
    },
    [user],
  );

  const hasPermission = useCallback(
    (permission: string) => {
      if (permissions.includes("platform.full")) return true;
      return permissions.includes(permission);
    },
    [permissions],
  );

  const value = useMemo(
    () => ({
      user,
      permissions,
      loading,
      isAuthenticated: !!readStoredAdminToken(),
      login,
      logout,
      refreshMe,
      hasRole,
      hasPermission,
    }),
    [user, permissions, loading, login, logout, refreshMe, hasRole, hasPermission],
  );

  return <AdminAuthContext.Provider value={value}>{children}</AdminAuthContext.Provider>;
}

export function useAdminAuth() {
  const ctx = useContext(AdminAuthContext);
  if (!ctx) throw new Error("useAdminAuth must be used within AdminAuthProvider");
  return ctx;
}

export function isAdminProtectedPath(pathname: string): boolean {
  return ADMIN_PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
