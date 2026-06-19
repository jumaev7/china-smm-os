"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { useAuth } from "@/lib/auth-store";
import { evaluateRouteAccess, hasActiveTenantSession } from "@/lib/route-permissions";
import {
  AUTH_HYDRATION_FAILSAFE_MS,
  forceAuthHydrationFinish,
  hasAnyStoredAuthToken,
  readAuthDebugSnapshot,
  reconcileStaleActiveSession,
} from "@/lib/session-sync";

const LOADING_STUCK_FALLBACK_MS = 3_000;

type AccessPhase = "loading" | "allowed" | "denied";

function resolveAccessPhase(allowed: boolean, reason: string | undefined): AccessPhase {
  if (allowed) return "allowed";
  if (reason === "loading") return "loading";
  return "denied";
}

/**
 * Enforces route-permissions for dashboard pages (platform/pilot/admin-only,
 * tenant business routes, executive copilot dual access).
 */
export function DashboardRouteGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { loading: tenantLoading, isAuthenticated: isTenant, user, permissions } = useAuth();
  const {
    loading: adminLoading,
    isAuthenticated: isAdmin,
    user: adminUser,
    permissions: adminPermissions,
  } = useAdminAuth();

  const [hydrationTimedOut, setHydrationTimedOut] = useState(false);
  const [loadingBypass, setLoadingBypass] = useState(false);
  const [mounted, setMounted] = useState(false);
  const prevPhaseRef = useRef<AccessPhase | null>(null);

  const debug = mounted
    ? readAuthDebugSnapshot()
    : { activeSession: null, tenantToken: false, adminToken: false };
  const isAdminSession = debug.activeSession === "admin" && debug.adminToken;

  const authReady = mounted && (
    isAdminSession
      ? !adminLoading
      : debug.activeSession === "tenant"
        ? !tenantLoading
        : !tenantLoading && !adminLoading
  );

  const routeAuthReady = mounted && (
    (isAdminSession && debug.adminToken) || authReady || hydrationTimedOut || loadingBypass
  );

  const access = evaluateRouteAccess(pathname, {
    authReady: routeAuthReady,
    isTenantAuthenticated: isTenant,
    isAdminAuthenticated: isAdmin,
    tenantRole: user?.role ?? null,
    tenantPermissions: permissions,
    adminRole: adminUser?.role ?? null,
    adminPermissions,
  });

  const accessPhase = resolveAccessPhase(access.allowed, access.reason);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const prev = prevPhaseRef.current;
    if (prev === "loading" && accessPhase === "allowed") {
      console.info("[route-guard] loading -> allowed", { pathname, activeSession: debug.activeSession });
    } else if (prev === "loading" && accessPhase === "denied") {
      console.info("[route-guard] loading -> denied", {
        pathname,
        activeSession: debug.activeSession,
        reason: access.reason,
        redirectTo: access.redirectTo,
      });
    }
    prevPhaseRef.current = accessPhase;
  }, [accessPhase, pathname, debug.activeSession, access.reason, access.redirectTo]);

  useEffect(() => {
    if (access.reason !== "loading") {
      setLoadingBypass(false);
      return;
    }

    const timer = window.setTimeout(() => {
      forceAuthHydrationFinish();
      setLoadingBypass(true);
    }, LOADING_STUCK_FALLBACK_MS);

    return () => window.clearTimeout(timer);
  }, [access.reason]);

  useEffect(() => {
    if (authReady) {
      setHydrationTimedOut(false);
      return;
    }

    const timer = window.setTimeout(() => {
      reconcileStaleActiveSession();
      forceAuthHydrationFinish();
      setHydrationTimedOut(true);

      if (!hasAnyStoredAuthToken()) {
        router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      }
    }, AUTH_HYDRATION_FAILSAFE_MS);

    return () => window.clearTimeout(timer);
  }, [authReady, pathname, router]);

  useEffect(() => {
    if (!access.redirectTo) return;
    // Avoid login redirect loops when a tenant session is already present.
    if (
      access.redirectTo.startsWith("/login") &&
      (isTenant || hasActiveTenantSession())
    ) {
      router.replace("/dashboard");
      return;
    }
    router.replace(access.redirectTo);
  }, [access.redirectTo, isTenant, router]);

  useEffect(() => {
    if (!routeAuthReady) return;
    if (access.redirectTo) return;
    if (isTenant || isAdmin || isAdminSession) return;
    if (hasAnyStoredAuthToken()) return;

    reconcileStaleActiveSession();
    router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [routeAuthReady, access.redirectTo, isTenant, isAdmin, isAdminSession, pathname, router]);

  if (!access.allowed) {
    if (access.reason === "loading") {
      return (
        <div className="flex min-h-[40vh] items-center justify-center text-gray-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Checking access…
        </div>
      );
    }

    if (access.reason === "role_denied") {
      return (
        <div className="mx-auto max-w-lg p-8 text-center">
          <h2 className="text-lg font-semibold text-gray-900">Access denied</h2>
          <p className="mt-2 text-sm text-gray-600">
            Your role does not have access to this page.
            {adminUser?.role ? ` (role: ${adminUser.role})` : user?.role ? ` (role: ${user.role})` : ""}
          </p>
        </div>
      );
    }

    return (
      <div className="flex min-h-[40vh] items-center justify-center text-gray-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Redirecting…
      </div>
    );
  }

  return <>{children}</>;
}
