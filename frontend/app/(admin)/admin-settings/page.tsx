"use client";

import { useQuery } from "@tanstack/react-query";
import { CreditCard, Network, BarChart3 } from "lucide-react";
import { adminAuthApi } from "@/lib/api";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";

export default function AdminSettingsPage() {
  const { hasPermission } = useAdminAuth();

  const tenantsQuery = useQuery({
    queryKey: ["admin-platform-tenants"],
    queryFn: () => adminAuthApi.platformTenants().then((r) => r.data),
    enabled: hasPermission("tenants.read"),
  });

  const billingQuery = useQuery({
    queryKey: ["admin-platform-billing"],
    queryFn: () => adminAuthApi.platformBilling().then((r) => r.data),
    enabled: hasPermission("billing.read"),
  });

  const analyticsQuery = useQuery({
    queryKey: ["admin-platform-analytics"],
    queryFn: () => adminAuthApi.platformAnalytics().then((r) => r.data),
    enabled: hasPermission("analytics.read"),
  });

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Platform Settings</h1>
        <p className="mt-1 text-sm text-slate-400">
          Tenant management, billing, subscriptions, and platform analytics
        </p>
      </div>

      {hasPermission("analytics.read") ? (
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="mb-3 flex items-center gap-2">
            <BarChart3 size={18} className="text-indigo-400" />
            <h2 className="text-lg font-medium text-white">Platform Analytics</h2>
          </div>
          {analyticsQuery.isLoading ? (
            <LoadingState label="Loading analytics…" />
          ) : analyticsQuery.isError ? (
            <ErrorState message={(analyticsQuery.error as Error).message} onRetry={() => analyticsQuery.refetch()} />
          ) : analyticsQuery.data ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              {[
                ["Tenants", analyticsQuery.data.total_tenants],
                ["Active tenants", analyticsQuery.data.active_tenants],
                ["Clients", analyticsQuery.data.total_clients],
                ["Leads", analyticsQuery.data.total_leads],
                ["Deals", analyticsQuery.data.total_deals],
              ].map(([label, value]) => (
                <div key={label as string} className="rounded-lg border border-slate-800 p-3">
                  <div className="text-xs text-slate-500">{label}</div>
                  <div className="text-xl font-semibold text-white">{value}</div>
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {hasPermission("billing.read") ? (
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="mb-3 flex items-center gap-2">
            <CreditCard size={18} className="text-indigo-400" />
            <h2 className="text-lg font-medium text-white">Billing & Subscriptions</h2>
          </div>
          {billingQuery.isLoading ? (
            <LoadingState label="Loading billing…" />
          ) : billingQuery.isError ? (
            <ErrorState message={(billingQuery.error as Error).message} onRetry={() => billingQuery.refetch()} />
          ) : billingQuery.data ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-slate-800 p-3">
                <div className="text-xs text-slate-500">Total tenants</div>
                <div className="text-xl font-semibold text-white">{billingQuery.data.total_tenants}</div>
              </div>
              <div className="rounded-lg border border-slate-800 p-3">
                <div className="text-xs text-slate-500">Active subscriptions</div>
                <div className="text-xl font-semibold text-white">
                  {billingQuery.data.active_subscriptions}
                </div>
              </div>
              <div className="rounded-lg border border-slate-800 p-3">
                <div className="text-xs text-slate-500">Trial subscriptions</div>
                <div className="text-xl font-semibold text-white">
                  {billingQuery.data.trial_subscriptions}
                </div>
              </div>
              <div className="rounded-lg border border-slate-800 p-3">
                <div className="text-xs text-slate-500">Plans</div>
                <div className="text-xl font-semibold text-white">{billingQuery.data.plans.length}</div>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {hasPermission("tenants.read") ? (
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="mb-3 flex items-center gap-2">
            <Network size={18} className="text-indigo-400" />
            <h2 className="text-lg font-medium text-white">Tenant Management</h2>
          </div>
          {tenantsQuery.isLoading ? (
            <LoadingState label="Loading tenants…" />
          ) : tenantsQuery.isError ? (
            <ErrorState message={(tenantsQuery.error as Error).message} onRetry={() => tenantsQuery.refetch()} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th className="pb-2 pr-4">Company</th>
                    <th className="pb-2 pr-4">Status</th>
                    <th className="pb-2 pr-4">Plan</th>
                    <th className="pb-2">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {(tenantsQuery.data?.items ?? []).map((t) => (
                    <tr key={t.id} className="border-b border-slate-800/60">
                      <td className="py-2 pr-4 text-white">{t.company_name}</td>
                      <td className="py-2 pr-4">{t.status}</td>
                      <td className="py-2 pr-4">{t.plan}</td>
                      <td className="py-2 text-slate-400">
                        {t.created_at ? new Date(t.created_at).toLocaleDateString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {hasPermission("platform.settings") ? (
        <section className="rounded-xl border border-dashed border-slate-700 p-5 text-sm text-slate-400">
          Platform settings configuration (v1 architecture) — extend in future releases.
        </section>
      ) : null}
    </div>
  );
}
