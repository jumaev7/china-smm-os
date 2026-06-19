"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ArrowRight,
  Briefcase,
  CheckCircle2,
  Globe,
  Lightbulb,
  MessageSquare,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react";
import { commercialDemoApi } from "@/lib/commercial-demo-api";
import { DemoModeBanner } from "@/components/demo/DemoModeToggle";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { KpiCard, PageHeader, PageShell, ScoreCard } from "@/components/ui/design-system";
import { cn } from "@/lib/utils";

const TREND_COLORS = {
  up: "text-emerald-600",
  down: "text-red-600",
  neutral: "text-gray-500",
};

const SECTION_ICONS: Record<string, typeof Users> = {
  buyer_growth: Users,
  pipeline: Briefcase,
  proposals: Sparkles,
  communications: MessageSquare,
};

export default function ExecutiveDemoPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["commercial-demo", "executive-demo"],
    queryFn: () => commercialDemoApi.getExecutiveDemo().then((r) => r.data),
  });

  if (isLoading) {
    return (
      <PageShell>
        <LoadingState message="Preparing executive presentation…" />
      </PageShell>
    );
  }

  if (isError || !data) {
    return (
      <PageShell>
        <ErrorState error={error} onRetry={() => refetch()} />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <div className="rounded-2xl border border-navy-200 bg-gradient-to-br from-navy-900 via-navy-800 to-brand-900 text-white p-8 mb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium text-brand-300 uppercase tracking-wider">
              Executive Dashboard
            </p>
            <h1 className="text-2xl font-bold mt-1">{data.headline}</h1>
            {(data.industry || data.country) && (
              <p className="text-sm text-gray-300 mt-2 flex items-center gap-2">
                <Globe size={14} />
                {[data.industry, data.country].filter(Boolean).join(" · ")}
              </p>
            )}
          </div>
          <ScoreCard
            title="ROI Score"
            score={data.roi_score}
            subtitle="Platform impact"
            className="bg-white/10 border-white/20 text-white max-w-[180px]"
          />
        </div>
        <p className="text-xs text-gray-400 mt-4">
          Generated {format(parseISO(data.generated_at), "MMM d, yyyy HH:mm")}
        </p>
      </div>

      <DemoModeBanner />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.kpis.map((kpi) => (
          <div key={kpi.label} className="card-premium p-4">
            <p className="text-xs text-gray-500">{kpi.label}</p>
            <p className="text-2xl font-bold text-navy-900 mt-1">{kpi.value}</p>
            {kpi.change && (
              <p className={cn("text-xs mt-1 flex items-center gap-1", TREND_COLORS[kpi.trend])}>
                <TrendingUp size={12} />
                {kpi.change}
              </p>
            )}
          </div>
        ))}
      </div>

      <section className="mt-8">
        <h2 className="text-base font-semibold text-navy-900 mb-4">Business Overview</h2>
        <div className="grid gap-4 md:grid-cols-2">
          {data.sections.map((section) => {
            const Icon = SECTION_ICONS[section.id] ?? Briefcase;
            return (
              <Link
                key={section.id}
                href={section.route}
                className="card-premium p-5 hover:shadow-md transition-shadow group"
              >
                <div className="flex items-center gap-2 mb-2">
                  <Icon size={18} className="text-brand-600" />
                  <h3 className="font-semibold text-navy-900">{section.title}</h3>
                  <ArrowRight
                    size={14}
                    className="ml-auto text-gray-300 group-hover:text-brand-500 transition-colors"
                  />
                </div>
                <p className="text-sm text-gray-600">{section.summary}</p>
                <ul className="mt-3 space-y-1">
                  {section.highlights.map((h) => (
                    <li key={h} className="text-xs text-gray-500 flex items-start gap-1.5">
                      <CheckCircle2 size={10} className="text-emerald-500 shrink-0 mt-0.5" />
                      {h}
                    </li>
                  ))}
                </ul>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="mt-8 card-premium p-6">
        <h2 className="text-base font-semibold text-navy-900 mb-1 flex items-center gap-2">
          <Lightbulb size={18} className="text-amber-500" />
          AI Recommendations
        </h2>
        <p className="text-sm text-gray-500 mb-4">Actions to take this week for maximum export growth.</p>
        <ul className="space-y-3">
          {data.ai_recommendations.map((rec) => (
            <li
              key={rec}
              className="flex items-start gap-3 rounded-lg border border-amber-100 bg-amber-50/50 px-4 py-3 text-sm text-gray-800"
            >
              <Sparkles size={14} className="text-amber-500 shrink-0 mt-0.5" />
              {rec}
            </li>
          ))}
        </ul>
      </section>

      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/value-demo" className="btn-secondary text-sm">
          Value Demo
        </Link>
        <Link href="/demo-tour" className="btn-secondary text-sm">
          Demo Tour
        </Link>
        <Link href="/growth-center" className="btn-primary text-sm">
          Full Growth Center
        </Link>
      </div>
    </PageShell>
  );
}
