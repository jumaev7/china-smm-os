"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { isAdminProtectedPath, useAdminAuth } from "@/lib/admin-auth-store";
import { hasActiveAdminSession } from "@/lib/route-permissions";
import {
  forceAuthHydrationFinish,
  hasStoredAdminToken,
} from "@/lib/session-sync";

const LOADING_STUCK_FALLBACK_MS = 3_000;

export function AdminAuthGuard({
  children,
  requireAdmin,
}: {
  children: React.ReactNode;
  /** When true, always require admin JWT (page-level guard). */
  requireAdmin?: boolean;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { loading, isAuthenticated } = useAdminAuth();
  const [loadingBypass, setLoadingBypass] = useState(false);
  const [mounted, setMounted] = useState(false);

  const protectedRoute = requireAdmin === true || isAdminProtectedPath(pathname);
  const authSettled = mounted && (!loading || loadingBypass);
  const hasAdminSession = mounted && (isAuthenticated || hasActiveAdminSession() || hasStoredAdminToken());

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!loading) {
      setLoadingBypass(false);
      return;
    }
    const timer = window.setTimeout(() => {
      forceAuthHydrationFinish();
      setLoadingBypass(true);
    }, LOADING_STUCK_FALLBACK_MS);
    return () => window.clearTimeout(timer);
  }, [loading]);

  useEffect(() => {
    if (!authSettled) return;
    if (!protectedRoute) return;
    if (!hasAdminSession) {
      router.replace(`/admin-login?next=${encodeURIComponent(pathname)}`);
    }
  }, [authSettled, protectedRoute, hasAdminSession, pathname, router]);

  if (!authSettled && protectedRoute) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-gray-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Checking admin session…
      </div>
    );
  }

  if (protectedRoute && !hasAdminSession) {
    return (
      <div className="mx-auto max-w-lg p-8 text-center">
        <h2 className="text-lg font-semibold text-gray-900">Access denied</h2>
        <p className="mt-2 text-sm text-gray-600">
          Admin session required. Sign in at admin login to continue.
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
