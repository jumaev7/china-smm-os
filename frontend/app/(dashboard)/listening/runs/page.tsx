"use client";

import { useQuery } from "@tanstack/react-query";
import { Radio } from "lucide-react";

import { ListeningSubNav } from "@/components/listening/ListeningSubNav";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  DataTable,
  DataTableBody,
  DataTableHead,
  DataTableRow,
  DataTableTd,
  DataTableTh,
  PageHeader,
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

export default function ListeningRunsPage() {
  const { t } = useTranslation();
  const runsQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "runs"],
    queryFn: () => listeningApi.listRuns({ limit: 50 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const items = runsQuery.data?.items ?? [];

  return (
    <PageShell wide>
      <PageHeader
        title={t("listening.runsTitle")}
        subtitle={t("listening.runsSubtitle")}
        icon={Radio}
        badge={<StatusBadge variant="neutral">{t("listening.readOnlyBadge")}</StatusBadge>}
      />
      <ListeningSubNav />

      {runsQuery.isLoading ? <LoadingState message={t("listening.loadingRuns")} /> : null}
      {runsQuery.isError && !runsQuery.isLoading ? (
        <ErrorState
          title={t("listening.loadError")}
          message={getApiErrorMessage(runsQuery.error)}
          onRetry={() => runsQuery.refetch()}
        />
      ) : null}

      {!runsQuery.isLoading && !runsQuery.isError ? (
        items.length === 0 ? (
          <EmptyState title={t("listening.noRuns")} description={t("listening.noRunsHint")} />
        ) : (
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>{t("listening.colStatus")}</DataTableTh>
                <DataTableTh>{t("listening.colSource")}</DataTableTh>
                <DataTableTh>{t("listening.colCounts")}</DataTableTh>
                <DataTableTh>{t("listening.colWatermark")}</DataTableTh>
                <DataTableTh>{t("listening.colErrors")}</DataTableTh>
                <DataTableTh>{t("listening.colWhen")}</DataTableTh>
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {items.map((run) => (
                <DataTableRow key={run.id}>
                  <DataTableTd>
                    <StatusBadge variant={run.status === "succeeded" ? "success" : "neutral"}>
                      {run.status}
                    </StatusBadge>
                    <div className="mt-1 text-xs text-slate-500">{run.trigger_type}</div>
                  </DataTableTd>
                  <DataTableTd className="text-sm">{run.source_type}</DataTableTd>
                  <DataTableTd className="text-xs text-slate-600 dark-tenant:text-slate-300">
                    fetched {run.fetched_count} · +{run.created_count} · upd {run.updated_count} ·
                    dup {run.duplicate_count} · rej {run.rejected_count} · err {run.error_count} ·
                    match {run.match_count}
                  </DataTableTd>
                  <DataTableTd className="whitespace-nowrap text-xs text-slate-500">
                    {formatWhen(run.freshness_watermark)}
                  </DataTableTd>
                  <DataTableTd className="max-w-[240px] text-xs text-slate-500">
                    <span className="line-clamp-3">{run.error_summary || "—"}</span>
                  </DataTableTd>
                  <DataTableTd className="whitespace-nowrap text-xs text-slate-500">
                    {formatWhen(run.completed_at ?? run.started_at)}
                  </DataTableTd>
                </DataTableRow>
              ))}
            </DataTableBody>
          </DataTable>
        )
      ) : null}
    </PageShell>
  );
}
