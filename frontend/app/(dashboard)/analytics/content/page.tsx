"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  ActionBar,
  DataTable,
  DataTableBody,
  DataTableHead,
  DataTableRow,
  DataTableTd,
  DataTableTh,
  FilterBar,
  PageHeader,
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
  MEASUREMENT_SORT_METRICS,
  classificationLabel,
  classificationVariant,
  confidencePct,
  formatMetricValue,
  formatShortDate,
  freshnessVariant,
  parsePeriodDays,
  titleCaseKey,
} from "@/lib/measurement-ui";
import { PLATFORM_CONFIG, cn } from "@/lib/utils";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function ContentPerformancePage() {
  const [period, setPeriod] = useState("30");
  const [sortMetric, setSortMetric] = useState("published_at");
  const days = parsePeriodDays(period);

  const query = useQuery({
    queryKey: [...MEASUREMENT_QUERY_KEY, "content-performance", days, sortMetric],
    queryFn: () =>
      measurementApi
        .contentPerformance({
          days,
          sort_metric: sortMetric,
          sort_dir: sortMetric === "published_at" ? "desc" : "desc",
          page: 1,
          page_size: 50,
        })
        .then((r) => r.data),
    ...QUERY_OPTS,
  });

  const rows = query.data?.items ?? [];
  const metricColumns =
    sortMetric === "published_at"
      ? ["impressions", "reach", "views", "engagements"]
      : [sortMetric, ...["impressions", "reach", "views", "engagements"].filter((m) => m !== sortMetric)].slice(
          0,
          4,
        );

  return (
    <PageShell wide>
      <PageHeader
        title="Content performance"
        subtitle="Observed metrics for measured publications. Sort by a metric you choose — rankings are descriptive only."
        icon={BarChart3}
        actions={
          <Link href="/analytics/performance" className="btn-secondary text-sm">
            Overview
          </Link>
        }
      />

      <ActionBar>
        <div className="flex w-full flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <FilterBar options={MEASUREMENT_PERIOD_OPTIONS} value={period} onChange={setPeriod} />
          <label className="flex items-center gap-2 text-xs text-slate-600 dark-tenant:text-slate-300">
            Sort by
            <select
              className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm dark-tenant:border-slate-700 dark-tenant:bg-slate-950"
              value={sortMetric}
              onChange={(e) => setSortMetric(e.target.value)}
            >
              {MEASUREMENT_SORT_METRICS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </ActionBar>

      <p className="mb-3 text-xs text-slate-500 dark-tenant:text-slate-400">
        Rows include publications whose <span className="font-medium">publish date</span> falls in
        the selected window. Metric cells show the latest{" "}
        <span className="font-medium">observation</span>, which may be outside that window.
      </p>

      {query.isLoading ? <LoadingState message="Loading content performance…" /> : null}

      {query.isError && !query.isLoading ? (
        <ErrorState
          title="Unable to load content performance"
          message={getApiErrorMessage(query.error)}
          onRetry={() => query.refetch()}
        />
      ) : null}

      {!query.isLoading && !query.isError ? (
        rows.length === 0 ? (
          <EmptyState
            title="No measured publications"
            description="After successful publishes are registered for measurement, observed metrics appear here."
          />
        ) : (
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>Publication</DataTableTh>
                <DataTableTh>Platform</DataTableTh>
                <DataTableTh>Account</DataTableTh>
                <DataTableTh>Published</DataTableTh>
                <DataTableTh>Campaign</DataTableTh>
                <DataTableTh>Freshness</DataTableTh>
                {metricColumns.map((key) => (
                  <DataTableTh key={key}>{titleCaseKey(key)}</DataTableTh>
                ))}
                <DataTableTh>Attribution</DataTableTh>
                <DataTableTh>Baseline</DataTableTh>
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {rows.map((row) => {
                const cfg = PLATFORM_CONFIG[row.platform as keyof typeof PLATFORM_CONFIG];
                return (
                  <DataTableRow key={row.publication_id}>
                    <DataTableTd>
                      <Link
                        href={`/analytics/publications/${row.publication_id}`}
                        className="font-medium text-slate-900 underline-offset-2 hover:underline dark-tenant:text-slate-100"
                      >
                        {row.content_title ||
                          row.provider_publication_id ||
                          row.publication_id.slice(0, 8)}
                      </Link>
                      {row.is_mock ? (
                        <span className="ml-2 text-[10px] text-slate-400">mock</span>
                      ) : null}
                    </DataTableTd>
                    <DataTableTd>
                      <span
                        className={cn(
                          "text-[10px] px-1.5 py-0.5 rounded font-bold",
                          cfg?.color ?? "bg-gray-100",
                        )}
                      >
                        {cfg?.label ?? row.platform}
                      </span>
                    </DataTableTd>
                    <DataTableTd>{row.account_label ?? "—"}</DataTableTd>
                    <DataTableTd>
                      <div>{formatShortDate(row.published_at)}</div>
                      {row.last_metric_at ? (
                        <div className="text-[10px] text-slate-400">
                          obs {formatShortDate(row.last_metric_at)}
                        </div>
                      ) : null}
                    </DataTableTd>
                    <DataTableTd>{row.campaign_name ?? "—"}</DataTableTd>
                    <DataTableTd>
                      <StatusBadge variant={freshnessVariant(row.freshness_status)}>
                        {row.freshness_status}
                      </StatusBadge>
                    </DataTableTd>
                    {metricColumns.map((key) => (
                      <DataTableTd key={key} className="tabular-nums">
                        {formatMetricValue(row.latest_metrics?.[key])}
                      </DataTableTd>
                    ))}
                    <DataTableTd>
                      <div className="text-xs">
                        {row.attribution_method
                          ? titleCaseKey(row.attribution_method)
                          : "unattributed"}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        conf {confidencePct(row.attribution_confidence)}
                      </div>
                    </DataTableTd>
                    <DataTableTd>
                      <StatusBadge variant={classificationVariant(row.baseline_classification)}>
                        {classificationLabel(row.baseline_classification)}
                      </StatusBadge>
                    </DataTableTd>
                  </DataTableRow>
                );
              })}
            </DataTableBody>
          </DataTable>
        )
      ) : null}
    </PageShell>
  );
}
