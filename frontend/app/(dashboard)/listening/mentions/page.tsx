"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Radio } from "lucide-react";

import { ListeningSubNav } from "@/components/listening/ListeningSubNav";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  ActionBar,
  DataTable,
  DataTableBody,
  DataTableHead,
  DataTableRow,
  DataTableTd,
  DataTableTh,
  FilterBar,
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

const REVIEW_OPTIONS = [
  { label: "Unreviewed", value: "unreviewed" },
  { label: "Relevant", value: "relevant" },
  { label: "Irrelevant", value: "irrelevant" },
  { label: "Needs follow-up", value: "needs_follow_up" },
  { label: "Resolved", value: "resolved" },
  { label: "All", value: "" },
];

const SOURCE_OPTIONS = [
  { label: "All sources", value: "" },
  { label: "Manual import", value: "manual_import" },
  { label: "Fixture", value: "fixture" },
];

function formatWhen(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function ListeningMentionsPage() {
  const { t } = useTranslation();
  const [reviewState, setReviewState] = useState("unreviewed");
  const [sourceType, setSourceType] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 25;

  const mentionsQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "mentions", reviewState, sourceType, search, offset],
    queryFn: () =>
      listeningApi
        .listMentions({
          review_state: reviewState || undefined,
          source_type: sourceType || undefined,
          search: search.trim() || undefined,
          limit,
          offset,
        })
        .then((r) => r.data),
    ...QUERY_OPTS,
  });

  const items = mentionsQuery.data?.items ?? [];
  const total = mentionsQuery.data?.total ?? 0;
  const pageLabel = useMemo(
    () => `${Math.min(offset + 1, total || 0)}–${Math.min(offset + limit, total)} / ${total}`,
    [offset, total],
  );

  return (
    <PageShell wide>
      <PageHeader
        title={t("listening.mentionsTitle")}
        subtitle={t("listening.mentionsSubtitle")}
        icon={Radio}
        badge={<StatusBadge variant="neutral">{t("listening.readOnlyBadge")}</StatusBadge>}
      />
      <ListeningSubNav />

      <ActionBar>
        <div className="flex w-full flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <FilterBar options={REVIEW_OPTIONS} value={reviewState} onChange={(v) => { setReviewState(v); setOffset(0); }} />
            <FilterBar options={SOURCE_OPTIONS} value={sourceType} onChange={(v) => { setSourceType(v); setOffset(0); }} />
          </div>
          <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-xs text-slate-500 lg:max-w-sm">
            <span>{t("listening.search")}</span>
            <input
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark-tenant:border-slate-700 dark-tenant:bg-slate-950 dark-tenant:text-slate-100"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setOffset(0);
              }}
              placeholder={t("listening.searchPlaceholder")}
              aria-label={t("listening.search")}
            />
          </label>
        </div>
      </ActionBar>

      {mentionsQuery.isLoading ? <LoadingState message={t("listening.loadingMentions")} /> : null}
      {mentionsQuery.isError && !mentionsQuery.isLoading ? (
        <ErrorState
          title={t("listening.loadError")}
          message={getApiErrorMessage(mentionsQuery.error)}
          onRetry={() => mentionsQuery.refetch()}
        />
      ) : null}

      {!mentionsQuery.isLoading && !mentionsQuery.isError ? (
        items.length === 0 ? (
          <EmptyState
            title={t("listening.emptyMentions")}
            description={t("listening.emptyMentionsHint")}
          />
        ) : (
          <>
            <DataTable>
              <DataTableHead>
                <DataTableRow>
                  <DataTableTh>{t("listening.colContent")}</DataTableTh>
                  <DataTableTh>{t("listening.colSource")}</DataTableTh>
                  <DataTableTh>{t("listening.colPublished")}</DataTableTh>
                  <DataTableTh>{t("listening.colMatches")}</DataTableTh>
                  <DataTableTh>{t("listening.colReview")}</DataTableTh>
                </DataTableRow>
              </DataTableHead>
              <DataTableBody>
                {items.map((m) => (
                  <DataTableRow key={m.id}>
                    <DataTableTd>
                      <Link
                        href={`/listening/mentions/${m.id}`}
                        className="font-medium text-slate-900 hover:underline dark-tenant:text-slate-100"
                      >
                        <span className="line-clamp-2">
                          {m.content_excerpt || m.content_text || t("listening.noContent")}
                        </span>
                      </Link>
                      <p className="mt-1 text-xs text-slate-500">{m.author_display || "—"}</p>
                    </DataTableTd>
                    <DataTableTd>
                      <div className="flex flex-col gap-1">
                        <StatusBadge variant="neutral">{m.source_type}</StatusBadge>
                        <span className="text-xs text-slate-500">{m.observation_origin}</span>
                      </div>
                    </DataTableTd>
                    <DataTableTd className="whitespace-nowrap text-xs text-slate-500">
                      <div>{formatWhen(m.published_at)}</div>
                      <div>obs {formatWhen(m.observed_at)}</div>
                    </DataTableTd>
                    <DataTableTd className="text-xs text-slate-600 dark-tenant:text-slate-300">
                      {(m.matches ?? []).slice(0, 3).map((match) => match.matched_term).join(", ") || "—"}
                    </DataTableTd>
                    <DataTableTd>
                      <StatusBadge variant={m.review_state === "relevant" ? "success" : "neutral"}>
                        {m.review_state}
                      </StatusBadge>
                    </DataTableTd>
                  </DataTableRow>
                ))}
              </DataTableBody>
            </DataTable>
            <div className="mt-4 flex items-center justify-between text-sm text-slate-600 dark-tenant:text-slate-300">
              <span>{pageLabel}</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={offset <= 0}
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                >
                  {t("common.previous")}
                </button>
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={offset + limit >= total}
                  onClick={() => setOffset(offset + limit)}
                >
                  {t("common.next")}
                </button>
              </div>
            </div>
          </>
        )
      ) : null}
    </PageShell>
  );
}
