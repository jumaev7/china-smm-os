"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { ArrowLeft, Image as ImageIcon, Link2, Unlink } from "lucide-react";

import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  KpiCard,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { ADVERTISING_QUERY_KEY, advertisingApi, getApiErrorMessage } from "@/lib/api";
import {
  fatigueLabel,
  fatigueVariant,
  formatFrequency,
  formatMoneyMinor,
  formatNumber,
  formatRatioPct,
  freshnessVariant,
  titleCaseKey,
} from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function AdvertisingCreativeDetailPage() {
  const params = useParams();
  const creativeId = String(params.creativeId);
  const queryClient = useQueryClient();
  const [contentId, setContentId] = useState("");

  const creativeQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "creative", creativeId],
    queryFn: () => advertisingApi.getCreative(creativeId).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const diagnosticsQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "creative", creativeId, "diagnostics"],
    queryFn: () => advertisingApi.creativeDiagnostics(creativeId).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: [...ADVERTISING_QUERY_KEY, "creative", creativeId] });

  const linkMutation = useMutation({
    mutationFn: () =>
      advertisingApi.linkCreativeContent(creativeId, contentId.trim()).then((r) => r.data),
    onSuccess: () => {
      toast.success("Linked to internal content");
      setContentId("");
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });
  const unlinkMutation = useMutation({
    mutationFn: () => advertisingApi.unlinkCreativeContent(creativeId).then((r) => r.data),
    onSuccess: () => {
      toast.success("Unlinked");
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const creative = creativeQuery.data;
  const diagnostics = diagnosticsQuery.data;

  return (
    <PageShell wide>
      <PageHeader
        title={creative?.name ?? "Creative"}
        subtitle="Read-only provider creative. Fatigue is an advisory signal derived from frequency."
        icon={ImageIcon}
        badge={<StatusBadge variant="neutral">Read-only</StatusBadge>}
        actions={
          <Link href="/advertising/creatives" className="btn-secondary text-sm">
            <ArrowLeft size={14} /> Creatives
          </Link>
        }
      />

      {creativeQuery.isLoading ? <LoadingState message="Loading creative…" /> : null}
      {creativeQuery.isError && !creativeQuery.isLoading ? (
        <ErrorState
          title="Unable to load creative"
          message={getApiErrorMessage(creativeQuery.error)}
          onRetry={() => creativeQuery.refetch()}
        />
      ) : null}

      {creative ? (
        <>
          <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
            <div className="flex h-52 items-center justify-center overflow-hidden rounded-xl border border-slate-200 bg-slate-50 dark-tenant:border-slate-800 dark-tenant:bg-slate-900">
              {creative.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={creative.thumbnail_url} alt={creative.name} className="h-full w-full object-cover" />
              ) : (
                <ImageIcon size={34} className="text-slate-300" />
              )}
            </div>
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                {creative.format ? (
                  <StatusBadge variant="neutral">{titleCaseKey(creative.format)}</StatusBadge>
                ) : null}
                <StatusBadge variant={fatigueVariant(creative.fatigue_status)}>
                  {fatigueLabel(creative.fatigue_status)}
                </StatusBadge>
                <StatusBadge variant={freshnessVariant(diagnostics?.freshness_status)}>
                  {titleCaseKey(diagnostics?.freshness_status)}
                </StatusBadge>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <KpiCard label="Spend" value={formatMoneyMinor(creative.spend_minor, creative.currency)} />
                <KpiCard label="Impressions" value={formatNumber(creative.impressions)} />
                <KpiCard
                  label="Frequency"
                  value={formatFrequency(diagnostics?.frequency ?? creative.frequency)}
                />
                <KpiCard
                  label="CTR"
                  value={diagnostics?.ctr != null ? formatRatioPct(diagnostics.ctr) : "—"}
                />
              </div>
              {creative.preview_url ? (
                <a
                  href={creative.preview_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block text-sm text-brand-600 underline underline-offset-2"
                >
                  Open provider preview
                </a>
              ) : null}
            </div>
          </div>

          <PageSection
            title="Internal content link"
            description="Associates this creative with internal content for correlation. Writes to our linkage table only — never the provider."
          >
            {creative.linked_content_id ? (
              <div className="card-premium flex flex-wrap items-center justify-between gap-3 p-4">
                <div className="text-sm">
                  <StatusBadge variant="info">Linked</StatusBadge>
                  <span className="ml-2 font-mono text-xs text-slate-500">
                    {creative.linked_content_id}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={unlinkMutation.isPending}
                  onClick={() => unlinkMutation.mutate()}
                >
                  <Unlink size={14} /> Unlink
                </button>
              </div>
            ) : (
              <div className="card-premium flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
                <label className="flex-1 text-sm">
                  <span className="mb-1 block text-xs font-medium text-slate-500">
                    Internal content ID
                  </span>
                  <input
                    type="text"
                    value={contentId}
                    onChange={(e) => setContentId(e.target.value)}
                    placeholder="UUID of content item"
                    className="input w-full"
                  />
                </label>
                <button
                  type="button"
                  className="btn-primary text-sm"
                  disabled={!contentId.trim() || linkMutation.isPending}
                  onClick={() => linkMutation.mutate()}
                >
                  <Link2 size={14} /> Link
                </button>
              </div>
            )}
          </PageSection>
        </>
      ) : null}
    </PageShell>
  );
}
