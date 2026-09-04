import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { AppState, type AppStateStatus } from 'react-native';

import { loginRequest, logoutRequest, meRequest, refreshRequest } from '@/api/auth';
import { configureApiClient } from '@/api/client';
import { promptBiometricUnlock } from '@/auth/biometrics';
import { runSingleFlightRefresh } from '@/auth/refreshQueue';
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from '@/auth/tokenMemory';
import { BIOMETRIC_LOCK_AFTER_MS } from '@/config/constants';
import {
  clearAllSecureSession,
  readRefreshToken,
  saveRefreshToken,
} from '@/storage/secureSession';
import type { AuthTenantSummary, AuthUser, SessionSnapshot } from '@/types/auth';
import { AppError } from '@/utils/errors';
import { safeLog } from '@/utils/logging';

type AuthStatus = 'bootstrapping' | 'unauthenticated' | 'authenticated' | 'locked';

interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  tenant: AuthTenantSummary | null;
  permissions: string[];
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  unlock: () => Promise<boolean>;
  isBootstrapping: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('bootstrapping');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [tenant, setTenant] = useState<AuthTenantSummary | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const backgroundedAt = useRef<number | null>(null);
  const lockedRef = useRef(false);

  const applySession = useCallback((snap: SessionSnapshot) => {
    setUser(snap.user);
    setTenant(snap.tenant);
    setPermissions(snap.permissions ?? snap.user.permissions ?? []);
  }, []);

  const clearSessionLocal = useCallback(async () => {
    clearAccessToken();
    await clearAllSecureSession();
    setUser(null);
    setTenant(null);
    setPermissions([]);
    lockedRef.current = false;
    setStatus('unauthenticated');
  }, []);

  const refreshAccessToken = useCallback(async (): Promise<string | null> => {
    return runSingleFlightRefresh(async () => {
      const stored = await readRefreshToken();
      if (!stored) {
        return null;
      }
      try {
        const res = await refreshRequest(stored);
        setAccessToken(res.access_token);
        if (res.refresh_token) {
          await saveRefreshToken(res.refresh_token);
        }
        return res.access_token;
      } catch (err) {
        safeLog('warn', 'refresh failed', {
          kind: err instanceof AppError ? err.kind : 'unknown',
        });
        return null;
      }
    });
  }, []);

  useEffect(() => {
    configureApiClient({
      getAccessToken,
      refreshAccessToken,
      onSessionInvalid: clearSessionLocal,
    });
  }, [refreshAccessToken, clearSessionLocal]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const stored = await readRefreshToken();
        if (!stored) {
          if (!cancelled) setStatus('unauthenticated');
          return;
        }
        const token = await refreshAccessToken();
        if (!token) {
          await clearSessionLocal();
          return;
        }
        const me = await meRequest(token);
        if (cancelled) return;
        applySession({
          user: me.user,
          tenant: me.tenant,
          permissions: me.permissions,
        });
        // Soft biometric gate on cold start when preference + hardware allow.
        const bio = await promptBiometricUnlock('Unlock operator session');
        if (cancelled) return;
        if (!bio.success) {
          lockedRef.current = true;
          setStatus('locked');
          return;
        }
        setStatus('authenticated');
      } catch (err) {
        safeLog('warn', 'bootstrap failed', {
          kind: err instanceof AppError ? err.kind : 'unknown',
        });
        await clearSessionLocal();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [applySession, clearSessionLocal, refreshAccessToken]);

  useEffect(() => {
    const onChange = async (next: AppStateStatus) => {
      if (next === 'background' || next === 'inactive') {
        backgroundedAt.current = Date.now();
        return;
      }
      if (next !== 'active') return;
      if (status !== 'authenticated' && status !== 'locked') return;
      const leftAt = backgroundedAt.current;
      backgroundedAt.current = null;
      if (leftAt == null) return;
      if (Date.now() - leftAt < BIOMETRIC_LOCK_AFTER_MS) return;
      lockedRef.current = true;
      setStatus('locked');
      const bio = await promptBiometricUnlock('Unlock China SMM Operator');
      if (bio.success) {
        lockedRef.current = false;
        setStatus('authenticated');
      }
    };

    const sub = AppState.addEventListener('change', onChange);
    return () => sub.remove();
  }, [status]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await loginRequest(email, password);
      // Password must never be retained.
      setAccessToken(res.access_token);
      await saveRefreshToken(res.refresh_token);
      applySession({
        user: res.user,
        tenant: res.tenant,
        permissions: res.user.permissions ?? [],
      });
      lockedRef.current = false;
      setStatus('authenticated');
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    try {
      if (getAccessToken()) {
        await logoutRequest();
      }
    } catch {
      // Best-effort server logout; always clear local.
    }
    await clearSessionLocal();
  }, [clearSessionLocal]);

  const unlock = useCallback(async () => {
    const bio = await promptBiometricUnlock('Unlock China SMM Operator');
    if (bio.success) {
      lockedRef.current = false;
      setStatus('authenticated');
      return true;
    }
    return false;
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      tenant,
      permissions,
      login,
      logout,
      unlock,
      isBootstrapping: status === 'bootstrapping',
    }),
    [status, user, tenant, permissions, login, logout, unlock],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return ctx;
}
