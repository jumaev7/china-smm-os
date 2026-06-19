"use client";

import { useEffect, useState } from "react";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { useAuth } from "@/lib/auth-store";
import { computeSessionAwareAuthReady } from "@/lib/session-sync";

export type DashboardWidgetScope = "core" | "shared" | "admin" | "adminHeavy" | "tenant";

/**
 * Gate dashboard widget queries by resolved auth state.
 * Tenant session takes precedence — admin widgets stay off for tenant users.
 */
export function useDashboardAuthGates() {
  const { isAuthenticated: isTenantAuthenticated, loading: tenantAuthLoading } = useAuth();
  const { isAuthenticated: isAdminAuthenticated, loading: adminAuthLoading } = useAdminAuth();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const authReady = mounted && computeSessionAwareAuthReady(tenantAuthLoading, adminAuthLoading);
  const hasSession = mounted && (isTenantAuthenticated || isAdminAuthenticated);

  const adminWidgetsEnabled = authReady && isAdminAuthenticated && !isTenantAuthenticated;
  const tenantWidgetsEnabled = authReady && isTenantAuthenticated;
  const sharedWidgetsEnabled = authReady && hasSession;
  /** Heavy admin orchestration widgets — skip for tenant dashboard to avoid slow 504 storms. */
  const adminHeavyWidgetsEnabled = adminWidgetsEnabled;
  const coreWidgetsEnabled = authReady;

  return {
    authReady,
    hasSession,
    isTenantAuthenticated,
    isAdminAuthenticated,
    adminWidgetsEnabled,
    adminHeavyWidgetsEnabled,
    tenantWidgetsEnabled,
    sharedWidgetsEnabled,
    coreWidgetsEnabled,
  };
}

export function isDashboardWidgetEnabled(
  scope: DashboardWidgetScope,
  gates: ReturnType<typeof useDashboardAuthGates>,
): boolean {
  switch (scope) {
    case "admin":
      return gates.adminWidgetsEnabled;
    case "adminHeavy":
      return gates.adminHeavyWidgetsEnabled;
    case "tenant":
      return gates.tenantWidgetsEnabled;
    case "shared":
      return gates.sharedWidgetsEnabled;
    case "core":
    default:
      return gates.coreWidgetsEnabled;
  }
}
