"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Building2 } from "lucide-react";
import { adminAuthApi, pilotOnboardingApi, normalizeList } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-800",
  pending: "bg-amber-100 text-amber-800",
  suspended: "bg-red-100 text-red-800",
  archived: "bg-gray-100 text-gray-700",
};

type PlatformTenant = {
  id: string;
  company_name: string;
  status: string;
  plan: string;
  created_at?: string;
};

export default function TenantsPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <TenantsPageContent />
    </AdminAuthGuard>
  );
}

function TenantsPageContent() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: listData, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-platform-tenants"],
    queryFn: () => adminAuthApi.platformTenants({ limit: 200 }).then((r) => r.data),
  });

  const { data: pilotOnboardingApps } = useQuery({
    queryKey: ["pilot-onboarding-applications-tenants"],
    queryFn: () => pilotOnboardingApi.applications({ limit: 200 }).then((r) => r.data),
  });

  const items = normalizeList(listData?.items ?? listData) as PlatformTenant[];
  const selected = items.find((t) => t.id === selectedId);
  const tenantOnboarding = pilotOnboardingApps?.items.find((a) => a.tenant_id === selectedId);

  if (isLoading) return <LoadingState message="Loading tenants…" />;
  if (isError) {
    return <ErrorState error={error} onRetry={() => refetch()} />;
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Building2 size={22} className="text-indigo-600" />
            Platform Tenants
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            All factory tenants — create new tenants via the factory partner workflow
          </p>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <section className="space-y-3">
          <p className="text-sm font-semibold text-gray-900">Tenant list</p>
          {items.length === 0 ? (
            <EmptyState
              title="No tenants yet"
              description="Approve a factory partner application or seed demo data to create the first tenant."
            />
          ) : (
            <ul className="card divide-y divide-gray-100">
              {items.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(t.id)}
                    className={cn(
                      "w-full text-left px-4 py-3 hover:bg-gray-50 transition",
                      selectedId === t.id && "bg-brand-50",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-gray-900">{t.company_name}</span>
                      <span
                        className={cn(
                          "text-xs px-2 py-0.5 rounded-full",
                          STATUS_STYLES[t.status] ?? STATUS_STYLES.active,
                        )}
                      >
                        {t.status}
                      </span>
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {t.plan}
                      {t.created_at ? ` · ${format(parseISO(t.created_at), "dd MMM yyyy")}` : ""}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="space-y-6">
          {!selected ? (
            <EmptyState title="Select a tenant" description="Choose a tenant from the list to view details." />
          ) : (
            <section className="card p-4 space-y-3">
              <p className="text-sm font-semibold text-gray-900">Tenant detail</p>
              <h2 className="text-lg font-semibold">{selected.company_name}</h2>
              <p className="text-sm text-gray-600">
                Plan: {selected.plan} · Status: {selected.status}
              </p>
              <p className="text-xs text-gray-400 font-mono">ID: {selected.id}</p>
              {tenantOnboarding ? (
                <div className="pt-3 border-t border-violet-100">
                  <p className="text-xs font-semibold text-violet-800">Onboarding status</p>
                  <p className="text-sm text-gray-700 mt-1">
                    {tenantOnboarding.readiness_score}% ·{" "}
                    <span className="capitalize">{tenantOnboarding.status.replace("_", " ")}</span>
                  </p>
                  <Link href="/pilot-onboarding" className="text-xs text-brand-700 hover:underline">
                    View pilot onboarding →
                  </Link>
                </div>
              ) : (
                <p className="text-xs text-gray-400">No linked factory application onboarding track</p>
              )}
              <div className="flex flex-wrap gap-3 pt-2">
                <Link href="/billing?tab=licenses" className="text-xs text-brand-700 hover:underline">
                  View licenses →
                </Link>
                <Link href="/billing?tab=overview" className="text-xs text-brand-700 hover:underline">
                  Platform billing →
                </Link>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
