"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Target } from "lucide-react";

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
  CAMPAIGN_PLANNER_QUERY_KEY,
  MEASUREMENT_QUERY_KEY,
  campaignPlannerApi,
  getApiErrorMessage,
  measurementApi,
  normalizeList,
  type MarketingCampaign,
} from "@/lib/api";
import {
  confidencePct,
  formatMetricValue,
  freshnessVariant,
  kpiStatusVariant,
  titleCaseKey,
} from "@/lib/measurement-ui";
import { cn } from "@/lib/utils";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function CampaignMeasurementPage() {
  const [selectedId, setSelectedId] = useState<string>("");

  const campaignsQuery = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, "campaigns", "measurement"],
    queryFn: () =>
      campaignPlannerApi.listCampaigns({ limit: 100 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const campaigns = normalizeList<MarketingCampaign>(campaignsQuery.data);
  const activeId = selectedId || campaigns[0]?.id || "";

  const filterOptions = useMemo(
    () =>
      campaigns.map((c) => ({
        label: c.name,
        value: c.id,
      })),
    [campaigns],
  );

  const measurementQuery = useQuery({
    queryKey: [...MEASUREMENT_QUERY_KEY, "campaign", activeId],
    queryFn: () => measurementApi.getCampaign(activeId).then((r) => r.data),
    enabled: Boolean(activeId),
    ...QUERY_OPTS,
  });

  const data = measurementQuery.data;

  return (
    <PageShell wide>
      <PageHeader
        title="Campaign measurement"
        subtitle="Attributed observed metrics and measured activity for campaign-linked publications. Not causal impact."
        icon={Target}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link href="/analytics/performance" className="btn-secondary text-sm">
              Overview
            </Link>
            <Link href="/campaign-planner" className="btn-secondary text-sm">
              Campaign Planner
            </Link>
          </div>
        }
      />

      {campaignsQuery.isLoading ? <LoadingState message="Loading campaigns…" /> : null}

      {campaignsQuery.isError && !campaignsQuery.isLoading ? (
        <ErrorState
          title="Unable to load campaigns"
          message={getApiErrorMessage(campaignsQuery.error)}
          onRetry={() => campaignsQuery.refetch()}
        />
      ) : null}

      {!campaignsQuery.isLoading && !campaignsQuery.isError && campaigns.length === 0 ? (
        <EmptyState
          title="No campaigns yet"
          description="Create a campaign in Campaign Planner to see attributed observed metrics here."
          action={
            <Link href="/campaign-planner" className="btn-primary text-sm mt-2">
              Open Campaign Planner
            </Link>
          }
        />
      ) : null}

      {!campaignsQuery.isLoading && !campaignsQuery.isError && campaigns.length > 0 ? (
        <>
          <ActionBar>
            <FilterBar
              options={filterOptions}
              value={activeId}
              onChange={setSelectedId}
            />
          </ActionBar>

          {measurementQuery.isLoading ? (
            <LoadingState message="Loading campaign measurement…" />
          ) : null}

          {measurementQuery.isError && !measurementQuery.isLoading ? (
            <ErrorState
              title="Unable to load campaign measurement"
              message={getApiErrorMessage(measurementQuery.error)}
              onRetry={() => measurementQuery.refetch()}
            />
          ) : null}

          {!measurementQuery.isLoading && !measurementQuery.isError && data ? (
            <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <KpiCard
                  label="Attributed publications"
                  value={data.attributed_publications}
                  icon={BarChart3}
                />
                <KpiCard
                  label="Unattributed publications"
                  value={data.unattributed_publications}
                  icon={BarChart3}
                />
                <KpiCard
                  label="Avg attribution confidence"
                  value={confidencePct(data.attribution_confidence_avg)}
                  icon={Target}
                />
                <KpiCard
                  label="Fresh / stale / unsupported"
                  value={`${data.freshness.fresh} / ${data.freshness.stale} / ${data.freshness.unsupported}`}
                  icon={BarChart3}
                />
              </div>

              <div className="mt-6 grid gap-6 xl:grid-cols-2">
                <PageSection title="KPI targets vs observed progress">
                  <p className="mb-3 text-xs text-slate-500 dark-tenant:text-slate-400">
                    Progress reflects measured activity only. Lead/sales KPIs are never marked
                    achieved from engagement proxies.
                  </p>
                  {data.kpi_progress.length === 0 ? (
                    <EmptyState
                      title="No KPIs configured"
                      description="Add KPIs in Campaign Planner to track observed progress against targets."
                    />
                  ) : (
                    <div className="space-y-3">
                      {data.kpi_progress.map((kpi) => {
                        const pct =
                          kpi.progress_ratio != null
                            ? Math.min(100, Math.max(0, kpi.progress_ratio * 100))
                            : null;
                        return (
                          <div
                            key={kpi.kpi_id}
                            className="rounded-xl border border-slate-200 bg-white p-4 dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div>
                                <p className="font-medium text-slate-900 dark-tenant:text-slate-100">
                                  {kpi.name || titleCaseKey(kpi.metric_key)}
                                </p>
                                <p className="text-xs text-slate-500">
                                  {titleCaseKey(kpi.metric_key)} · {kpi.comparator}{" "}
                                  {formatMetricValue(kpi.target_value)}
                                </p>
                              </div>
                              <StatusBadge variant={kpiStatusVariant(kpi.status)}>
                                {titleCaseKey(kpi.status)}
                              </StatusBadge>
                            </div>
                            <div className="mt-3 flex items-end justify-between gap-3">
                              <div>
                                <p className="text-[10px] uppercase tracking-wide text-slate-400">
                                  Observed
                                </p>
                                <p className="text-xl font-semibold tabular-nums">
                                  {formatMetricValue(kpi.current_value)}
                                </p>
                              </div>
                              <div className="text-right text-xs text-slate-500">
                                <div>conf {confidencePct(kpi.confidence)}</div>
                                <StatusBadge variant={freshnessVariant(kpi.freshness_status)}>
                                  {kpi.freshness_status}
                                </StatusBadge>
                              </div>
                            </div>
                            {pct != null ? (
                              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100 dark-tenant:bg-white/[0.06]">
                                <div
                                  className={cn(
                                    "h-full rounded-full transition-all",
                                    kpi.status === "target_reached" ||
                                      kpi.status === "target_exceeded"
                                      ? "bg-emerald-500"
                                      : "bg-brand-500",
                                  )}
                                  style={{ width: `${pct}%` }}
                                />
                              </div>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </PageSection>

                <PageSection title="Attributed observed metrics">
                  <p className="mb-3 text-xs text-slate-500 dark-tenant:text-slate-400">
                    Sum of observed metrics on publications attributed to this campaign. Descriptive
                    grouping only — not causal contribution.
                  </p>
                  {data.attributed_observed_metrics.length === 0 ? (
                    <p className="text-sm text-slate-500">
                      No attributed observed metrics yet for this campaign.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {data.attributed_observed_metrics.map((m) => (
                        <div
                          key={m.metric_key}
                          className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800"
                        >
                          <span>{titleCaseKey(m.metric_key)}</span>
                          <span className="tabular-nums font-medium">
                            {formatMetricValue(m.value, m.value_type)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {data.measurement_gaps.length > 0 ? (
                    <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-3 dark-tenant:border-amber-900 dark-tenant:bg-amber-950/30">
                      <p className="text-xs font-semibold uppercase tracking-wide text-amber-800 dark-tenant:text-amber-300">
                        Measurement gaps
                      </p>
                      <ul className="mt-2 space-y-1 text-sm text-amber-900 dark-tenant:text-amber-200">
                        {data.measurement_gaps.map((gap) => (
                          <li key={gap}>• {gap}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {data.notes && data.notes.length > 0 ? (
                    <ul className="mt-3 space-y-1 text-xs text-slate-500">
                      {data.notes.map((note) => (
                        <li key={note}>• {note}</li>
                      ))}
                    </ul>
                  ) : null}
                </PageSection>
              </div>
            </>
          ) : null}
        </>
      ) : null}
    </PageShell>
  );
}
