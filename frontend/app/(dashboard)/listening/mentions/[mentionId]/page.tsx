"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Radio } from "lucide-react";
import toast from "react-hot-toast";

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
  type ListeningReviewState,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

const REVIEW_STATES: ListeningReviewState[] = [
  "unreviewed",
  "relevant",
  "irrelevant",
  "needs_follow_up",
  "resolved",
];

function formatWhen(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function safeExternalHref(url?: string | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.toString();
  } catch {
    return null;
  }
  return null;
}

export default function ListeningMentionDetailPage() {
  const { t } = useTranslation();
  const params = useParams();
  const mentionId = String(params.mentionId || "");
  const queryClient = useQueryClient();

  const mentionQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "mention", mentionId],
    queryFn: () => listeningApi.getMention(mentionId).then((r) => r.data),
    enabled: Boolean(mentionId),
    ...QUERY_OPTS,
  });

  const reviewMutation = useMutation({
    mutationFn: (review_state: ListeningReviewState) =>
      listeningApi.reviewMention(mentionId, { review_state }),
    onSuccess: () => {
      toast.success(t("listening.reviewUpdated"));
      queryClient.invalidateQueries({ queryKey: LISTENING_QUERY_KEY });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const m = mentionQuery.data;
  const externalHref = safeExternalHref(m?.canonical_url);

  return (
    <PageShell wide>
      <PageHeader
        title={t("listening.mentionDetail")}
        subtitle={t("listening.mentionDetailSubtitle")}
        icon={Radio}
        badge={<StatusBadge variant="neutral">{t("listening.readOnlyBadge")}</StatusBadge>}
        actions={
          <Link href="/listening/mentions" className="btn-secondary text-sm">
            {t("listening.backToMentions")}
          </Link>
        }
      />
      <ListeningSubNav />

      {mentionQuery.isLoading ? <LoadingState message={t("listening.loadingMention")} /> : null}
      {mentionQuery.isError && !mentionQuery.isLoading ? (
        <ErrorState
          title={t("listening.loadError")}
          message={getApiErrorMessage(mentionQuery.error)}
          onRetry={() => mentionQuery.refetch()}
        />
      ) : null}

      {m ? (
        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <div className="space-y-6">
            <PageSection title={t("listening.content")}>
              <div className="flex flex-wrap gap-2 text-xs">
                <StatusBadge variant="neutral">{m.source_type}</StatusBadge>
                <StatusBadge variant="neutral">{m.observation_origin}</StatusBadge>
                <StatusBadge variant="neutral">{m.content_type}</StatusBadge>
                {m.language ? <StatusBadge variant="neutral">{m.language}</StatusBadge> : null}
              </div>
              <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-800 dark-tenant:text-slate-100">
                {m.content_text || m.content_excerpt || t("listening.noContent")}
              </p>
              {externalHref ? (
                <p className="mt-4 text-sm">
                  <a
                    href={externalHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-slate-700 underline dark-tenant:text-slate-200"
                  >
                    {t("listening.openSource")}
                  </a>
                </p>
              ) : null}
            </PageSection>

            <PageSection title={t("listening.matchEvidence")}>
              {(m.matches ?? []).length === 0 ? (
                <EmptyState title={t("listening.noMatches")} description={t("listening.noMatchesHint")} />
              ) : (
                <ul className="space-y-3">
                  {(m.matches ?? []).map((match) => (
                    <li
                      key={match.id}
                      className="rounded-lg border border-slate-200 px-4 py-3 dark-tenant:border-slate-800"
                    >
                      <div className="flex flex-wrap gap-2 text-xs">
                        <StatusBadge variant="success">{match.match_type}</StatusBadge>
                        <span className="font-medium text-slate-800 dark-tenant:text-slate-100">
                          {match.matched_term}
                        </span>
                        <span className="text-slate-500">{match.matcher_version}</span>
                      </div>
                      {match.evidence_excerpt ? (
                        <p className="mt-2 text-sm text-slate-600 dark-tenant:text-slate-300">
                          {match.evidence_excerpt}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </PageSection>
          </div>

          <div className="space-y-6">
            <PageSection title={t("listening.review")}>
              <p className="mb-3 text-sm text-slate-600 dark-tenant:text-slate-300">
                {t("listening.reviewHint")}
              </p>
              <div className="flex flex-col gap-2">
                {REVIEW_STATES.map((state) => (
                  <button
                    key={state}
                    type="button"
                    className="btn-secondary justify-start text-left text-sm"
                    disabled={reviewMutation.isPending || m.review_state === state}
                    onClick={() => reviewMutation.mutate(state)}
                    aria-pressed={m.review_state === state}
                  >
                    {state}
                    {m.review_state === state ? ` · ${t("listening.current")}` : ""}
                  </button>
                ))}
              </div>
            </PageSection>

            <PageSection title={t("listening.provenance")}>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">{t("listening.author")}</dt>
                  <dd>{m.author_display || "—"}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">{t("listening.publishedAt")}</dt>
                  <dd>{formatWhen(m.published_at)}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">{t("listening.firstObserved")}</dt>
                  <dd>{formatWhen(m.first_observed_at)}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">{t("listening.lastObserved")}</dt>
                  <dd>{formatWhen(m.last_observed_at)}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">{t("listening.externalId")}</dt>
                  <dd className="break-all text-right">{m.provider_external_id || "—"}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">{t("listening.ingestionRun")}</dt>
                  <dd className="break-all text-right text-xs">{m.ingestion_run_id || "—"}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">{t("listening.normVersion")}</dt>
                  <dd>{m.normalization_version || "—"}</dd>
                </div>
              </dl>
              {m.engagement ? (
                <pre className="mt-4 overflow-x-auto rounded-md bg-slate-50 p-3 text-xs dark-tenant:bg-slate-900">
                  {JSON.stringify(m.engagement, null, 2)}
                </pre>
              ) : null}
            </PageSection>
          </div>
        </div>
      ) : null}
    </PageShell>
  );
}
