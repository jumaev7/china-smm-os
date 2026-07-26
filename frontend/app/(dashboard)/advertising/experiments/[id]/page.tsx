"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FlaskConical } from "lucide-react";

import { AdvertisingSubNav } from "@/components/advertising/AdvertisingSubNav";
import { KindBadge } from "@/components/advertising/KindBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import {
  ADVERTISING_QUERY_KEY,
  advertisingApi,
  getApiErrorMessage,
} from "@/lib/api";
import { formatWhen, titleCaseKey } from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

function reviewKind(resultStatus?: string | null, kind?: string | null): string {
  const status = (resultStatus ?? "").toLowerCase();
  if (status === "insufficient_data" || status === "insufficient") {
    return "INSUFFICIENT DATA";
  }
  return kind ?? "DIRECTIONAL";
}

export default function AdvertisingExperimentDetailPage() {
  const params = useParams();
  const experimentId = String(params.id ?? "");
  const queryClient = useQueryClient();

  const experimentQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "experiments", experimentId],
    queryFn: () => advertisingApi.getExperiment(experimentId).then((r) => r.data),
    enabled: Boolean(experimentId),
    ...QUERY_OPTS,
  });

  const reviewQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "experiments", experimentId, "review"],
    queryFn: () => advertisingApi.getExperimentReview(experimentId).then((r) => r.data),
    enabled: Boolean(experimentId),
    ...QUERY_OPTS,
    retry: false,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: [...ADVERTISING_QUERY_KEY, "experiments", experimentId],
    });
    queryClient.invalidateQueries({
      queryKey: [...ADVERTISING_QUERY_KEY, "experiments", experimentId, "review"],
    });
  };

  const startMutation = useMutation({
    mutationFn: () => advertisingApi.startExperimentObservation(experimentId).then((r) => r.data),
    onSuccess: invalidate,
  });
  const completeMutation = useMutation({
    mutationFn: () => advertisingApi.completeExperiment(experimentId).then((r) => r.data),
    onSuccess: invalidate,
  });
  const cancelMutation = useMutation({
    mutationFn: () => advertisingApi.cancelExperiment(experimentId).then((r) => r.data),
    onSuccess: invalidate,
  });
  const buildReviewMutation = useMutation({
    mutationFn: () => advertisingApi.buildExperimentReview(experimentId).then((r) => r.data),
    onSuccess: invalidate,
  });

  const exp = experimentQuery.data;
  const review = reviewQuery.data ?? buildReviewMutation.data;
  const actionPending =
    startMutation.isPending ||
    completeMutation.isPending ||
    cancelMutation.isPending ||
    buildReviewMutation.isPending;

  return (
    <PageShell wide>
      <PageHeader
        title={exp?.name ?? "Experiment"}
        subtitle="Observation lifecycle and directional review. Never launches on a provider."
        icon={FlaskConical}
        badge={<StatusBadge variant="neutral">Observation only</StatusBadge>}
        actions={
          <Link href="/advertising/experiments" className="btn-secondary text-sm inline-flex items-center gap-1.5">
            <ArrowLeft size={14} /> Experiments
          </Link>
        }
      />
      <AdvertisingSubNav />

      {experimentQuery.isLoading ? <LoadingState message="Loading experiment…" /> : null}
      {experimentQuery.isError && !experimentQuery.isLoading ? (
        <ErrorState
          title="Unable to load experiment"
          message={getApiErrorMessage(experimentQuery.error)}
          onRetry={() => experimentQuery.refetch()}
        />
      ) : null}

      {exp ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge variant="neutral">{titleCaseKey(exp.status)}</StatusBadge>
            <KindBadge kind={exp.kind ?? "OBSERVATION_PLAN"} />
            <span className="text-xs text-slate-500">
              {titleCaseKey(exp.experiment_type)} · {exp.primary_metric_key}
            </span>
          </div>

          <PageSection title="Hypothesis">
            <p className="text-sm whitespace-pre-wrap">{exp.hypothesis}</p>
            {exp.notes ? <p className="mt-2 text-xs text-slate-500">{exp.notes}</p> : null}
            <dl className="mt-3 grid gap-2 sm:grid-cols-3 text-sm">
              <div>
                <dt className="kpi-label">Observation start</dt>
                <dd>{exp.observation_start ?? "—"}</dd>
              </div>
              <div>
                <dt className="kpi-label">Observation end</dt>
                <dd>{exp.observation_end ?? "—"}</dd>
              </div>
              <div>
                <dt className="kpi-label">Created</dt>
                <dd>{formatWhen(exp.created_at)}</dd>
              </div>
            </dl>
          </PageSection>

          <PageSection title="Variants">
            {(exp.variants ?? []).length === 0 ? (
              <p className="text-sm text-slate-500">No variants recorded.</p>
            ) : (
              <div className="space-y-2">
                {(exp.variants ?? []).map((v, idx) => (
                  <div
                    key={String(v.id ?? v.variant_key ?? idx)}
                    className="rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800"
                  >
                    <p className="font-medium">
                      {String(v.label ?? v.variant_key ?? `Variant ${idx + 1}`)}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {titleCaseKey(String(v.entity_type ?? "entity"))} ·{" "}
                      {String(v.entity_id ?? "—")}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </PageSection>

          <PageSection
            title="Lifecycle"
            description="Local observation status only — no Apply / Pause / Launch provider actions."
          >
            <div className="flex flex-wrap gap-2">
              {exp.status === "draft" || exp.status === "ready" ? (
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={actionPending}
                  onClick={() => startMutation.mutate()}
                >
                  Start observation
                </button>
              ) : null}
              {exp.status === "running_observation" ? (
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={actionPending}
                  onClick={() => completeMutation.mutate()}
                >
                  Complete
                </button>
              ) : null}
              {exp.status === "draft" ||
              exp.status === "ready" ||
              exp.status === "running_observation" ? (
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={actionPending}
                  onClick={() => cancelMutation.mutate()}
                >
                  Cancel
                </button>
              ) : null}
            </div>
            {(startMutation.isError || completeMutation.isError || cancelMutation.isError) && (
              <p className="mt-2 text-xs text-rose-600">
                {getApiErrorMessage(
                  startMutation.error || completeMutation.error || cancelMutation.error,
                )}
              </p>
            )}
          </PageSection>

          <PageSection
            title="Review"
            description="Directional result only. Does not claim statistical significance."
            action={
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={buildReviewMutation.isPending}
                onClick={() => buildReviewMutation.mutate()}
              >
                {buildReviewMutation.isPending ? "Building…" : "Build / refresh review"}
              </button>
            }
          >
            {!review && !reviewQuery.isLoading ? (
              <EmptyState
                title="No review yet"
                description="Build a directional review after observation has enough data."
              />
            ) : null}
            {reviewQuery.isLoading && !review ? (
              <LoadingState message="Loading review…" />
            ) : null}
            {review ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <KindBadge kind={reviewKind(review.result_status, review.kind)} />
                  <StatusBadge variant="neutral">
                    {titleCaseKey(review.result_status)}
                  </StatusBadge>
                  {review.claims_statistical_significance === false ? (
                    <StatusBadge variant="info">No significance claim</StatusBadge>
                  ) : null}
                </div>
                <p className="text-sm">{review.conclusion}</p>
                {review.limitations && review.limitations.length > 0 ? (
                  <div>
                    <p className="kpi-label mb-1">Warnings / limitations</p>
                    <ul className="space-y-0.5 text-xs text-slate-500">
                      {review.limitations.map((lim) => (
                        <li key={lim}>• {lim}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {(review.variants ?? []).length > 0 ? (
                  <div className="space-y-2">
                    <p className="kpi-label">Variant evidence</p>
                    {(review.variants ?? []).map((v, idx) => (
                      <div
                        key={String(v.variant_key ?? idx)}
                        className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark-tenant:border-slate-800"
                      >
                        <pre className="whitespace-pre-wrap font-sans text-slate-600 dark-tenant:text-slate-300">
                          {JSON.stringify(v, null, 2)}
                        </pre>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            {buildReviewMutation.isError ? (
              <p className="mt-2 text-xs text-rose-600">
                {getApiErrorMessage(buildReviewMutation.error)}
              </p>
            ) : null}
          </PageSection>
        </>
      ) : null}
    </PageShell>
  );
}
