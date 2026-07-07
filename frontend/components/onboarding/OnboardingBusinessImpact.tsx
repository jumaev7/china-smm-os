"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BarChart3, Handshake, Sparkles, Target, TrendingUp } from "lucide-react";
import { customerSuccessApi } from "@/lib/api";
import { cn } from "@/lib/utils";

function fmtMoney(value: number | string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Number(value));
}

export function OnboardingBusinessImpact({ compact = false }: { compact?: boolean }) {
  const { data, isLoading } = useQuery({
    queryKey: ["customer-success", "business-impact"],
    queryFn: () => customerSuccessApi.businessImpact().then((r) => r.data),
    staleTime: 60_000,
  });

  const impact = data?.business_impact;
  const hasData =
    impact &&
    (impact.buyers_acquired > 0 ||
      impact.opportunities_created > 0 ||
      Number(impact.pipeline_created_value) > 0);

  const projectedMetrics = [
    {
      icon: Handshake,
      label: "Buyer relationships",
      value: hasData ? String(impact!.buyers_acquired) : "—",
      hint: hasData ? "acquired" : "Track after first lead",
      tone: "brand" as const,
    },
    {
      icon: Target,
      label: "Pipeline value",
      value: hasData ? fmtMoney(impact!.pipeline_created_value) : "—",
      hint: hasData ? "created" : "Unlocks with deals",
      tone: "emerald" as const,
    },
    {
      icon: TrendingUp,
      label: "Proposal win rate",
      value: hasData ? `${impact!.proposal_acceptance_rate}%` : "—",
      hint: hasData ? "acceptance" : "After first proposal",
      tone: "violet" as const,
    },
    {
      icon: BarChart3,
      label: "Revenue influenced",
      value: hasData ? fmtMoney(data!.roi_kpis.estimated_revenue_influenced) : "—",
      hint: hasData ? "estimated" : "Grows with activity",
      tone: "amber" as const,
    },
  ];

  const toneStyles = {
    brand: "from-brand-50 to-white border-brand-100 text-brand-700",
    emerald: "from-emerald-50 to-white border-emerald-100 text-emerald-700",
    violet: "from-violet-50 to-white border-violet-100 text-violet-700",
    amber: "from-amber-50 to-white border-amber-100 text-amber-700",
  };

  return (
    <section className={cn("rounded-3xl border border-slate-200 bg-white shadow-card overflow-hidden", compact && "rounded-2xl")}>
      <div className="p-6 sm:p-8 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-emerald-700 flex items-center gap-1.5">
              <Sparkles size={12} />
              Business impact
            </p>
            <h2 className="text-xl font-semibold text-navy-900 mt-1">
              {hasData ? "Your export growth in numbers" : "Impact you'll see as you progress"}
            </h2>
            <p className="text-sm text-gray-500 mt-1 max-w-lg">
              {hasData
                ? "Real outcomes from your CRM, proposals, and buyer activity — updated as you work."
                : "Each onboarding step builds toward measurable pipeline and revenue. Metrics appear once you capture leads and deals."}
            </p>
          </div>
          {!compact ? (
            <Link
              href="/customer-success/business-impact"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:text-brand-700 shrink-0"
            >
              Full impact dashboard
              <ArrowRight size={14} />
            </Link>
          ) : null}
        </div>

        <div className={cn("grid gap-4", compact ? "grid-cols-2" : "sm:grid-cols-2 lg:grid-cols-4")}>
          {projectedMetrics.map((m, i) => (
            <div
              key={m.label}
              className={cn(
                "rounded-2xl border bg-gradient-to-br p-4 animate-fade-in-up",
                toneStyles[m.tone],
              )}
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <m.icon size={18} className="opacity-80 mb-3" />
              <p className="text-[10px] uppercase tracking-wide opacity-70 font-medium">{m.label}</p>
              <p className="text-2xl font-bold tabular-nums text-navy-900 mt-1">
                {isLoading ? (
                  <span className="inline-block w-12 h-7 rounded bg-white/60 animate-shimmer bg-gradient-to-r from-transparent via-white/80 to-transparent bg-[length:200%_100%]" />
                ) : (
                  m.value
                )}
              </p>
              <p className="text-xs opacity-70 mt-0.5">{m.hint}</p>
            </div>
          ))}
        </div>

        {!hasData && !isLoading ? (
          <div className="rounded-xl bg-slate-50 border border-slate-100 px-4 py-3 text-sm text-gray-600">
            Complete <strong className="text-navy-900">business readiness</strong> steps to populate live impact metrics.
            Your first lead and deal are the tipping point.
          </div>
        ) : null}
      </div>
    </section>
  );
}
