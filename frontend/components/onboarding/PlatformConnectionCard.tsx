"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { CheckCircle2, Clock, Loader2, PlugZap } from "lucide-react";
import { cn } from "@/lib/utils";

export function PlatformConnectionCard({
  icon: Icon,
  name,
  description,
  connected,
  comingSoon = false,
  lastSync,
  connectHref,
  onConnect,
  connecting = false,
  index = 0,
}: {
  icon: LucideIcon;
  name: string;
  description?: string;
  connected: boolean;
  comingSoon?: boolean;
  lastSync?: string | null;
  connectHref?: string;
  onConnect?: () => void;
  connecting?: boolean;
  index?: number;
}) {
  const statusLabel = comingSoon ? "Coming Soon" : connected ? "Connected" : "Not Connected";

  const inner = (
    <div
      className={cn(
        "group relative flex flex-col rounded-2xl border p-5 transition-all duration-300 animate-fade-in-up",
        connected
          ? "border-emerald-200/80 bg-emerald-50/30 shadow-card dark-tenant:border-emerald-500/20 dark-tenant:bg-emerald-500/5"
          : comingSoon
            ? "border-slate-200/60 bg-slate-50/50 opacity-75 dark-tenant:border-white/[0.06] dark-tenant:bg-white/[0.02]"
            : "border-slate-200 bg-white shadow-card hover:shadow-card-hover hover:border-brand-200 dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card dark-tenant:hover:border-violet-500/30",
      )}
      style={{ animationDelay: `${index * 60}ms` }}
    >
      {connected ? (
        <div className="absolute top-0 left-5 right-5 h-0.5 rounded-full bg-gradient-to-r from-emerald-400 to-emerald-500" />
      ) : null}

      <div className="flex items-start gap-4">
        <div
          className={cn(
            "shrink-0 flex items-center justify-center w-12 h-12 rounded-xl ring-1",
            connected
              ? "bg-emerald-100 ring-emerald-200 text-emerald-600 dark-tenant:bg-emerald-500/15 dark-tenant:ring-emerald-500/25"
              : "bg-brand-50 ring-brand-100 text-brand-600 dark-tenant:bg-violet-500/10 dark-tenant:ring-violet-500/20 dark-tenant:text-violet-400",
          )}
        >
          {connected ? <CheckCircle2 size={22} /> : <Icon size={22} />}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-[15px] text-navy-900 dark-tenant:text-slate-100">{name}</h3>
            <StatusBadge connected={connected} comingSoon={comingSoon} label={statusLabel} />
          </div>
          {description ? (
            <p className="text-sm text-gray-600 mt-1 leading-relaxed dark-tenant:text-slate-400">{description}</p>
          ) : null}
          {lastSync && connected ? (
            <p className="text-xs text-gray-500 mt-2 flex items-center gap-1 dark-tenant:text-slate-500">
              <Clock size={11} />
              Last sync {formatRelativeTime(lastSync)}
            </p>
          ) : null}
        </div>
      </div>

      {!comingSoon && !connected ? (
        <div className="mt-4 pt-4 border-t border-slate-100 dark-tenant:border-white/[0.06]">
          {connectHref ? (
            <Link
              href={connectHref}
              className="inline-flex items-center gap-2 text-sm font-semibold text-brand-600 hover:text-brand-700 dark-tenant:text-violet-400"
            >
              <PlugZap size={14} />
              Connect
            </Link>
          ) : onConnect ? (
            <button
              type="button"
              onClick={onConnect}
              disabled={connecting}
              className="inline-flex items-center gap-2 text-sm font-semibold text-brand-600 hover:text-brand-700 disabled:opacity-50 dark-tenant:text-violet-400"
            >
              {connecting ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />}
              {connecting ? "Connecting…" : "Connect"}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );

  return inner;
}

function StatusBadge({
  connected,
  comingSoon,
  label,
}: {
  connected: boolean;
  comingSoon: boolean;
  label: string;
}) {
  return (
    <span
      className={cn(
        "text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full",
        connected
          ? "bg-emerald-100 text-emerald-700 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-300"
          : comingSoon
            ? "bg-slate-100 text-slate-500 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-500"
            : "bg-amber-50 text-amber-700 dark-tenant:bg-amber-500/10 dark-tenant:text-amber-300",
      )}
    >
      {label}
    </span>
  );
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
