"use client";

import { useEffect, useState } from "react";
import { LogOut, Shield } from "lucide-react";
import Link from "next/link";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { useAuth } from "@/lib/auth-store";
import { resolveNavAudience } from "@/lib/nav-access";
import { computeSessionAwareAuthReady } from "@/lib/session-sync";

const TENANT_ROLE_LABELS: Record<string, string> = {
  owner: "Owner",
  manager: "Manager",
  sales: "Sales",
  operator: "Operator",
  viewer: "Viewer",
};

const ADMIN_ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  platform_admin: "Platform Admin",
  support_admin: "Support Admin",
  auditor: "Auditor",
};

export function UserMenu() {
  const [mounted, setMounted] = useState(false);
  const {
    user: tenantUser,
    tenantName,
    logout: tenantLogout,
    isAuthenticated: isTenant,
    loading: tenantLoading,
  } = useAuth();
  const {
    user: adminUser,
    logout: adminLogout,
    isAuthenticated: isAdmin,
    loading: adminLoading,
  } = useAdminAuth();

  useEffect(() => {
    setMounted(true);
  }, []);

  const authReady = mounted && computeSessionAwareAuthReady(tenantLoading, adminLoading);
  const audience = resolveNavAudience({
    authReady,
    isTenantAuthenticated: isTenant,
    isAdminAuthenticated: isAdmin,
  });

  if (!authReady) {
    return null;
  }

  if (audience === "admin") {
    return (
      <div className="flex items-center gap-3">
        {adminUser ? (
          <div className="hidden sm:block text-right">
            <div className="text-sm font-medium text-gray-900 leading-tight">{adminUser.email}</div>
            <div className="flex items-center justify-end gap-1 text-xs text-gray-500">
              <Shield size={11} />
              <span>{ADMIN_ROLE_LABELS[adminUser.role] ?? adminUser.role}</span>
              <span className="text-gray-400">· Platform Admin</span>
            </div>
          </div>
        ) : null}
        <Link
          href="/admin-users"
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Platform Admin
        </Link>
        <button
          type="button"
          onClick={() => adminLogout()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <LogOut size={14} />
          Logout
        </button>
      </div>
    );
  }

  if (audience === "tenant" && tenantUser) {
    return (
      <div className="flex items-center gap-3">
        <div className="hidden sm:block text-right">
          <div className="text-sm font-medium text-gray-900 leading-tight">{tenantUser.email}</div>
          <div className="flex items-center justify-end gap-1 text-xs text-gray-500">
            <Shield size={11} />
            <span>{TENANT_ROLE_LABELS[tenantUser.role] ?? tenantUser.role}</span>
            {tenantName ? <span className="text-gray-400">· {tenantName}</span> : null}
          </div>
        </div>
        <button
          type="button"
          onClick={() => tenantLogout()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <LogOut size={14} />
          Logout
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Link
        href="/login"
        className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        Tenant sign in
      </Link>
      <Link
        href="/admin-login"
        className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        Admin sign in
      </Link>
    </div>
  );
}
