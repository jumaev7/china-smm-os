"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "next/navigation";
import { FileSearch } from "lucide-react";

import { ListeningSubNav } from "@/components/listening/ListeningSubNav";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import {
  LISTENING_QUERY_KEY,
  getApiErrorMessage,
  listeningApi,
  type ListeningInsightReviewState,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

const REVIEW_STATES: ListeningInsightReviewState[] = [
  "acknowledged",
  "dismissed",
  "monitoring",
  "resolved",
];

export default function ListeningInsightDetailPage() {
  const { t } = useTranslation();
  const routeParams = useParams<{ insightKey: string }>();
  const search = useSearchParams();
  const windowKey = (search.get("window_key") as "7d" | "30d" | "90d" | null) || "30d";
  const queryClient = useQueryClient();
  const insightKey = decodeURIComponent(String(routeParams.insightKey || ""));

  const detailQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "intelligence", "insight", insightKey, windowKey],
    queryFn: () =>
      listeningApi
        .intelligenceInsightDetail(insightKey, { window_key: windowKey, include_fixture: false })
        .then((r) => r.data),
    enabled: Boolean(insightKey),
    ...QUERY_OPTS,
  });

  const reviewMutation = useMutation({
    mutationFn: (review_state: ListeningInsightReviewState) =>
      listeningApi.reviewInsight(insightKey, { review_state }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: [...LISTENING_QUERY_KEY, "intelligence"],
      });
    },
  });

  const data = detailQuery.data;
  const insight = data?.insight;

  return (
    <PageShell wide>
      <PageHeader
        title={insight?.title || t("listening.intelInsightDetail")}
        subtitle={t("listening.intelInsightDetailSubtitle")}
        icon={FileSearch}
        badge={<StatusBadge variant="neutral">{t("listening.readOnlyBadge")}</StatusBadge>}
        actions={
          <Link href="/listening/intelligence" className="btn-secondary text-sm">
            {t("listening.intelBack")}
          </Link>
        }
      />
      <ListeningSubNav />

      {detailQuery.isLoading ? <LoadingState message={t("listening.loadingIntelligence")} /> : null}
      {detailQuery.isError && !detailQuery.isLoading ? (
        <ErrorState
          title={t("listening.loadError")}
          message={getApiErrorMessage(detailQuery.error)}
          onRetry={() => detailQuery.refetch()}
        />
      ) : null}

      {insight ? (
        <>
          <PageSection title={t("listening.intelObservedFacts")} className="mb-6">
            <p className="mb-3 text-sm text-slate-700 dark-tenant:text-slate-200">
              {insight.explanation}
            </p>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {insight.observed_facts.map((fact) => (
                <li key={fact}>{fact}</li>
              ))}
            </ul>
            <dl className="mt-4 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
              <div>
                <dt className="font-semibold">{t("listening.intelMethod")}</dt>
                <dd>{insight.methodology_version}</dd>
              </div>
              <div>
                <dt className="font-semibold">{t("listening.intelCoverage")}</dt>
                <dd>
                  {insight.coverage_status} / {insight.confidence}
                </dd>
              </div>
              <div>
                <dt className="font-semibold">{t("listening.intelReviewState")}</dt>
                <dd>{insight.analyst_review_state}</dd>
              </div>
              <div>
                <dt className="font-semibold">{t("listening.intelCategory")}</dt>
                <dd>
                  {insight.category} · {insight.severity}
                </dd>
              </div>
            </dl>
            {(insight.limitations || []).length > 0 ? (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-800 dark-tenant:text-amber-200">
                {insight.limitations.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : null}
          </PageSection>

          <PageSection title={t("listening.intelEvidence")} className="mb-6">
            {(data?.evidence || []).length === 0 ? (
              <EmptyState
                title={t("listening.intelNoEvidence")}
                description={t("listening.intelNoEvidenceHint")}
              />
            ) : (
              <ul className="space-y-3">
                {data!.evidence.map((row) => (
                  <li
                    key={row.id}
                    className="rounded-md border border-slate-200 p-3 dark-tenant:border-slate-700"
                  >
                    <p className="text-sm">{row.content_excerpt || t("listening.noContent")}</p>
                    <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                      <span>{row.observation_origin}</span>
                      <span>{row.review_state}</span>
                      <span>{row.published_at || t("listening.unknownTime")}</span>
                      <Link
                        href={`/listening/mentions/${row.id}`}
                        className="text-sky-700 underline dark-tenant:text-sky-300"
                      >
                        {t("listening.intelOpenMention")}
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </PageSection>

          <PageSection title={t("listening.intelAnalystReview")}>
            <p className="mb-3 text-sm text-slate-600 dark-tenant:text-slate-300">
              {t("listening.intelAnalystReviewHint")}
            </p>
            <div className="flex flex-wrap gap-2">
              {REVIEW_STATES.map((state) => (
                <button
                  key={state}
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={reviewMutation.isPending}
                  onClick={() => reviewMutation.mutate(state)}
                >
                  {t(`listening.insightReview.${state}`)}
                </button>
              ))}
            </div>
            {reviewMutation.isSuccess ? (
              <p className="mt-2 text-sm text-emerald-700 dark-tenant:text-emerald-300" role="status">
                {t("listening.intelReviewUpdated")}
              </p>
            ) : null}
            {reviewMutation.isError ? (
              <p className="mt-2 text-sm text-rose-700" role="alert">
                {getApiErrorMessage(reviewMutation.error)}
              </p>
            ) : null}
          </PageSection>
        </>
      ) : null}
    </PageShell>
  );
}
