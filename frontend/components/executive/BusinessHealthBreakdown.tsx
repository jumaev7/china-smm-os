"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import type { BusinessHealthAssessment, DomainHealthAssessment } from "@/lib/api";
import { HealthIndicator } from "@/components/ui/design-system/HealthIndicator";
import { businessHealthBandLabel, domainDrilldownHref } from "@/lib/business-health";

function coverageLabel(health: BusinessHealthAssessment): string {
  const pct = Math.round((health.data_confidence || 0) * 100);
  return `${health.domains_evaluated}/${health.domains_evaluated + health.domains_unavailable} domains · ${pct}% coverage`;
}

function DomainRow({ domain }: { domain: DomainHealthAssessment }) {
  const href = domainDrilldownHref(domain.domain);
  const available = domain.availability === "available";
  const content = (
    <>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-navy-900 truncate dark-tenant:text-slate-100">
          {domain.label}
        </p>
        <p className="text-[11px] text-gray-500 truncate dark-tenant:text-slate-400">
          {available
            ? `${domain.status?.replace(/_/g, " ") ?? "—"} · weight ${(domain.effective_weight * 100).toFixed(0)}%`
            : (domain.unavailable_reason || domain.availability).replace(/_/g, " ")}
        </p>
      </div>
      <div className="tabular-nums text-sm font-semibold text-navy-800 dark-tenant:text-slate-100">
        {available && domain.score != null ? domain.score : "—"}
      </div>
    </>
  );

  if (href) {
    return (
      <Link
        href={href}
        className="flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-brand-50/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500 dark-tenant:hover:bg-white/[0.04]"
        aria-label={`${domain.label}: ${available && domain.score != null ? domain.score : domain.availability}`}
      >
        {content}
      </Link>
    );
  }

  return (
    <div
      className="flex items-center gap-3 rounded-lg px-2 py-2"
      aria-label={`${domain.label}: ${available && domain.score != null ? domain.score : domain.availability}`}
    >
      {content}
    </div>
  );
}

export function BusinessHealthBreakdown({
  health,
  loading,
  error,
  className,
  title = "Business Health",
}: {
  health?: BusinessHealthAssessment | null;
  loading?: boolean;
  error?: boolean;
  className?: string;
  title?: string;
}) {
  if (loading) {
    return (
      <div className={cn("card p-4", className)} role="status" aria-live="polite">
        <p className="text-sm text-gray-500">Loading business health…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className={cn("card p-4 border-danger-200", className)} role="alert">
        <p className="text-sm text-danger-700">Business health assessment unavailable.</p>
      </div>
    );
  }

  if (!health) {
    return (
      <div className={cn("card p-4", className)}>
        <p className="text-sm text-gray-500">No business health data yet.</p>
      </div>
    );
  }

  const band = businessHealthBandLabel(health.status);
  const available = health.domains.filter((d) => d.availability === "available");
  const unavailable = health.domains.filter((d) => d.availability !== "available");

  return (
    <section
      className={cn("card p-4 space-y-4", className)}
      aria-labelledby="business-health-heading"
    >
      <div className="flex flex-col sm:flex-row sm:items-start gap-4">
        <HealthIndicator
          score={health.score}
          label={`${title} · ${band}`}
          size="lg"
        />
        <div className="min-w-0 flex-1 space-y-1">
          <h2 id="business-health-heading" className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100">
            {title}: {health.score}/100 — {band}
          </h2>
          <p className="text-xs text-gray-600 dark-tenant:text-slate-400">
            {health.executive_summary}
          </p>
          <p className="text-[11px] text-gray-500 dark-tenant:text-slate-500">
            {coverageLabel(health)}
            {health.history_available && health.change != null
              ? ` · Δ ${health.change > 0 ? "+" : ""}${health.change}`
              : " · No comparable history"}
            {" · "}
            {health.methodology_version}
          </p>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="space-y-1 lg:col-span-1">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Domains</h3>
          <ul className="divide-y divide-gray-100 dark-tenant:divide-white/[0.06]">
            {available.map((d) => (
              <li key={d.domain}>
                <DomainRow domain={d} />
              </li>
            ))}
            {unavailable.map((d) => (
              <li key={d.domain} className="opacity-70">
                <DomainRow domain={d} />
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Main deductions
          </h3>
          {health.deductions.length === 0 ? (
            <p className="text-xs text-gray-500">No material deductions.</p>
          ) : (
            <ul className="space-y-2">
              {health.deductions.map((item) => (
                <li key={item.code + item.title} className="text-xs text-gray-700 dark-tenant:text-slate-300">
                  <span className="font-medium text-navy-900 dark-tenant:text-slate-100">{item.title}</span>
                  <span className="text-gray-400"> · impact {item.score_impact}</span>
                  <p className="text-[11px] text-gray-500 mt-0.5">{item.explanation}</p>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Positive signals
          </h3>
          {health.positive_signals.length === 0 ? (
            <p className="text-xs text-gray-500">No positive signals flagged.</p>
          ) : (
            <ul className="space-y-2">
              {health.positive_signals.map((item) => (
                <li key={item.code + item.title} className="text-xs text-gray-700 dark-tenant:text-slate-300">
                  <span className="font-medium text-navy-900 dark-tenant:text-slate-100">{item.title}</span>
                  <p className="text-[11px] text-gray-500 mt-0.5">{item.explanation}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {health.disclaimer && (
        <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500">{health.disclaimer}</p>
      )}
    </section>
  );
}
