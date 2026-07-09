"use client";

import Link from "next/link";
import { AlertTriangle, Plug, PlugZap, Settings } from "lucide-react";
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

export function IntegrationCard({
  integration,
  onSelect,
  index = 0,
}: {
  integration: ResolvedIntegration;
  onSelect: (integration: ResolvedIntegration) => void;
  index?: number;
}) {
  const Icon = integration.icon;
  const isConnected = integration.status === "connected";
  const needsAttention = integration.status === "attention_needed";

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
    <article
      className={cn(
        "group relative flex flex-col rounded-2xl border p-5 transition-all duration-300 animate-fade-in-up",
        "focus-within:ring-2 focus-within:ring-brand-500/40 focus-within:ring-offset-2 dark-tenant:focus-within:ring-violet-500/40",
        isConnected
          ? "border-emerald-200/80 bg-emerald-50/20 shadow-card dark-tenant:border-emerald-500/20 dark-tenant:bg-emerald-500/5"
          : needsAttention
            ? "border-amber-200/80 bg-amber-50/30 shadow-card dark-tenant:border-amber-500/20 dark-tenant:bg-amber-500/5"
            : integration.status === "coming_soon"
              ? "border-slate-200/60 bg-slate-50/50 opacity-90 dark-tenant:border-white/[0.06] dark-tenant:bg-white/[0.02]"
              : "border-slate-200 bg-white shadow-card hover:shadow-card-hover hover:border-brand-200 dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card dark-tenant:hover:border-violet-500/30",
      )}
      style={{ animationDelay: `${index * 40}ms` }}
    >
      {isConnected ? (
        <div className="absolute top-0 left-5 right-5 h-0.5 rounded-full bg-gradient-to-r from-emerald-400 to-emerald-500" />
      ) : needsAttention ? (
        <div className="absolute top-0 left-5 right-5 h-0.5 rounded-full bg-gradient-to-r from-amber-400 to-orange-500" />
      ) : null}

      <button
        type="button"
        onClick={() => onSelect(integration)}
        className="flex flex-col flex-1 text-left w-full"
        aria-label={`View ${integration.name} integration details`}
      >
        <div className="flex items-start gap-4">
          <div
            className={cn(
              "shrink-0 flex items-center justify-center w-12 h-12 rounded-xl ring-1",
              integration.iconClassName,
              "ring-black/5 dark-tenant:ring-white/10",
            )}
          >
            <Icon size={22} aria-hidden />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-semibold text-[15px] text-navy-900 dark-tenant:text-slate-100">
                {integration.name}
              </h3>
              <span
                className={cn(
                  "text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full",
                  STATUS_STYLES[integration.status],
                )}
              >
                {STATUS_LABELS[integration.status]}
              </span>
            </div>
            <p className="text-[11px] text-gray-500 mt-0.5 dark-tenant:text-slate-500">
              {CATEGORY_LABELS[integration.category]}
            </p>
            <p className="text-sm text-gray-600 mt-1.5 leading-relaxed line-clamp-2 dark-tenant:text-slate-400">
              {integration.description}
            </p>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-xs text-gray-500 dark-tenant:text-slate-500">
            <span
              className={cn("w-2 h-2 rounded-full shrink-0", HEALTH_STYLES[integration.health])}
              aria-hidden
            />
            <span>{HEALTH_LABELS[integration.health]}</span>
            {integration.lastSync && isConnected ? (
              <span className="text-gray-400 dark-tenant:text-slate-600">·</span>
            ) : null}
            {integration.lastSync && isConnected ? (
              <span>Synced {formatRelativeTime(integration.lastSync)}</span>
            ) : null}
          </div>
        </div>
      </button>

      <div className="mt-4 pt-4 border-t border-slate-100 dark-tenant:border-white/[0.06] flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {primaryHref && integration.primaryAction !== "coming_soon" ? (
            <Link
              href={primaryHref}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
                needsAttention
                  ? "bg-amber-100 text-amber-800 hover:bg-amber-200 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-300"
                  : isConnected
                    ? "bg-emerald-100 text-emerald-800 hover:bg-emerald-200 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-300"
                    : "bg-brand-600 text-white hover:bg-brand-700 dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500",
              )}
              aria-label={`${primaryLabel} ${integration.name}`}
              onClick={(e) => e.stopPropagation()}
            >
              {needsAttention ? <AlertTriangle size={12} /> : <PlugZap size={12} />}
              {primaryLabel}
            </Link>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold bg-slate-100 text-slate-500 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-500">
              <Plug size={12} />
              Coming Soon
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          {integration.logsHref && integration.status !== "coming_soon" ? (
            <button
              type="button"
              onClick={() => onSelect(integration)}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark-tenant:hover:bg-white/[0.06] dark-tenant:hover:text-slate-200 text-xs"
              aria-label={`View logs for ${integration.name}`}
            >
              Logs
            </button>
          ) : null}
          {integration.settingsHref && integration.status !== "coming_soon" ? (
            <Link
              href={integration.settingsHref}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark-tenant:hover:bg-white/[0.06] dark-tenant:hover:text-slate-200"
              aria-label={`Settings for ${integration.name}`}
              onClick={(e) => e.stopPropagation()}
            >
              <Settings size={14} />
            </Link>
          ) : null}
        </div>
      </div>
    </article>
  );
}
