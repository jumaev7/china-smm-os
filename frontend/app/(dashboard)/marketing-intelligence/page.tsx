"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Brain,
  CheckCircle2,
  Lightbulb,
  Radio,
  TrendingUp,
} from "lucide-react";
import { format, parseISO } from "date-fns";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { KpiCard, PageHeader, PageSection, PageShell } from "@/components/ui/design-system";
import {
  INTELLIGENCE_QUERY_KEY,
  getApiErrorMessage,
  intelligenceApi,
  type MarketingRecommendation,
  type MarketingScore,
  type MarketingSignal,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

function formatWhen(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "MMM d, HH:mm");
  } catch {
    return iso;
  }
}

function scoreTone(score: number): string {
  if (score >= 75) return "text-emerald-700 dark-tenant:text-emerald-400";
  if (score >= 55) return "text-amber-700 dark-tenant:text-amber-400";
  return "text-rose-700 dark-tenant:text-rose-400";
}

function priorityTone(priority: string): string {
  if (priority === "critical") return "bg-rose-100 text-rose-800 dark-tenant:bg-rose-950 dark-tenant:text-rose-300";
  if (priority === "high") return "bg-orange-100 text-orange-800 dark-tenant:bg-orange-950 dark-tenant:text-orange-300";
  if (priority === "medium") return "bg-amber-100 text-amber-800 dark-tenant:bg-amber-950 dark-tenant:text-amber-300";
  return "bg-slate-100 text-slate-700 dark-tenant:bg-slate-800 dark-tenant:text-slate-300";
}

function severityTone(severity: string): string {
  if (severity === "critical" || severity === "error") {
    return "border-rose-200 dark-tenant:border-rose-900";
  }
  if (severity === "warning") return "border-amber-200 dark-tenant:border-amber-900";
  if (severity === "success") return "border-emerald-200 dark-tenant:border-emerald-900";
  return "border-slate-200 dark-tenant:border-slate-800";
}

function ScoreCard({ score }: { score: MarketingScore }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark-tenant:border-slate-800 dark-tenant:bg-slate-950">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500 dark-tenant:text-slate-400">
            {score.category.replace(/_/g, " ")}
          </p>
          <p className={cn("mt-1 text-3xl font-semibold tabular-nums", scoreTone(score.score))}>
            {score.score}
          </p>
        </div>
        <span className="text-xs text-slate-400">w {score.weight.toFixed(2)}</span>
      </div>
      {score.explanation?.reasoning ? (
        <p className="mt-3 text-sm leading-relaxed text-slate-600 dark-tenant:text-slate-300">
          {score.explanation.reasoning}
        </p>
      ) : null}
    </div>
  );
}

function RecommendationCard({ item }: { item: MarketingRecommendation }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark-tenant:border-slate-800 dark-tenant:bg-slate-950">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-md px-2 py-0.5 text-xs font-medium", priorityTone(item.priority))}>
          {item.priority}
        </span>
        <span className="text-xs text-slate-500">{item.category}</span>
        <span className="text-xs text-slate-400">conf {(item.confidence * 100).toFixed(0)}%</span>
      </div>
      <h3 className="mt-2 text-base font-semibold text-slate-900 dark-tenant:text-slate-100">
        {item.title}
      </h3>
      <p className="mt-1 text-sm text-slate-600 dark-tenant:text-slate-300">{item.reason}</p>
      {item.explanation?.recommendation ? (
        <p className="mt-2 text-sm text-slate-700 dark-tenant:text-slate-200">
          → {item.explanation.recommendation}
        </p>
      ) : null}
      {item.action_url ? (
        <Link
          href={item.action_url}
          className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-slate-900 underline-offset-2 hover:underline dark-tenant:text-slate-100"
        >
          Open <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      ) : null}
    </div>
  );
}

function SignalRow({ signal }: { signal: MarketingSignal }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-lg border border-l-4 bg-white px-3 py-2 dark-tenant:bg-slate-950",
        severityTone(signal.severity),
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium text-slate-900 dark-tenant:text-slate-100">{signal.signal_type}</p>
        <span className="text-xs text-slate-500">{formatWhen(signal.occurred_at)}</span>
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-slate-500">
        <span>{signal.source}</span>
        <span>{signal.severity}</span>
        {signal.entity_type ? <span>{signal.entity_type}</span> : null}
      </div>
    </div>
  );
}

