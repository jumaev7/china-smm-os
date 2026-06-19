"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { useAuth } from "@/lib/auth-store";
import {
  evaluateRouteAccess,
  getTenantRequiredRoles,
  requiresTenantAuth,
  resolveNavAudience,
} from "@/lib/route-permissions";
import {
  AUTH_HYDRATION_FAILSAFE_MS,
  computeSessionAwareAuthReady,
  forceAuthHydrationFinish,
  hasAnyStoredAuthToken,
  reconcileStaleActiveSession,
} from "@/lib/session-sync";

export function TenantAuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { loading: tenantLoading, isAuthenticated: isTenant, user, permissions, hasRole } = useAuth();
  const {
    loading: adminLoading,
    isAuthenticated: isAdmin,
    user: adminUser,
    permissions: adminPermissions,
  } = useAdminAuth();

  const [hydrationTimedOut, setHydrationTimedOut] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const authReady = mounted && computeSessionAwareAuthReady(tenantLoading, adminLoading);
  const effectiveAuthReady = mounted && (authReady || hydrationTimedOut);

  const audience = resolveNavAudience({
    authReady: effectiveAuthReady,
    isTenantAuthenticated: isTenant,
    isAdminAuthenticated: isAdmin,
  });

  const routeCtx = {
    authReady: effectiveAuthReady,
    isTenantAuthenticated: isTenant,
    isAdminAuthenticated: isAdmin,
    tenantRole: user?.role ?? null,
    tenantPermissions: permissions,
    adminRole: adminUser?.role ?? null,
    adminPermissions,
  };

  const access = evaluateRouteAccess(pathname, routeCtx);
  const protectedRoute = requiresTenantAuth(pathname);
  const requiredRoles = getTenantRequiredRoles(pathname);

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
    if (!effectiveAuthReady || audience === "admin") return;
    if (access.redirectTo) {
      router.replace(access.redirectTo);
      return;
    }
    if (
      protectedRoute &&
      isTenant &&
      requiredRoles &&
      user &&
      !hasRole(...requiredRoles)
    ) {
      router.replace("/dashboard");
    }
  }, [
    effectiveAuthReady,
    audience,
    access.redirectTo,
    protectedRoute,
    isTenant,
    requiredRoles,
    user,
    hasRole,
    router,
  ]);

  if (audience === "admin") {
    return <>{children}</>;
  }

  if (!effectiveAuthReady && protectedRoute) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-gray-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Checking session…
      </div>
    );
  }

  if (access.redirectTo) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-gray-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Redirecting…
      </div>
    );
  }

  if (protectedRoute && requiredRoles && user && !hasRole(...requiredRoles)) {
    return (
      <div className="mx-auto max-w-lg p-8 text-center">
        <h2 className="text-lg font-semibold text-gray-900">Access denied</h2>
        <p className="mt-2 text-sm text-gray-600">
          Your role ({user.role}) does not have access to this page.
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
