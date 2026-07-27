"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LineChart } from "lucide-react";

import { HorizontalBarChart, SimpleBarChart } from "@/components/analytics/SimpleBarChart";
import { ListeningSubNav } from "@/components/listening/ListeningSubNav";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  KpiCard,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import {
  LISTENING_QUERY_KEY,
  getApiErrorMessage,
  listeningApi,
  type ListeningCoverage,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

function coverageVariant(status: string | undefined): "success" | "warning" | "danger" | "neutral" {
  if (status === "sufficient") return "success";
  if (status === "partial") return "warning";
  if (status === "insufficient" || status === "unavailable") return "danger";
  return "neutral";
}

function formatChange(
  kind: string | undefined,
  pct: number | null | undefined,
  unavailableLabel: string,
  newActivityLabel: string,
): string {
  if (kind === "new_activity") return newActivityLabel;
  if (kind === "unavailable" || kind === "zero_baseline_zero_current" || pct == null) {
    return unavailableLabel;
  }
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

function CoverageBanner({
  coverage,
  t,
}: {
  coverage: ListeningCoverage;
  t: (key: string, vars?: Record<string, string | number>) => string;
}) {
  return (
    <div
      className={
        coverage.status === "sufficient"
          ? "mb-6 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900 dark-tenant:border-emerald-900 dark-tenant:bg-emerald-950/40 dark-tenant:text-emerald-100"
          : coverage.status === "partial"
            ? "mb-6 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark-tenant:border-amber-900 dark-tenant:bg-amber-950/40 dark-tenant:text-amber-100"
            : "mb-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900 dark-tenant:border-rose-900 dark-tenant:bg-rose-950/40 dark-tenant:text-rose-100"
      }
      role="status"
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge variant={coverageVariant(coverage.status)}>
          {t(`listening.coverage.${coverage.status}`)}
        </StatusBadge>
        <span>
          {t("listening.intelEligibleCount", { count: coverage.eligible_mention_count })}
        </span>
        <span className="text-xs opacity-80">
          {t("listening.intelFreshness")}: {coverage.freshness_status}
        </span>
      </div>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">
        {(coverage.limitations || []).slice(0, 4).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

export default function ListeningIntelligencePage() {
  const { t } = useTranslation();
  const [windowKey, setWindowKey] = useState<"7d" | "30d" | "90d">("30d");

  const params = useMemo(() => ({ window_key: windowKey, include_fixture: false }), [windowKey]);

  const overviewQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "intelligence", "overview", params],
    queryFn: () => listeningApi.intelligenceOverview(params).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const seriesQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "intelligence", "series", params],
    queryFn: () => listeningApi.intelligenceTimeSeries(params).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const subjectsQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "intelligence", "subjects", params],
    queryFn: () => listeningApi.intelligenceSubjects(params).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const data = overviewQuery.data;
  const loading = overviewQuery.isLoading;
  const error = overviewQuery.isError;

  const trendData =
    seriesQuery.data?.buckets.map((b) => ({
      label: (b.bucket_start || "").slice(5, 10),
      value: b.total_observed_mentions,
      sublabel: String(b.total_observed_mentions),
    })) || [];

  const sovShares = data?.observed_share_of_voice?.shares || [];
  const sovChart = sovShares.map((s) => ({
    label: s.canonical_name,
    value: s.observed_share_pct ?? 0,
    sublabel:
      s.observed_share_pct == null
        ? t("listening.intelUnavailable")
        : `${s.observed_share_pct}%`,
  }));

  return (
    <PageShell wide>
      <PageHeader
        title={t("listening.intelTitle")}
        subtitle={t("listening.intelSubtitle")}
        icon={LineChart}
        badge={<StatusBadge variant="neutral">{t("listening.readOnlyBadge")}</StatusBadge>}
        actions={
          <div className="flex flex-wrap gap-2">
            {(["7d", "30d", "90d"] as const).map((key) => (
              <button
                key={key}
                type="button"
                className={
                  windowKey === key
                    ? "btn-primary text-sm"
                    : "btn-secondary text-sm"
                }
                onClick={() => setWindowKey(key)}
                aria-pressed={windowKey === key}
              >
                {t(`listening.window.${key}`)}
              </button>
            ))}
          </div>
        }
      />
      <ListeningSubNav />

      {loading ? <LoadingState message={t("listening.loadingIntelligence")} /> : null}
      {error && !loading ? (
        <ErrorState
          title={t("listening.loadError")}
          message={getApiErrorMessage(overviewQuery.error)}
          onRetry={() => overviewQuery.refetch()}
        />
      ) : null}

      {data ? (
        <>
          <CoverageBanner coverage={data.coverage} t={t} />

          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard
              label={t("listening.intelEligible")}
              value={String(data.eligible_mention_count)}
            />
            <KpiCard
              label={t("listening.intelPrevious")}
              value={
                data.comparison_valid && data.previous_eligible_mention_count != null
                  ? String(data.previous_eligible_mention_count)
                  : t("listening.intelUnavailable")
              }
            />
            <KpiCard
              label={t("listening.intelCoverage")}
              value={t(`listening.coverage.${data.coverage.status}`)}
            />
            <KpiCard
              label={t("listening.intelSentiment")}
              value={t("listening.intelSentimentDeferred")}
            />
          </div>

          <PageSection title={t("listening.intelTrends")} className="mb-6">
            {seriesQuery.isLoading ? (
              <LoadingState message={t("listening.loadingIntelligence")} />
            ) : trendData.length === 0 ? (
              <EmptyState
                title={t("listening.intelEmptyTrends")}
                description={t("listening.intelEmptyTrendsHint")}
              />
            ) : (
              <>
                <p className="mb-3 text-sm text-slate-600 dark-tenant:text-slate-300">
                  {seriesQuery.data?.textual_summary}
                </p>
                <SimpleBarChart data={trendData} valueSuffix="" />
              </>
            )}
          </PageSection>

          <PageSection title={t("listening.intelCompetitors")} className="mb-6">
            <p className="mb-2 text-sm text-slate-600 dark-tenant:text-slate-300">
              {t("listening.intelSovLabel")}
            </p>
            {data.observed_share_of_voice?.available ? (
              <>
                <p className="mb-3 text-xs text-slate-500">
                  {t("listening.intelSovDenominator", {
                    denominator: data.observed_share_of_voice.denominator ?? 0,
                    count: data.observed_share_of_voice.comparison_set?.length ?? 0,
                  })}
                </p>
                <HorizontalBarChart data={sovChart} />
              </>
            ) : (
              <EmptyState
                title={t("listening.intelSovUnavailable")}
                description={(data.observed_share_of_voice?.limitations || []).join(" ")}
              />
            )}

            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 dark-tenant:border-slate-700">
                    <th className="py-2 pr-3">{t("listening.colSubject")}</th>
                    <th className="py-2 pr-3">{t("listening.colObserved")}</th>
                    <th className="py-2 pr-3">{t("listening.colChange")}</th>
                    <th className="py-2 pr-3">{t("listening.intelSovShort")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(subjectsQuery.data?.subjects || data.top_subjects || []).map((s) => (
                    <tr key={s.subject_id} className="border-b border-slate-100 dark-tenant:border-slate-800">
                      <td className="py-2 pr-3">
                        <div className="font-medium">{s.canonical_name}</div>
                        <div className="text-xs text-slate-500">{s.subject_type}</div>
                      </td>
                      <td className="py-2 pr-3">{s.observed_mention_count}</td>
                      <td className="py-2 pr-3">
                        {formatChange(
                          s.change_kind,
                          s.percentage_change,
                          t("listening.intelUnavailable"),
                          t("listening.intelNewActivity"),
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        {s.observed_share == null
                          ? t("listening.intelUnavailable")
                          : `${s.observed_share.toFixed(1)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!data.comparison_valid ? (
                <p className="mt-2 text-xs text-amber-700 dark-tenant:text-amber-300">
                  {t("listening.intelComparisonInvalid")}
                </p>
              ) : null}
            </div>
          </PageSection>

          <div className="mb-6 grid gap-6 lg:grid-cols-2">
            <PageSection title={t("listening.intelTopics")}>
              {(data.emerging_topics || []).length === 0 ? (
                <EmptyState
                  title={t("listening.intelEmptyTopics")}
                  description={t("listening.intelEmptyTopicsHint")}
                />
              ) : (
                <ul className="space-y-3">
                  {data.emerging_topics.map((topic) => (
                    <li
                      key={topic.topic_id}
                      className="rounded-md border border-slate-200 p-3 dark-tenant:border-slate-700"
                    >
                      <div className="font-medium">{topic.label}</div>
                      <p className="mt-1 text-sm text-slate-600 dark-tenant:text-slate-300">
                        {topic.detection_reason}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {t("listening.intelTopicCounts", {
                          current: topic.current_count,
                          baseline: topic.baseline_count,
                        })}
                      </p>
                      {topic.representative_mention_ids?.[0] ? (
                        <Link
                          href={`/listening/mentions/${topic.representative_mention_ids[0]}`}
                          className="mt-2 inline-block text-xs text-sky-700 underline dark-tenant:text-sky-300"
                        >
                          {t("listening.intelViewEvidence")}
                        </Link>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </PageSection>

            <PageSection title={t("listening.intelAnomalies")}>
              <div className="mb-3">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {t("listening.intelMarketSignals")}
                </h3>
                {(data.notable_anomalies || []).length === 0 ? (
                  <p className="mt-2 text-sm text-slate-500">{t("listening.intelNoMarketAnomalies")}</p>
                ) : (
                  <ul className="mt-2 space-y-2">
                    {data.notable_anomalies.map((a) => (
                      <li key={a.code} className="rounded-md border border-slate-200 p-2 text-sm dark-tenant:border-slate-700">
                        <StatusBadge variant="warning">{a.severity}</StatusBadge>{" "}
                        {a.explanation}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-rose-600 dark-tenant:text-rose-300">
                  {t("listening.intelDataQuality")}
                </h3>
                {(data.data_quality_anomalies || []).length === 0 ? (
                  <p className="mt-2 text-sm text-slate-500">{t("listening.intelNoDqAnomalies")}</p>
                ) : (
                  <ul className="mt-2 space-y-2">
                    {data.data_quality_anomalies.map((a) => (
                      <li
                        key={a.code}
                        className="rounded-md border border-rose-200 bg-rose-50 p-2 text-sm text-rose-900 dark-tenant:border-rose-900 dark-tenant:bg-rose-950/40 dark-tenant:text-rose-100"
                      >
                        {a.explanation}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </PageSection>
          </div>

          <PageSection title={t("listening.intelInsights")}>
            {(data.insights || []).length === 0 ? (
              <EmptyState
                title={t("listening.intelEmptyInsights")}
                description={t("listening.intelEmptyInsightsHint")}
              />
            ) : (
              <ul className="space-y-3">
                {data.insights.map((insight) => (
                  <li
                    key={insight.insight_key}
                    className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-slate-200 p-3 dark-tenant:border-slate-700"
                  >
                    <div>
                      <div className="font-medium">{insight.title}</div>
                      <p className="mt-1 text-sm text-slate-600 dark-tenant:text-slate-300">
                        {insight.explanation}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {insight.methodology_version} · {insight.analyst_review_state} ·{" "}
                        {insight.coverage_status}
                      </p>
                    </div>
                    <Link
                      href={`/listening/intelligence/insights/${insight.insight_key}?window_key=${windowKey}`}
                      className="btn-secondary text-sm"
                    >
                      {t("listening.intelOpenInsight")}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </PageSection>
        </>
      ) : null}
    </PageShell>
  );
}
