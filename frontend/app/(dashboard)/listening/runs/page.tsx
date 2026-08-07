"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

function formatWhen(iso: string | null | undefined, unknownLabel: string): string {
  if (!iso) return unknownLabel;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return unknownLabel;
    return d.toLocaleString();
  } catch {
    return unknownLabel;
  }
}

export default function ListeningRunsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const runsQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "runs"],
    queryFn: () => listeningApi.listRuns({ limit: 50 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const items = runsQuery.data?.items ?? [];
  const webhookQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "webhook-events"],
    queryFn: () => listeningApi.listWebhookEvents({ limit: 50 }).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const replayMutation = useMutation({
    mutationFn: (eventId: string) => listeningApi.replayWebhookEvent(eventId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: LISTENING_QUERY_KEY }),
  });
  const processMutation = useMutation({
    mutationFn: () => listeningApi.processWebhookEvents(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: LISTENING_QUERY_KEY }),
  });
  const webhookItems = webhookQuery.data?.items ?? [];

  return (
    <PageShell wide>
      <PageHeader
        title={t("listening.runsTitle")}
        subtitle={t("listening.runsSubtitle")}
        icon={Radio}
        badge={<StatusBadge variant="neutral">{t("listening.readOnlyBadge")}</StatusBadge>}
      />
      <ListeningSubNav />

      <section className="rounded-xl border border-slate-200 bg-white p-4 dark-tenant:border-slate-700 dark-tenant:bg-slate-900">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">Meta webhook inbox</h2>
            <p className="text-xs text-slate-500">Signed notifications trigger GET-only reconciliation; polling remains the fallback.</p>
          </div>
          <button
            type="button"
            onClick={() => processMutation.mutate()}
            disabled={processMutation.isPending}
            className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-medium text-white disabled:opacity-50 dark-tenant:bg-slate-100 dark-tenant:text-slate-900"
          >
            {processMutation.isPending ? "Processing…" : "Process due events"}
          </button>
        </div>
        {webhookQuery.isError ? <ErrorState title="Webhook inbox unavailable" message={getApiErrorMessage(webhookQuery.error)} onRetry={() => webhookQuery.refetch()} /> : null}
        {!webhookQuery.isError && webhookItems.length === 0 ? <p className="text-sm text-slate-500">No webhook events received.</p> : null}
        {webhookItems.length > 0 ? (
          <DataTable>
            <DataTableHead><DataTableRow><DataTableTh>Status</DataTableTh><DataTableTh>Page / field</DataTableTh><DataTableTh>Attempts</DataTableTh><DataTableTh>Received</DataTableTh><DataTableTh>Action</DataTableTh></DataTableRow></DataTableHead>
            <DataTableBody>{webhookItems.map((event) => (
              <DataTableRow key={event.id}>
                <DataTableTd><StatusBadge variant={event.status === "succeeded" ? "success" : "neutral"}>{event.status}</StatusBadge></DataTableTd>
                <DataTableTd className="text-xs">{event.provider_object_ref} / {event.provider_field || "unknown"}</DataTableTd>
                <DataTableTd className="text-xs">{event.attempt_count}{event.last_error_code ? ` · ${event.last_error_code}` : ""}</DataTableTd>
                <DataTableTd className="text-xs">{formatWhen(event.received_at, t("listening.unknownTime"))}</DataTableTd>
                <DataTableTd>{event.status === "dead_letter" || event.status === "retry" ? <button type="button" onClick={() => replayMutation.mutate(event.id)} className="text-xs font-medium text-blue-600 hover:underline">Replay</button> : "—"}</DataTableTd>
              </DataTableRow>
            ))}</DataTableBody>
          </DataTable>
        ) : null}
      </section>

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
                    {formatWhen(run.freshness_watermark, t("listening.unknownTime"))}
                  </DataTableTd>
                  <DataTableTd className="max-w-[240px] text-xs text-slate-500">
                    <span className="line-clamp-3">{run.error_summary || "—"}</span>
                  </DataTableTd>
                  <DataTableTd className="whitespace-nowrap text-xs text-slate-500">
                    {formatWhen(run.completed_at ?? run.started_at, t("listening.unknownTime"))}
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
