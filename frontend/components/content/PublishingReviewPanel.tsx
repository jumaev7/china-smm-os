"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  ClipboardList,
  History,
  Loader2,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";

import {
  PUBLISHING_INTELLIGENCE_QUERY_KEY,
  getApiErrorMessage,
  publishingIntelligenceApi,
  type PublishingReview,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  contentId: string;
}

function scoreTone(score: number): string {
  if (score >= 75) return "text-emerald-700";
  if (score >= 55) return "text-amber-700";
  return "text-rose-700";
}

function statusTone(status: string): string {
  if (status === "passed") return "text-emerald-600";
  if (status === "warning") return "text-amber-600";
  if (status === "failed") return "text-rose-600";
  return "text-slate-400";
}

function readinessLabel(value: string): string {
  if (value === "ready") return "Hard checks: ready";
  if (value === "blocked") return "Hard checks: blocked";
  return "Hard checks: warnings";
}

export function PublishingReviewPanel({ contentId }: Props) {
  const qc = useQueryClient();

  const latestQuery = useQuery({
    queryKey: [...PUBLISHING_INTELLIGENCE_QUERY_KEY, "latest", contentId],
    queryFn: async () => {
      try {
        const res = await publishingIntelligenceApi.latestReview(contentId);
        return res.data;
      } catch (err: unknown) {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 404) return null;
        throw err;
      }
    },
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });

  const historyQuery = useQuery({
    queryKey: [...PUBLISHING_INTELLIGENCE_QUERY_KEY, "history", contentId],
    queryFn: () =>
      publishingIntelligenceApi.listReviews(contentId, { page_size: 8 }).then((r) => r.data),
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });

  const runReview = useMutation({
    mutationFn: () => publishingIntelligenceApi.createReview(contentId).then((r) => r.data),
    onSuccess: (data) => {
      qc.setQueryData([...PUBLISHING_INTELLIGENCE_QUERY_KEY, "latest", contentId], data);
      void qc.invalidateQueries({ queryKey: [...PUBLISHING_INTELLIGENCE_QUERY_KEY, "history", contentId] });
      void qc.invalidateQueries({ queryKey: ["marketing-intelligence"] });
    },
  });

  const review = latestQuery.data;
  const history = historyQuery.data?.items ?? [];

  return (
    <div className="card p-4 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <ClipboardList size={15} className="text-brand-600 shrink-0" />
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Publishing Score</h3>
            <p className="text-[11px] text-gray-500 mt-0.5">
              Rule-based Phase 1 review — not AI. Advisory only; hard publish safety still applies.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => runReview.mutate()}
          disabled={runReview.isPending}
          className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-white disabled:opacity-60"
        >
          {runReview.isPending ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <RefreshCw size={13} />
          )}
          {review ? "Re-run review" : "Run review"}
        </button>
      </div>

      {runReview.isError ? (
        <p className="text-xs text-rose-600">{getApiErrorMessage(runReview.error)}</p>
      ) : null}

      {latestQuery.isLoading ? (
        <div className="animate-pulse space-y-2">
          <div className="h-8 bg-gray-100 rounded w-24" />
          <div className="h-3 bg-gray-100 rounded w-full" />
        </div>
      ) : null}

      {!latestQuery.isLoading && !review ? (
        <p className="text-xs text-gray-500">
          No review yet. Run a deterministic pre-publish review to get a Publishing Score.
        </p>
      ) : null}

      {review ? <ReviewBody review={review} history={history} /> : null}
    </div>
  );
}

