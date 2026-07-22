"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  FileText,
  Radio,
  RefreshCw,
} from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  ActionBar,
  FilterBar,
  KpiCard,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import {
  MEASUREMENT_QUERY_KEY,
  getApiErrorMessage,
  measurementApi,
} from "@/lib/api";
import {
  MEASUREMENT_PERIOD_OPTIONS,
  formatWhen,
  freshnessVariant,
  parsePeriodDays,
  titleCaseKey,
} from "@/lib/measurement-ui";
import { PLATFORM_CONFIG, cn } from "@/lib/utils";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function PerformanceOverviewPage() {
  const [period, setPeriod] = useState("30");
  const days = parsePeriodDays(period);

  const overviewQuery = useQuery({
    queryKey: [...MEASUREMENT_QUERY_KEY, "overview", days],
    queryFn: () => measurementApi.overview({ days }).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const configQuery = useQuery({
    queryKey: [...MEASUREMENT_QUERY_KEY, "configuration"],
    queryFn: () => measurementApi.configuration().then((r) => r.data),
    ...QUERY_OPTS,
  });

  const data = overviewQuery.data;
  const unsupportedPlatforms =
    configQuery.data?.platforms.filter((p) => p.capability_status === "unsupported") ?? [];

  return (
    <PageShell wide>
      <PageHeader
        title="Performance overview"
        subtitle="Observed publication metrics and measurement coverage — not causal attribution."
        icon={BarChart3}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link href="/analytics/content" className="btn-secondary text-sm">
              Content
            </Link>
            <Link href="/analytics/campaigns" className="btn-secondary text-sm">
              Campaigns
            </Link>
            <Link href="/analytics" className="btn-secondary text-sm">
              Publish volume
            </Link>
          </div>
        }
      />

      <ActionBar>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between w-full">
          <FilterBar options={MEASUREMENT_PERIOD_OPTIONS} value={period} onChange={setPeriod} />
          <p className="text-xs text-slate-500 dark-tenant:text-slate-400">
            Window filters by <span className="font-medium">publication date</span>. Metric values
            use the latest <span className="font-medium">observation date</span> available.
          </p>
        </div>
      </ActionBar>

      {overviewQuery.isLoading ? <LoadingState message="Loading measurement overview…" /> : null}

      {overviewQuery.isError && !overviewQuery.isLoading ? (
        <ErrorState
          title="Unable to load performance overview"
          message={getApiErrorMessage(overviewQuery.error)}
          onRetry={() => overviewQuery.refetch()}
        />
      ) : null}

      {!overviewQuery.isLoading && !overviewQuery.isError && data ? (
        <>
          <div className="mb-2 text-xs text-slate-500 dark-tenant:text-slate-400">
            Selected window: {formatWhen(data.window_start)} → {formatWhen(data.window_end)}
            {data.timezone ? ` (${data.timezone})` : ""}
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              label="Measured publications"
              value={data.measured_publications}
              icon={FileText}
              iconClassName="bg-slate-100 text-slate-600 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-300"
            />
            <KpiCard
              label="Fresh observations"
              value={data.fresh_count}
              sub={data.aging_count != null ? `${data.aging_count} aging` : undefined}
              icon={Activity}
              iconClassName="bg-emerald-100 text-emerald-600 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-400"
            />
            <KpiCard
              label="Stale"
              value={data.stale_count}
              icon={RefreshCw}
              iconClassName="bg-amber-100 text-amber-600 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-400"
            />
            <KpiCard
              label="Unsupported"
              value={data.unsupported_count}
              sub={
                data.unavailable_count != null
                  ? `${data.unavailable_count} unavailable`
                  : undefined
              }
              icon={Radio}
              iconClassName="bg-slate-100 text-slate-600 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-300"
            />
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <KpiCard
              label="Attribution coverage"
              value={
                data.attribution_coverage.coverage_ratio != null
                  ? `${(data.attribution_coverage.coverage_ratio * 100).toFixed(0)}%`
                  : "—"
              }
              sub={`${data.attribution_coverage.attributed_publications} attributed · ${data.attribution_coverage.unattributed_publications} unattributed`}
              icon={Activity}
            />
            <KpiCard
              label="Open anomalies"
              value={data.open_anomalies}
              icon={AlertTriangle}
              iconClassName="bg-amber-100 text-amber-600 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-400"
            />
            <KpiCard
              label="Recent ingestion failures"
              value={data.recent_ingestion_failures.length}
              icon={AlertTriangle}
              iconClassName="bg-rose-100 text-rose-600 dark-tenant:bg-rose-500/15 dark-tenant:text-rose-400"
            />
          </div>

          <div className="mt-6 grid gap-6 xl:grid-cols-2">
            <PageSection title="Platform distribution">
              {data.platform_distribution.length === 0 ? (
                <EmptyState
                  title="No measured publications in this window"
                  description="Publications registered for measurement will appear here after publish success."
                />
              ) : (
                <div className="space-y-2">
                  {data.platform_distribution.map((row) => {
                    const cfg = PLATFORM_CONFIG[row.platform as keyof typeof PLATFORM_CONFIG];
                    return (
                      <div
                        key={row.platform}
                        className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span
                            className={cn(
                              "text-[10px] px-1.5 py-0.5 rounded font-bold shrink-0",
                              cfg?.color ?? "bg-gray-100",
                            )}
                          >
                            {cfg?.label ?? titleCaseKey(row.platform)}
                          </span>
                          {row.capability_status ? (
                            <StatusBadge variant={freshnessVariant(row.capability_status)}>
                              {row.capability_status.replace(/_/g, " ")}
                            </StatusBadge>
                          ) : null}
                        </div>
                        <span className="tabular-nums font-medium">{row.publication_count}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </PageSection>

            <PageSection title="Recent ingestion failures">
              {data.recent_ingestion_failures.length === 0 ? (
                <p className="text-sm text-slate-500 dark-tenant:text-slate-400">
                  No recent ingestion failures recorded.
                </p>
              ) : (
                <div className="space-y-2">
                  {data.recent_ingestion_failures.slice(0, 8).map((fail) => (
                    <div
                      key={fail.id}
                      className="rounded-lg border border-rose-200 bg-rose-50/50 px-3 py-2 text-sm dark-tenant:border-rose-900 dark-tenant:bg-rose-950/30"
                    >
                      <div className="flex justify-between gap-2">
                        <span className="font-medium">{fail.platform ?? "unknown platform"}</span>
                        <span className="text-xs text-slate-500">{formatWhen(fail.created_at)}</span>
                      </div>
                      <p className="mt-0.5 text-xs text-slate-600 dark-tenant:text-slate-300">
                        {fail.error_summary ?? fail.status}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </PageSection>
          </div>

          {unsupportedPlatforms.length > 0 ? (
            <PageSection title="Unsupported platforms">
              <p className="mb-3 text-sm text-slate-500 dark-tenant:text-slate-400">
                These platforms cannot supply live post-level metrics with the current adapters.
                No fabricated values are shown.
              </p>
              <div className="flex flex-wrap gap-2">
                {unsupportedPlatforms.map((p) => (
                  <div
                    key={p.platform}
                    className="rounded-lg border border-dashed border-slate-300 px-3 py-2 text-sm dark-tenant:border-slate-700"
                  >
                    <p className="font-medium">{titleCaseKey(p.platform)}</p>
                    <p className="text-xs text-slate-500">
                      {p.unsupported_reason ?? "Live metrics unsupported"}
                    </p>
                  </div>
                ))}
              </div>
            </PageSection>
          ) : null}

          {data.notes && data.notes.length > 0 ? (
            <ul className="mt-4 space-y-1 text-xs text-slate-500">
              {data.notes.map((note) => (
                <li key={note}>• {note}</li>
              ))}
            </ul>
          ) : null}

          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              href="/analytics/content"
              className="inline-flex items-center gap-1 text-sm font-medium text-slate-900 underline-offset-2 hover:underline dark-tenant:text-slate-100"
            >
              Content performance <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              href="/analytics/campaigns"
              className="inline-flex items-center gap-1 text-sm font-medium text-slate-900 underline-offset-2 hover:underline dark-tenant:text-slate-100"
            >
              Campaign measurement <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </>
      ) : null}
    </PageShell>
  );
}
