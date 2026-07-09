"use client";

import { HeartPulse, Link2, PlugZap, AlertTriangle } from "lucide-react";
import { KpiCard } from "@/components/ui/design-system/KpiCard";
import { PageHeader } from "@/components/ui/design-system";
import {
  HEALTH_LABELS,
  type IntegrationHealth,
  type IntegrationCategory,
} from "@/lib/integration-center-ui";

export function IntegrationCenterHeader({
  connectedCount,
  attentionCount,
  notConnectedCount,
  overallHealth,
  activeCategory,
  onCategoryChange,
  categories,
}: {
  connectedCount: number;
  attentionCount: number;
  notConnectedCount: number;
  overallHealth: IntegrationHealth;
  activeCategory: IntegrationCategory;
  onCategoryChange: (category: IntegrationCategory) => void;
  categories: { id: IntegrationCategory; label: string }[];
}) {
  const healthSub =
    overallHealth === "healthy"
      ? "All systems operational"
      : overallHealth === "degraded"
        ? "Some integrations in mock mode"
        : overallHealth === "unhealthy"
          ? "Action required"
          : "No connections yet";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Integration Center"
        subtitle="Connect, monitor, and manage all external services from one place."
        icon={Link2}
      />

      <section
        className="grid grid-cols-2 sm:grid-cols-4 gap-3 animate-fade-in-up"
        aria-label="Integration health summary"
      >
        <KpiCard
          label="Overall Health"
          value={HEALTH_LABELS[overallHealth]}
          sub={healthSub}
          icon={HeartPulse}
          iconClassName={
            overallHealth === "healthy"
              ? "bg-emerald-50 text-emerald-600 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-400"
              : overallHealth === "unhealthy"
                ? "bg-red-50 text-red-600 dark-tenant:bg-red-500/15 dark-tenant:text-red-400"
                : overallHealth === "degraded"
                  ? "bg-amber-50 text-amber-600 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-400"
                  : "bg-slate-50 text-slate-600 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-400"
          }
        />
        <KpiCard
          label="Connected"
          value={connectedCount}
          sub="Active integrations"
          icon={PlugZap}
          iconClassName="bg-emerald-50 text-emerald-600 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-400"
        />
        <KpiCard
          label="Attention Needed"
          value={attentionCount}
          sub={attentionCount > 0 ? "Requires action" : "All clear"}
          icon={AlertTriangle}
          iconClassName="bg-amber-50 text-amber-600 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-400"
        />
        <KpiCard
          label="Available"
          value={notConnectedCount}
          sub="Ready to connect"
          icon={Link2}
          iconClassName="bg-sky-50 text-sky-600 dark-tenant:bg-sky-500/15 dark-tenant:text-sky-400"
        />
      </section>

      <nav aria-label="Integration categories">
        <div className="flex flex-wrap gap-2">
          {categories.map((cat) => {
            const active = activeCategory === cat.id;
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => onCategoryChange(cat.id)}
                aria-pressed={active}
                className={
                  active
                    ? "rounded-xl bg-brand-600 px-3.5 py-2 text-xs font-semibold text-white shadow-sm dark-tenant:bg-violet-600"
                    : "rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-xs font-medium text-gray-600 hover:border-brand-200 hover:text-brand-700 dark-tenant:border-white/10 dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-400 dark-tenant:hover:border-violet-500/30 dark-tenant:hover:text-violet-300"
                }
              >
                {cat.label}
              </button>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
