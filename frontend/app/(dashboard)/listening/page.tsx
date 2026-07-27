"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Radio } from "lucide-react";

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
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

function formatWhen(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function ListeningOverviewPage() {
  const { t } = useTranslation();
  const overviewQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "overview"],
    queryFn: () => listeningApi.overview().then((r) => r.data),
    ...QUERY_OPTS,
  });

  const data = overviewQuery.data;

  return (
    <PageShell wide>
      <PageHeader
        title={t("listening.title")}
        subtitle={t("listening.subtitle")}
        icon={Radio}
        badge={<StatusBadge variant="neutral">{t("listening.readOnlyBadge")}</StatusBadge>}
        actions={
          <Link href="/listening/projects" className="btn-secondary text-sm">
            {t("listening.configure")}
          </Link>
        }
      />
      <ListeningSubNav />

      {overviewQuery.isLoading ? <LoadingState message={t("listening.loadingOverview")} /> : null}
      {overviewQuery.isError && !overviewQuery.isLoading ? (
        <ErrorState
          title={t("listening.loadError")}
          message={getApiErrorMessage(overviewQuery.error)}
          onRetry={() => overviewQuery.refetch()}
        />
      ) : null}

      {data ? (
        <>
          <div
            className="mb-6 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark-tenant:border-amber-900 dark-tenant:bg-amber-950/40 dark-tenant:text-amber-100"
            role="status"
          >
            {data.coverage_notice}
            {!data.live_provider_available ? (
              <span className="mt-1 block font-medium">{t("listening.noLiveProvider")}</span>
            ) : null}
          </div>

          <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard label={t("listening.kpiProjects")} value={String(data.project_count)} />
            <KpiCard label={t("listening.kpiMentions")} value={String(data.mention_total)} />
            <KpiCard label={t("listening.kpiUnreviewed")} value={String(data.unreviewed_count)} />
            <KpiCard
              label={t("listening.kpiLive")}
              value={data.live_provider_available ? t("common.yes") : t("common.no")}
            />
          </div>

          <PageSection title={t("listening.recentMentions")} className="mb-8">
            {data.recent_mentions.length === 0 ? (
              <EmptyState
                title={t("listening.emptyMentions")}
                description={t("listening.emptyMentionsHint")}
              />
            ) : (
              <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 dark-tenant:divide-slate-800 dark-tenant:border-slate-800">
                {data.recent_mentions.map((m) => (
                  <li key={m.id} className="px-4 py-3">
                    <Link
                      href={`/listening/mentions/${m.id}`}
                      className="block hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
                    >
                      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                        <StatusBadge variant="neutral">{m.source_type}</StatusBadge>
                        <StatusBadge variant="neutral">{m.observation_origin}</StatusBadge>
                        <span>{formatWhen(m.published_at ?? m.observed_at)}</span>
                        <span>{m.review_state}</span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-sm text-slate-800 dark-tenant:text-slate-100">
                        {m.content_excerpt || m.content_text || t("listening.noContent")}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </PageSection>

          <PageSection title={t("listening.sourceFreshness")} className="mb-8">
            {data.sources.length === 0 ? (
              <EmptyState title={t("listening.noSources")} description={t("listening.noSourcesHint")} />
            ) : (
              <ul className="grid gap-3 md:grid-cols-2">
                {data.sources.map((s) => (
                  <li
                    key={s.id}
                    className="rounded-lg border border-slate-200 px-4 py-3 dark-tenant:border-slate-800"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-medium text-slate-900 dark-tenant:text-slate-100">
                        {s.display_name}
                      </p>
                      <StatusBadge variant="neutral">{s.freshness_status}</StatusBadge>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {s.source_type} · {s.capability_status}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {t("listening.lastSuccess")}: {formatWhen(s.last_success_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </PageSection>

          <PageSection title={t("listening.ingestionHealth")}>
            {data.recent_ingestion_runs.length === 0 ? (
              <EmptyState title={t("listening.noRuns")} description={t("listening.noRunsHint")} />
            ) : (
              <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 dark-tenant:divide-slate-800 dark-tenant:border-slate-800">
                {data.recent_ingestion_runs.map((run) => (
                  <li key={run.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
                    <div>
                      <StatusBadge variant={run.status === "succeeded" ? "success" : "neutral"}>
                        {run.status}
                      </StatusBadge>
                      <span className="ml-2 text-slate-600 dark-tenant:text-slate-300">
                        {run.source_type} · {run.trigger_type}
                      </span>
                    </div>
                    <span className="text-xs text-slate-500">
                      +{run.created_count} / dup {run.duplicate_count} / rej {run.rejected_count} ·{" "}
                      {formatWhen(run.completed_at ?? run.started_at)}
                    </span>
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
