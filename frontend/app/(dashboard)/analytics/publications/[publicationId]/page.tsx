"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, FileText } from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
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
  classificationLabel,
  classificationVariant,
  confidencePct,
  formatMetricValue,
  formatWhen,
  freshnessVariant,
  titleCaseKey,
} from "@/lib/measurement-ui";
import { PLATFORM_CONFIG, cn } from "@/lib/utils";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

/** Discrete timeline bars — missing observations are gaps, not interpolated. */
function MetricTimeline({
  points,
}: {
  points: Array<{ observed_at: string; value: number | null }>;
}) {
  const max = Math.max(
    1,
    ...points.map((p) => (p.value != null && !Number.isNaN(p.value) ? p.value : 0)),
  );

  if (points.length === 0) {
    return (
      <p className="text-sm text-slate-500 dark-tenant:text-slate-400">
        No observation timeline yet.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500 dark-tenant:text-slate-400">
        Discrete observations only — gaps mean no snapshot for that time (not zero).
      </p>
      <div className="flex items-end gap-1.5 h-28 overflow-x-auto pb-1">
        {points.map((p) => {
          const missing = p.value == null;
          const height = missing ? 4 : Math.max(8, Math.round((Number(p.value) / max) * 100));
          return (
            <div
              key={`${p.observed_at}-${p.value}`}
              className="flex flex-col items-center gap-1 min-w-[28px]"
              title={`${formatWhen(p.observed_at)}: ${missing ? "no observation" : formatMetricValue(p.value)}`}
            >
              <div
                className={cn(
                  "w-5 rounded-t transition-all",
                  missing
                    ? "bg-slate-200 border border-dashed border-slate-400 dark-tenant:bg-slate-800 dark-tenant:border-slate-600"
                    : "bg-brand-500 dark-tenant:bg-violet-500",
                )}
                style={{ height }}
              />
              <span className="text-[9px] text-slate-400 rotate-[-35deg] origin-top-left whitespace-nowrap">
                {formatWhen(p.observed_at).split(",")[0]}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function PublicationDetailPage() {
  const params = useParams<{ publicationId: string }>();
  const publicationId = params.publicationId;

  const detailQuery = useQuery({
    queryKey: [...MEASUREMENT_QUERY_KEY, "publication", publicationId],
    queryFn: () => measurementApi.getPublication(publicationId).then((r) => r.data),
    enabled: Boolean(publicationId),
    ...QUERY_OPTS,
  });

  const data = detailQuery.data;
  const cfg = data
    ? PLATFORM_CONFIG[data.platform as keyof typeof PLATFORM_CONFIG]
    : undefined;

  const timelineByMetric = useMemo(() => {
    const map = new Map<string, Array<{ observed_at: string; value: number | null }>>();
    for (const point of data?.timeline ?? []) {
      const list = map.get(point.metric_key) ?? [];
      list.push({ observed_at: point.observed_at, value: point.value });
      map.set(point.metric_key, list);
    }
    return map;
  }, [data?.timeline]);

  const primaryTimelineMetric =
    [...timelineByMetric.keys()].find((k) =>
      ["impressions", "views", "reach", "engagements"].includes(k),
    ) ?? [...timelineByMetric.keys()][0];

  return (
    <PageShell wide>
      <PageHeader
        title="Publication measurement"
        subtitle="Identity, observed metrics, freshness, and attribution for a single external publication."
        icon={FileText}
        actions={
          <Link href="/analytics/content" className="btn-secondary text-sm">
            <ArrowLeft size={14} /> Content performance
          </Link>
        }
      />

      {detailQuery.isLoading ? <LoadingState message="Loading publication…" /> : null}

      {detailQuery.isError && !detailQuery.isLoading ? (
        <ErrorState
          title="Unable to load publication"
          message={getApiErrorMessage(detailQuery.error)}
          onRetry={() => detailQuery.refetch()}
        />
      ) : null}

      {!detailQuery.isLoading && !detailQuery.isError && data ? (
        <>
          <div className="rounded-xl border border-slate-200 bg-white p-4 dark-tenant:border-slate-800 dark-tenant:bg-slate-950">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      "text-[10px] px-1.5 py-0.5 rounded font-bold",
                      cfg?.color ?? "bg-gray-100",
                    )}
                  >
                    {cfg?.label ?? data.platform}
                  </span>
                  <StatusBadge variant={freshnessVariant(data.freshness_status)}>
                    {data.freshness_status}
                  </StatusBadge>
                  {data.is_mock ? (
                    <StatusBadge variant="neutral">mock adapter</StatusBadge>
                  ) : null}
                </div>
                <h2 className="mt-2 text-lg font-semibold text-slate-900 dark-tenant:text-slate-100">
                  {data.content_title || data.provider_publication_id}
                </h2>
                <p className="mt-1 text-xs text-slate-500 font-mono truncate">
                  {data.provider_publication_id}
                </p>
              </div>
              {data.provider_permalink ? (
                <a
                  href={data.provider_permalink}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline dark-tenant:text-violet-300"
                >
                  Permalink <ExternalLink size={14} />
                </a>
              ) : null}
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4 text-sm">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Published at</p>
                <p>{formatWhen(data.published_at)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">
                  Last metric observation
                </p>
                <p>{formatWhen(data.last_metric_at)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Account</p>
                <p>{data.account_label ?? "—"}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Status</p>
                <p>{data.publication_status}</p>
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3 text-sm border-t border-slate-100 pt-4 dark-tenant:border-slate-800">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Source content</p>
                {data.content_id ? (
                  <Link
                    href={`/content/${data.content_id}`}
                    className="font-medium hover:underline"
                  >
                    {data.content_title || data.content_id.slice(0, 8)}
                  </Link>
                ) : (
                  <p>—</p>
                )}
                {data.content_variant_id ? (
                  <p className="text-[10px] text-slate-400">
                    variant {data.content_variant_id.slice(0, 8)}
                  </p>
                ) : null}
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Campaign / slot</p>
                <p>{data.campaign_name ?? data.campaign_id ?? "—"}</p>
                {data.campaign_slot_id ? (
                  <p className="text-[10px] text-slate-400">
                    slot {data.campaign_slot_id.slice(0, 8)}
                  </p>
                ) : null}
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Generation</p>
                <p>
                  {data.generation_method
                    ? titleCaseKey(data.generation_method)
                    : "—"}
                  {data.publishing_score_at_publish != null
                    ? ` · pub score ${data.publishing_score_at_publish}`
                    : ""}
                </p>
              </div>
            </div>
          </div>

          <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {(data.normalized_metrics ?? []).slice(0, 4).map((m) => (
              <KpiCard
                key={m.metric_key}
                label={titleCaseKey(m.metric_key)}
                value={formatMetricValue(m.value, m.value_type)}
                sub={m.observed_at ? `obs ${formatWhen(m.observed_at)}` : m.window_key ?? undefined}
              />
            ))}
          </div>

          <div className="mt-6 grid gap-6 xl:grid-cols-2">
            <PageSection title="Metric timeline">
              {primaryTimelineMetric ? (
                <>
                  <p className="mb-2 text-xs text-slate-500">
                    Showing {titleCaseKey(primaryTimelineMetric)}
                  </p>
                  <MetricTimeline points={timelineByMetric.get(primaryTimelineMetric) ?? []} />
                </>
              ) : (
                <EmptyState
                  title="No timeline points"
                  description="Snapshots will appear here after metric ingestion."
                />
              )}
            </PageSection>

            <PageSection title="Attribution">
              {data.attribution ? (
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between gap-2">
                    <span>Method</span>
                    <span className="font-medium">
                      {titleCaseKey(data.attribution.method)}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span>Confidence</span>
                    <span className="font-medium tabular-nums">
                      {confidencePct(data.attribution.confidence)}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span>Status</span>
                    <StatusBadge variant="info">{data.attribution.status}</StatusBadge>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-slate-500">Unattributed — no campaign/slot linkage recorded.</p>
              )}
            </PageSection>
          </div>

          <div className="mt-6 grid gap-6 xl:grid-cols-2">
            <PageSection title="Normalized metrics">
              {(data.normalized_metrics ?? []).length === 0 ? (
                <p className="text-sm text-slate-500">No normalized metrics yet.</p>
              ) : (
                <div className="space-y-2">
                  {data.normalized_metrics.map((m) => (
                    <div
                      key={`n-${m.metric_key}`}
                      className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800"
                    >
                      <div>
                        <p className="font-medium">{titleCaseKey(m.metric_key)}</p>
                        <p className="text-[10px] text-slate-400">
                          {m.normalization_status ?? "normalized"}
                          {m.aggregation_type ? ` · ${m.aggregation_type}` : ""}
                        </p>
                      </div>
                      <span className="tabular-nums font-semibold">
                        {formatMetricValue(m.value, m.value_type)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </PageSection>

            <PageSection title="Provider-native metrics">
              <p className="mb-2 text-xs text-slate-500 dark-tenant:text-slate-400">
                Provider keys as reported by the adapter — kept distinct from catalog keys.
              </p>
              {(data.provider_native_metrics ?? []).length === 0 ? (
                <p className="text-sm text-slate-500">
                  No provider-native metrics available (unsupported or not yet ingested).
                </p>
              ) : (
                <div className="space-y-2">
                  {data.provider_native_metrics.map((m) => (
                    <div
                      key={`p-${m.provider_metric_key ?? m.metric_key}`}
                      className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800"
                    >
                      <div>
                        <p className="font-medium font-mono text-xs">
                          {m.provider_metric_key ?? m.metric_key}
                        </p>
                        {m.metric_key && m.metric_key !== m.provider_metric_key ? (
                          <p className="text-[10px] text-slate-400">
                            → {m.metric_key}
                          </p>
                        ) : null}
                      </div>
                      <span className="tabular-nums font-semibold">
                        {formatMetricValue(m.value, m.value_type)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </PageSection>
          </div>

          <PageSection title="Derived rates (catalog formulas)">
            {(data.derived_rates ?? []).length === 0 ? (
              <p className="text-sm text-slate-500">
                No derived rates — missing contributor metrics yield null, never interpolated.
              </p>
            ) : (
              <div className="space-y-2">
                {data.derived_rates.map((rate) => (
                  <div
                    key={rate.metric_key}
                    className="rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{titleCaseKey(rate.metric_key)}</span>
                      <span className="tabular-nums font-semibold">
                        {formatMetricValue(rate.value, "ratio")}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500 font-mono">{rate.formula}</p>
                    {rate.missing_inputs && rate.missing_inputs.length > 0 ? (
                      <p className="mt-1 text-[10px] text-amber-700 dark-tenant:text-amber-400">
                        Missing inputs: {rate.missing_inputs.join(", ")}
                      </p>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </PageSection>

          <div className="mt-6 grid gap-6 xl:grid-cols-2">
            <PageSection title="Baseline classification">
              {(data.baseline_classifications ?? []).length === 0 ? (
                <p className="text-sm text-slate-500">
                  Insufficient sample for baseline comparison.
                </p>
              ) : (
                <div className="space-y-2">
                  {data.baseline_classifications!.map((b) => (
                    <div
                      key={b.metric_key}
                      className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800"
                    >
                      <span>{titleCaseKey(b.metric_key)}</span>
                      <StatusBadge variant={classificationVariant(b.classification)}>
                        {classificationLabel(b.classification)}
                      </StatusBadge>
                    </div>
                  ))}
                </div>
              )}
            </PageSection>

            <PageSection title="Anomalies">
              {(data.anomalies ?? []).length === 0 ? (
                <p className="text-sm text-slate-500">No open anomalies for this publication.</p>
              ) : (
                <div className="space-y-2">
                  {data.anomalies.map((a) => (
                    <div
                      key={a.id}
                      className="rounded-lg border border-amber-200 bg-amber-50/50 px-3 py-2 text-sm dark-tenant:border-amber-900 dark-tenant:bg-amber-950/30"
                    >
                      <div className="flex justify-between gap-2">
                        <span className="font-medium">{titleCaseKey(a.anomaly_key)}</span>
                        <StatusBadge
                          variant={
                            a.severity === "critical" || a.severity === "error"
                              ? "danger"
                              : "warning"
                          }
                        >
                          {a.severity}
                        </StatusBadge>
                      </div>
                      <p className="mt-1 text-xs text-slate-600 dark-tenant:text-slate-300">
                        {a.message ?? a.status}
                      </p>
                      <p className="text-[10px] text-slate-400">{formatWhen(a.detected_at)}</p>
                    </div>
                  ))}
                </div>
              )}
            </PageSection>
          </div>
        </>
      ) : null}
    </PageShell>
  );
}