function ReviewBody({
  review,
  history,
}: {
  review: PublishingReview;
  history: PublishingReview[];
}) {
  const categories = Object.values(review.category_scores || {}).filter((c) => c.applicable);
  const checks = review.checks || [];
  const failed = checks.filter((c) => c.status === "failed");
  const warnings = checks.filter((c) => c.status === "warning");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <p className={cn("text-3xl font-semibold tabular-nums", scoreTone(review.overall_score))}>
            {review.overall_score}
          </p>
          <p className="text-[11px] text-gray-500">
            v{review.review_version} · engine {review.review_engine_version}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {review.is_stale || review.status === "stale" ? (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800">
              Stale — content changed
            </span>
          ) : review.is_current ? (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-800">
              Current
            </span>
          ) : (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
              {review.status}
            </span>
          )}
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-medium",
              review.publish_readiness === "blocked"
                ? "bg-rose-100 text-rose-800"
                : review.publish_readiness === "ready"
                  ? "bg-emerald-100 text-emerald-800"
                  : "bg-amber-100 text-amber-800",
            )}
          >
            {readinessLabel(review.publish_readiness)}
          </span>
        </div>
      </div>

      <p className="text-[11px] text-gray-500 flex items-start gap-1.5">
        <ShieldAlert size={12} className="mt-0.5 shrink-0" />
        Quality score is advisory. Hard blockers come from publish safety, not the score alone.
      </p>

      {categories.length > 0 ? (
        <div>
          <h4 className="text-xs font-semibold text-gray-800 mb-2">Category breakdown</h4>
          <div className="space-y-1.5">
            {categories.map((cat) => (
              <div key={cat.category} className="flex items-center justify-between gap-2 text-xs">
                <span className="text-gray-600 capitalize">{cat.category.replace(/_/g, " ")}</span>
                <span className={cn("font-medium tabular-nums", scoreTone(cat.score))}>
                  {cat.score}
                  <span className="text-gray-400 font-normal"> · w{cat.weight}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {review.platform_reviews?.length ? (
        <div>
          <h4 className="text-xs font-semibold text-gray-800 mb-2">Platform readiness</h4>
          <div className="space-y-1.5">
            {review.platform_reviews.map((p) => (
              <div key={p.platform} className="flex items-center justify-between text-xs">
                <span className="capitalize text-gray-600">{p.platform}</span>
                <span className={cn("font-medium tabular-nums", scoreTone(p.platform_score))}>
                  {p.platform_score}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {review.recommendations?.length ? (
        <div>
          <h4 className="text-xs font-semibold text-gray-800 mb-2">Recommendations</h4>
          <ul className="space-y-2">
            {review.recommendations.slice(0, 6).map((rec) => (
              <li key={rec.key} className="rounded-md border border-slate-100 bg-slate-50 px-2.5 py-2">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wide text-slate-500">{rec.priority}</span>
                  <span className="text-[10px] text-slate-400">{rec.category}</span>
                </div>
                <p className="text-xs font-medium text-gray-900 mt-0.5">{rec.suggested_action}</p>
                <p className="text-[11px] text-gray-500 mt-0.5">{rec.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div>
        <h4 className="text-xs font-semibold text-gray-800 mb-2">
          Checks
          <span className="font-normal text-gray-400">
            {" "}
            · {failed.length} failed · {warnings.length} warnings
          </span>
        </h4>
        <ul className="max-h-48 overflow-y-auto space-y-1">
          {[...failed, ...warnings, ...checks.filter((c) => c.status === "passed")].slice(0, 20).map((c) => (
            <li key={`${c.check_key}-${c.category}`} className="flex items-start gap-1.5 text-[11px]">
              {c.status === "passed" ? (
                <CheckCircle2 size={12} className="text-emerald-500 mt-0.5 shrink-0" />
              ) : (
                <AlertCircle size={12} className={cn("mt-0.5 shrink-0", statusTone(c.status))} />
              )}
              <div className="min-w-0">
                <span className="text-gray-800">{c.check_key}</span>
                <span className="text-gray-400"> · {c.status}</span>
                {c.score != null ? (
                  <span className="text-gray-400"> · {c.score}</span>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      </div>

      {history.length > 1 ? (
        <div>
          <h4 className="text-xs font-semibold text-gray-800 mb-2 flex items-center gap-1">
            <History size={12} /> Review history
          </h4>
          <ul className="space-y-1">
            {history.slice(0, 5).map((h) => (
              <li
                key={h.review_id}
                className={cn(
                  "flex items-center justify-between text-[11px] rounded px-2 py-1",
                  h.review_id === review.review_id ? "bg-slate-100" : "bg-transparent",
                )}
              >
                <span className="text-gray-600">
                  v{h.review_version}
                  {h.is_stale || h.status === "stale" ? " · stale" : ""}
                  {h.status === "superseded" ? " · superseded" : ""}
                </span>
                <span className={cn("font-medium tabular-nums", scoreTone(h.overall_score))}>
                  {h.overall_score}
                </span>
              </li>
            ))}
          </ul>
          {history.length >= 2 ? (
            <p className="text-[10px] text-gray-400 mt-1">
              Compare: latest {history[0]?.overall_score} vs previous {history[1]?.overall_score}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
