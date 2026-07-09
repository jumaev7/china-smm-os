"use client";

import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  ExternalLink,
  PlugZap,
  Shield,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  CATEGORY_LABELS,
  formatRelativeTime,
  HEALTH_LABELS,
  HEALTH_STYLES,
  STATUS_LABELS,
  STATUS_STYLES,
  type ResolvedIntegration,
} from "@/lib/integration-center-ui";

function DrawerSection({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: LucideIcon;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark-tenant:text-slate-500 flex items-center gap-1.5">
        <Icon size={13} />
        {title}
      </h3>
      {children}
    </section>
  );
}

export function IntegrationDetailDrawer({
  integration,
  onClose,
}: {
  integration: ResolvedIntegration | null;
  onClose: () => void;
}) {
  if (!integration) return null;

  const Icon = integration.icon;
  const primaryLabel =
    integration.primaryAction === "connect"
      ? "Connect"
      : integration.primaryAction === "manage"
        ? "Manage"
        : integration.primaryAction === "reconnect"
          ? "Reconnect"
          : "Coming Soon";

  const primaryHref =
    integration.primaryAction === "manage"
      ? integration.manageHref
      : integration.primaryAction === "connect" || integration.primaryAction === "reconnect"
        ? integration.connectHref
        : undefined;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-30 backdrop-blur-[1px]"
        onClick={onClose}
        data-app-modal
        aria-hidden
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="integration-drawer-title"
        className={cn(
          "fixed inset-y-0 right-0 w-full max-w-lg z-40 flex flex-col",
          "bg-white border-l border-gray-200 shadow-2xl",
          "dark-tenant:bg-surface-dark-page dark-tenant:border-white/[0.08]",
        )}
      >
        <header className="shrink-0 p-4 border-b border-gray-100 dark-tenant:border-white/[0.06]">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3 min-w-0">
              <div
                className={cn(
                  "shrink-0 flex items-center justify-center w-12 h-12 rounded-xl ring-1",
                  integration.iconClassName,
                  "ring-black/5 dark-tenant:ring-white/10",
                )}
              >
                <Icon size={22} aria-hidden />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-gray-500 dark-tenant:text-slate-500 font-medium uppercase tracking-wide">
                  {CATEGORY_LABELS[integration.category]}
                </p>
                <h2
                  id="integration-drawer-title"
                  className="text-lg font-semibold text-gray-900 dark-tenant:text-slate-100 mt-0.5 truncate"
                >
                  {integration.name}
                </h2>
                <div className="flex flex-wrap items-center gap-2 mt-1.5">
                  <span
                    className={cn(
                      "text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full",
                      STATUS_STYLES[integration.status],
                    )}
                  >
                    {STATUS_LABELS[integration.status]}
                  </span>
                  <span className="flex items-center gap-1 text-xs text-gray-500 dark-tenant:text-slate-500">
                    <span
                      className={cn("w-2 h-2 rounded-full", HEALTH_STYLES[integration.health])}
                      aria-hidden
                    />
                    {HEALTH_LABELS[integration.health]}
                  </span>
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark-tenant:hover:bg-white/[0.06] dark-tenant:hover:text-slate-200"
              aria-label="Close integration details"
            >
              <X size={18} />
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          <DrawerSection title="Overview" icon={CheckCircle2}>
            <p className="text-sm text-gray-600 dark-tenant:text-slate-400 leading-relaxed">
              {integration.description}
            </p>
            {integration.lastSync ? (
              <p className="text-xs text-gray-500 flex items-center gap-1 dark-tenant:text-slate-500">
                <Clock size={11} />
                Last sync {formatRelativeTime(integration.lastSync)}
              </p>
            ) : null}
          </DrawerSection>

          {integration.accountName || integration.accountId ? (
            <DrawerSection title="Connected account" icon={PlugZap}>
              <div className="rounded-xl border border-gray-100 bg-gray-50/80 p-3 space-y-1 dark-tenant:border-white/[0.06] dark-tenant:bg-white/[0.03]">
                {integration.accountName ? (
                  <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-100">
                    {integration.accountName}
                  </p>
                ) : null}
                {integration.accountId ? (
                  <p className="text-xs text-gray-500 font-mono dark-tenant:text-slate-500">
                    {integration.accountId}
                  </p>
                ) : null}
              </div>
            </DrawerSection>
          ) : null}

          <DrawerSection title="Permissions" icon={Shield}>
            {integration.permissions && integration.permissions.length > 0 ? (
              <ul className="space-y-1">
                {integration.permissions.map((perm) => (
                  <li
                    key={perm}
                    className="text-xs text-gray-600 flex items-center gap-1.5 dark-tenant:text-slate-400"
                  >
                    <CheckCircle2 size={11} className="text-emerald-500 shrink-0" />
                    {perm}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-500 dark-tenant:text-slate-500">
                No permission data available yet.
              </p>
            )}
            {integration.missingPermissions && integration.missingPermissions.length > 0 ? (
              <div className="mt-2 rounded-lg bg-amber-50 border border-amber-100 p-3 dark-tenant:bg-amber-500/10 dark-tenant:border-amber-500/20">
                <p className="text-xs font-semibold text-amber-800 dark-tenant:text-amber-300 flex items-center gap-1">
                  <AlertTriangle size={12} />
                  Missing permissions
                </p>
                <ul className="mt-1 space-y-0.5">
                  {integration.missingPermissions.map((perm) => (
                    <li key={perm} className="text-xs text-amber-700 dark-tenant:text-amber-200">
                      {perm}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </DrawerSection>

          <DrawerSection title="Recent sync history" icon={Clock}>
            <div className="rounded-xl border border-dashed border-gray-200 p-4 text-center dark-tenant:border-white/[0.08]">
              <p className="text-sm text-gray-500 dark-tenant:text-slate-500">
                Detailed sync logs will appear here once available.
              </p>
              {integration.logsHref ? (
                <Link
                  href={integration.logsHref}
                  className="inline-flex items-center gap-1 mt-2 text-xs font-semibold text-brand-600 hover:text-brand-700 dark-tenant:text-violet-400"
                >
                  View publishing logs
                  <ExternalLink size={11} />
                </Link>
              ) : null}
            </div>
          </DrawerSection>

          <DrawerSection title="Troubleshooting" icon={Wrench}>
            <ul className="space-y-2">
              {integration.troubleshooting.map((tip) => (
                <li
                  key={tip}
                  className="text-sm text-gray-600 flex items-start gap-2 dark-tenant:text-slate-400"
                >
                  <span className="text-brand-500 mt-1 shrink-0">•</span>
                  {tip}
                </li>
              ))}
            </ul>
            {integration.blockers && integration.blockers.length > 0 ? (
              <div className="mt-3 rounded-lg bg-red-50 border border-red-100 p-3 dark-tenant:bg-red-500/10 dark-tenant:border-red-500/20">
                <p className="text-xs font-semibold text-red-800 dark-tenant:text-red-300">Blockers</p>
                <ul className="mt-1 space-y-0.5">
                  {integration.blockers.map((b) => (
                    <li key={b} className="text-xs text-red-700 dark-tenant:text-red-200">
                      {b}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </DrawerSection>
        </div>

        <footer className="shrink-0 p-4 border-t border-gray-100 dark-tenant:border-white/[0.06] flex flex-wrap gap-2">
          {primaryHref && integration.primaryAction !== "coming_soon" ? (
            <Link
              href={primaryHref}
              className={cn(
                "inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors",
                integration.status === "attention_needed"
                  ? "bg-amber-600 text-white hover:bg-amber-700"
                  : integration.status === "connected"
                    ? "bg-emerald-600 text-white hover:bg-emerald-700"
                    : "bg-brand-600 text-white hover:bg-brand-700 dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500",
              )}
              aria-label={`${primaryLabel} ${integration.name}`}
            >
              <PlugZap size={14} />
              {primaryLabel}
            </Link>
          ) : null}
          {integration.settingsHref && integration.status !== "coming_soon" ? (
            <Link
              href={integration.settingsHref}
              className="inline-flex items-center gap-2 rounded-xl border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark-tenant:border-white/10 dark-tenant:text-slate-300 dark-tenant:hover:bg-white/[0.04]"
            >
              Settings
            </Link>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-2 rounded-xl border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark-tenant:border-white/10 dark-tenant:text-slate-300 dark-tenant:hover:bg-white/[0.04]"
          >
            Close
          </button>
        </footer>
      </aside>
    </>
  );
}
