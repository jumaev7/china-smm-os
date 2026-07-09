"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRelativeTime, type ResolvedIntegration } from "@/lib/integration-center-ui";

export function IntegrationConnectedPanel({
  items,
  onSelect,
}: {
  items: ResolvedIntegration[];
  onSelect: (integration: ResolvedIntegration) => void;
}) {
  if (items.length === 0) return null;

  return (
    <section aria-label="Connected integrations" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="section-title">Connected integrations</h2>
        <span className="text-xs text-gray-500 dark-tenant:text-slate-500">{items.length} active</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => onSelect(item)}
              className={cn(
                "flex items-center gap-3 rounded-xl border border-emerald-200/60 bg-emerald-50/30 p-3 text-left",
                "hover:border-emerald-300 hover:shadow-sm transition-all",
                "dark-tenant:border-emerald-500/20 dark-tenant:bg-emerald-500/5 dark-tenant:hover:border-emerald-500/40",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40",
              )}
              aria-label={`View ${item.name} connection details`}
            >
              <div
                className={cn(
                  "shrink-0 w-10 h-10 rounded-lg flex items-center justify-center ring-1",
                  item.iconClassName,
                  "ring-black/5 dark-tenant:ring-white/10",
                )}
              >
                <Icon size={18} aria-hidden />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100 truncate">
                  {item.name}
                </p>
                <p className="text-xs text-gray-500 dark-tenant:text-slate-500 truncate">
                  {item.accountName ?? "Connected"}
                  {item.lastSync ? ` · ${formatRelativeTime(item.lastSync)}` : ""}
                </p>
              </div>
              <CheckCircle2 size={16} className="text-emerald-500 shrink-0" aria-hidden />
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function IntegrationAttentionPanel({
  items,
  onSelect,
}: {
  items: ResolvedIntegration[];
  onSelect: (integration: ResolvedIntegration) => void;
}) {
  if (items.length === 0) return null;

  return (
    <section aria-label="Integrations needing attention" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="section-title text-amber-800 dark-tenant:text-amber-300">Needs attention</h2>
        <Link
          href="/publishing"
          className="text-xs font-medium text-amber-700 hover:text-amber-900 flex items-center gap-1 dark-tenant:text-amber-400"
        >
          Publishing settings
          <ArrowRight size={12} />
        </Link>
      </div>
      <div className="rounded-2xl border border-amber-200/80 bg-amber-50/40 divide-y divide-amber-100 dark-tenant:border-amber-500/20 dark-tenant:bg-amber-500/5 dark-tenant:divide-amber-500/10">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => onSelect(item)}
              className="flex w-full items-center gap-3 p-4 text-left hover:bg-amber-50/80 transition-colors dark-tenant:hover:bg-amber-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-500/40"
              aria-label={`Fix ${item.name} connection`}
            >
              <div
                className={cn(
                  "shrink-0 w-10 h-10 rounded-lg flex items-center justify-center ring-1",
                  item.iconClassName,
                  "ring-black/5 dark-tenant:ring-white/10",
                )}
              >
                <Icon size={18} aria-hidden />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100">{item.name}</p>
                <p className="text-xs text-amber-700 dark-tenant:text-amber-300">
                  {item.missingPermissions?.length
                    ? `Missing: ${item.missingPermissions.slice(0, 2).join(", ")}`
                    : item.blockers?.length
                      ? item.blockers[0]
                      : "Connection requires attention"}
                </p>
              </div>
              <span className="text-xs font-semibold text-amber-800 dark-tenant:text-amber-300 shrink-0">
                Reconnect
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function IntegrationEmptyState() {
  return (
    <section
      className="rounded-2xl border border-dashed border-gray-200 bg-gray-50/50 p-8 text-center dark-tenant:border-white/[0.08] dark-tenant:bg-white/[0.02]"
      aria-label="No integrations connected"
    >
      <div className="w-14 h-14 rounded-2xl bg-brand-50 flex items-center justify-center mx-auto mb-4 dark-tenant:bg-violet-500/10">
        <CheckCircle2 size={28} className="text-brand-600 dark-tenant:text-violet-400" />
      </div>
      <h3 className="text-lg font-semibold text-gray-900 dark-tenant:text-slate-100">
        No integrations connected yet
      </h3>
      <p className="text-sm text-gray-600 mt-2 max-w-md mx-auto dark-tenant:text-slate-400">
        Connect your social, messaging, and publishing accounts to start syncing content and reaching buyers
        from one hub.
      </p>
      <div className="flex flex-wrap justify-center gap-3 mt-6">
        <Link
          href="/onboarding/channels"
          className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500"
        >
          Start connecting
          <ArrowRight size={14} />
        </Link>
        <Link
          href="/publishing"
          className="inline-flex items-center gap-2 rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-white dark-tenant:border-white/10 dark-tenant:text-slate-300 dark-tenant:hover:bg-white/[0.04]"
        >
          Publishing settings
        </Link>
      </div>
    </section>
  );
}