export default function MarketingIntelligencePage() {
  const { t } = useTranslation();

  const healthQuery = useQuery({
    queryKey: [...INTELLIGENCE_QUERY_KEY, "health"],
    queryFn: () => intelligenceApi.health().then((r) => r.data),
    ...QUERY_OPTS,
  });
  const scoresQuery = useQuery({
    queryKey: [...INTELLIGENCE_QUERY_KEY, "scores"],
    queryFn: () => intelligenceApi.scores().then((r) => r.data),
    ...QUERY_OPTS,
  });
  const signalsQuery = useQuery({
    queryKey: [...INTELLIGENCE_QUERY_KEY, "signals"],
    queryFn: () => intelligenceApi.signals({ page_size: 12 }).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const recommendationsQuery = useQuery({
    queryKey: [...INTELLIGENCE_QUERY_KEY, "recommendations"],
    queryFn: () =>
      intelligenceApi.recommendations({ status: "open", page_size: 12 }).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const insightsQuery = useQuery({
    queryKey: [...INTELLIGENCE_QUERY_KEY, "insights"],
    queryFn: () => intelligenceApi.insights({ page_size: 8 }).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const historyQuery = useQuery({
    queryKey: [...INTELLIGENCE_QUERY_KEY, "history"],
    queryFn: () => intelligenceApi.history({ days: 30 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const loading =
    healthQuery.isLoading ||
    scoresQuery.isLoading ||
    signalsQuery.isLoading ||
    recommendationsQuery.isLoading;
  const error =
    healthQuery.error ||
    scoresQuery.error ||
    signalsQuery.error ||
    recommendationsQuery.error;

  const health = healthQuery.data;
  const scores = scoresQuery.data?.items ?? [];
  const signals = signalsQuery.data?.items ?? [];
  const recommendations = recommendationsQuery.data?.items ?? [];
  const insights = insightsQuery.data?.items ?? [];
  const trendPoints = (historyQuery.data?.trends ?? []).filter((t) => t.metric_key === "score.overall");

  const publishingSignals = signals.filter((s) => s.signal_type.startsWith("publishing."));
  const reviewCompleted = publishingSignals.filter((s) => s.signal_type === "publishing.review_completed");
  const scoreLow = publishingSignals.filter((s) => s.signal_type === "publishing.score_low");
  const criticalIssues = publishingSignals.filter(
    (s) => s.signal_type === "publishing.critical_issue_detected",
  );
  const platformFitWarnings = publishingSignals.filter(
    (s) => s.signal_type === "publishing.platform_fit_low",
  );
  const avgPublishingScore = (() => {
    const scoresFromSignals = reviewCompleted
      .map((s) => {
        const payload = (s.metadata as { payload?: { overall_score?: number } } | null)?.payload;
        return payload?.overall_score;
      })
      .filter((n): n is number => typeof n === "number");
    if (scoresFromSignals.length === 0) return null;
    return Math.round(
      scoresFromSignals.reduce((a, b) => a + b, 0) / scoresFromSignals.length,
    );
  })();
  const publishingRecCategories = recommendations
    .filter((r) => r.category === "publishing")
    .reduce<Record<string, number>>((acc, r) => {
      acc[r.recommendation_key] = (acc[r.recommendation_key] || 0) + 1;
      return acc;
    }, {});

  const retry = () => {
    void healthQuery.refetch();
    void scoresQuery.refetch();
    void signalsQuery.refetch();
    void recommendationsQuery.refetch();
    void insightsQuery.refetch();
    void historyQuery.refetch();
  };

  return (
    <PageShell wide>
      <PageHeader
        title={t("marketingIntelligence.title")}
        subtitle={t("marketingIntelligence.subtitle")}
        icon={Brain}
      />

      {loading ? <LoadingState /> : null}

      {error && !loading ? (
        <ErrorState
          title={t("marketingIntelligence.errorTitle")}
          message={getApiErrorMessage(error)}
          onRetry={retry}
        />
      ) : null}

      {!loading && !error && health ? (
        <>
          <PageSection title={t("marketingIntelligence.health")}>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <KpiCard
                label={t("marketingIntelligence.overallScore")}
                value={String(health.overall_score)}
                sub={health.status}
                icon={Activity}
              />
              <KpiCard
                label={t("marketingIntelligence.openRecommendations")}
                value={String(health.open_recommendations)}
                icon={Lightbulb}
              />
              <KpiCard
                label={t("marketingIntelligence.recentSignals")}
                value={String(health.recent_signals_7d)}
                icon={Radio}
              />
              <KpiCard
                label={t("marketingIntelligence.engine")}
                value={health.scoring_version}
                sub={`rec ${health.recommendation_engine_version}`}
                icon={CheckCircle2}
              />
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {scores
                .filter((s) => s.category !== "overall")
                .map((score) => (
                  <ScoreCard key={score.category} score={score} />
                ))}
            </div>
          </PageSection>

          <PageSection title="Publishing Intelligence">
            <p className="mb-3 text-sm text-slate-500 dark-tenant:text-slate-400">
              Deterministic pre-publish quality signals (rule-based, no AI rewrite).
            </p>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <KpiCard
                label="Avg publishing score"
                value={avgPublishingScore != null ? String(avgPublishingScore) : "—"}
                sub={`${reviewCompleted.length} recent reviews`}
                icon={Activity}
              />
              <KpiCard
                label="Low-score content"
                value={String(scoreLow.length)}
                icon={AlertTriangle}
              />
              <KpiCard
                label="Critical review issues"
                value={String(criticalIssues.length)}
                icon={AlertTriangle}
              />
              <KpiCard
                label="Platform-fit warnings"
                value={String(platformFitWarnings.length)}
                icon={Radio}
              />
            </div>
            {Object.keys(publishingRecCategories).length > 0 ? (
              <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4 dark-tenant:border-slate-800 dark-tenant:bg-slate-950">
                <p className="text-xs uppercase tracking-wide text-slate-500">
                  Frequent publishing recommendation keys
                </p>
                <ul className="mt-2 space-y-1 text-sm">
                  {Object.entries(publishingRecCategories)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 6)
                    .map(([key, count]) => (
                      <li key={key} className="flex justify-between gap-3 text-slate-700 dark-tenant:text-slate-300">
                        <span className="truncate">{key}</span>
                        <span className="tabular-nums text-slate-500">{count}</span>
                      </li>
                    ))}
                </ul>
              </div>
            ) : null}
          </PageSection>

          <div className="grid gap-6 xl:grid-cols-2">
            <PageSection title={t("marketingIntelligence.recommendations")}>
              {recommendations.length === 0 ? (
                <EmptyState
                  title={t("marketingIntelligence.noRecommendations")}
                  description={t("marketingIntelligence.noRecommendationsBody")}
                />
              ) : (
                <div className="space-y-3">
                  {recommendations.map((item) => (
                    <RecommendationCard key={item.id} item={item} />
                  ))}
                </div>
              )}
            </PageSection>

            <PageSection title={t("marketingIntelligence.signals")}>
              {signals.length === 0 ? (
                <EmptyState
                  title={t("marketingIntelligence.noSignals")}
                  description={t("marketingIntelligence.noSignalsBody")}
                />
              ) : (
                <div className="space-y-2">
                  {signals.map((signal) => (
                    <SignalRow key={signal.id} signal={signal} />
                  ))}
                </div>
              )}
            </PageSection>
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <PageSection title={t("marketingIntelligence.insights")}>
              {insights.length === 0 ? (
                <EmptyState
                  title={t("marketingIntelligence.noInsights")}
                  description={t("marketingIntelligence.noInsightsBody")}
                />
              ) : (
                <div className="space-y-3">
                  {insights.map((insight) => (
                    <div
                      key={insight.id}
                      className="rounded-xl border border-slate-200 bg-white p-4 dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <h3 className="font-medium text-slate-900 dark-tenant:text-slate-100">
                          {insight.title}
                        </h3>
                        <span className="text-xs text-slate-500">{formatWhen(insight.created_at)}</span>
                      </div>
                      <p className="mt-1 text-sm text-slate-600 dark-tenant:text-slate-300">
                        {insight.summary}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </PageSection>

            <PageSection title={t("marketingIntelligence.trend")}>
              {trendPoints.length === 0 ? (
                <div className="flex items-center gap-3 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-500 dark-tenant:border-slate-700">
                  <TrendingUp className="h-5 w-5" />
                  {t("marketingIntelligence.noTrend")}
                </div>
              ) : (
                <div className="space-y-2">
                  {trendPoints.slice(-14).map((point) => (
                    <div
                      key={`${point.metric_key}-${point.bucket_start}`}
                      className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800"
                    >
                      <span className="text-slate-500">{formatWhen(point.bucket_start)}</span>
                      <span className={cn("font-semibold tabular-nums", scoreTone(point.value))}>
                        {Math.round(point.value)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {historyQuery.isError ? (
                <p className="mt-2 flex items-center gap-2 text-xs text-amber-700">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {getApiErrorMessage(historyQuery.error)}
                </p>
              ) : null}
            </PageSection>
          </div>
        </>
      ) : null}
    </PageShell>
  );
}
