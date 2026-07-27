"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Radio } from "lucide-react";
import toast from "react-hot-toast";

import { ListeningSubNav } from "@/components/listening/ListeningSubNav";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  ActionBar,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import {
  LISTENING_QUERY_KEY,
  getApiErrorMessage,
  listeningApi,
  type ListeningProjectStatus,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function ListeningProjectDetailPage() {
  const { t } = useTranslation();
  const params = useParams();
  const projectId = String(params.projectId || "");
  const queryClient = useQueryClient();

  const [subjectName, setSubjectName] = useState("");
  const [subjectAliases, setSubjectAliases] = useState("");
  const [queryName, setQueryName] = useState("");
  const [includeTerms, setIncludeTerms] = useState("");
  const [excludeTerms, setExcludeTerms] = useState("");
  const [importJson, setImportJson] = useState(
    '[\n  {\n    "provider_external_id": "demo-1",\n    "content_text": "Sample mention about Acme brand",\n    "author_display": "observer",\n    "language": "en",\n    "canonical_url": "https://example.com/p/1"\n  }\n]',
  );

  const projectQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "project", projectId],
    queryFn: () => listeningApi.getProject(projectId).then((r) => r.data),
    enabled: Boolean(projectId),
    ...QUERY_OPTS,
  });
  const subjectsQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "subjects", projectId],
    queryFn: () => listeningApi.listSubjects(projectId).then((r) => r.data),
    enabled: Boolean(projectId),
    ...QUERY_OPTS,
  });
  const queriesQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "queries", projectId],
    queryFn: () => listeningApi.listQueries(projectId).then((r) => r.data),
    enabled: Boolean(projectId),
    ...QUERY_OPTS,
  });
  const sourcesQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "sources", projectId],
    queryFn: () => listeningApi.listSources(projectId).then((r) => r.data),
    enabled: Boolean(projectId),
    ...QUERY_OPTS,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: LISTENING_QUERY_KEY });

  const statusMutation = useMutation({
    mutationFn: (status: ListeningProjectStatus) =>
      listeningApi.updateProject(projectId, { status }),
    onSuccess: () => {
      toast.success(t("listening.projectUpdated"));
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const subjectMutation = useMutation({
    mutationFn: () =>
      listeningApi.createSubject(projectId, {
        subject_type: "own_brand",
        canonical_name: subjectName.trim(),
        aliases: subjectAliases
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      toast.success(t("listening.subjectCreated"));
      setSubjectName("");
      setSubjectAliases("");
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const queryMutation = useMutation({
    mutationFn: () =>
      listeningApi.createQuery(projectId, {
        name: queryName.trim(),
        include_terms: includeTerms
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
        exclude_terms: excludeTerms
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      toast.success(t("listening.queryCreated"));
      setQueryName("");
      setIncludeTerms("");
      setExcludeTerms("");
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const fixtureMutation = useMutation({
    mutationFn: () => listeningApi.fixtureIngest(projectId),
    onSuccess: (res) => {
      toast.success(
        t("listening.ingestDone", {
          created: String(res.data.created_count),
          duplicates: String(res.data.duplicate_count),
        }),
      );
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const importMutation = useMutation({
    mutationFn: () => {
      let items: Record<string, unknown>[];
      try {
        const parsed = JSON.parse(importJson);
        if (!Array.isArray(parsed)) throw new Error("not array");
        items = parsed;
      } catch {
        throw new Error(t("listening.invalidImportJson"));
      }
      return listeningApi.importMentions(projectId, { items });
    },
    onSuccess: (res) => {
      toast.success(
        t("listening.ingestDone", {
          created: String(res.data.created_count),
          duplicates: String(res.data.duplicate_count),
        }),
      );
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const project = projectQuery.data;
  const loading =
    projectQuery.isLoading || subjectsQuery.isLoading || queriesQuery.isLoading || sourcesQuery.isLoading;

  return (
    <PageShell wide>
      <PageHeader
        title={project?.name || t("listening.projectDetail")}
        subtitle={t("listening.projectDetailSubtitle")}
        icon={Radio}
        badge={<StatusBadge variant="neutral">{t("listening.readOnlyBadge")}</StatusBadge>}
        actions={
          <Link href="/listening/projects" className="btn-secondary text-sm">
            {t("listening.backToProjects")}
          </Link>
        }
      />
      <ListeningSubNav />

      {loading ? <LoadingState message={t("listening.loadingProject")} /> : null}
      {projectQuery.isError ? (
        <ErrorState
          title={t("listening.loadError")}
          message={getApiErrorMessage(projectQuery.error)}
          onRetry={() => projectQuery.refetch()}
        />
      ) : null}

      {project ? (
        <>
          <ActionBar>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge variant={project.status === "active" ? "success" : "neutral"}>
                {project.status}
              </StatusBadge>
              {(["active", "paused", "archived"] as ListeningProjectStatus[]).map((status) => (
                <button
                  key={status}
                  type="button"
                  className="btn-secondary text-xs"
                  disabled={statusMutation.isPending || project.status === status}
                  onClick={() => statusMutation.mutate(status)}
                >
                  {status}
                </button>
              ))}
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={fixtureMutation.isPending}
                onClick={() => fixtureMutation.mutate()}
              >
                {t("listening.runFixture")}
              </button>
            </div>
          </ActionBar>

          <div className="grid gap-6 lg:grid-cols-2">
            <PageSection title={t("listening.subjects")}>
              <form
                className="mb-4 space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!subjectName.trim()) return;
                  subjectMutation.mutate();
                }}
              >
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark-tenant:border-slate-700 dark-tenant:bg-slate-950"
                  placeholder={t("listening.subjectName")}
                  value={subjectName}
                  onChange={(e) => setSubjectName(e.target.value)}
                  aria-label={t("listening.subjectName")}
                />
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark-tenant:border-slate-700 dark-tenant:bg-slate-950"
                  placeholder={t("listening.aliasesPlaceholder")}
                  value={subjectAliases}
                  onChange={(e) => setSubjectAliases(e.target.value)}
                  aria-label={t("listening.aliasesPlaceholder")}
                />
                <button type="submit" className="btn-secondary text-sm" disabled={subjectMutation.isPending}>
                  {t("listening.addSubject")}
                </button>
              </form>
              {(subjectsQuery.data ?? []).length === 0 ? (
                <EmptyState title={t("listening.noSubjects")} description={t("listening.noSubjectsHint")} />
              ) : (
                <ul className="space-y-2 text-sm">
                  {(subjectsQuery.data ?? []).map((s) => (
                    <li key={s.id} className="rounded-md border border-slate-200 px-3 py-2 dark-tenant:border-slate-800">
                      <div className="font-medium">{s.canonical_name}</div>
                      <div className="text-xs text-slate-500">
                        {s.subject_type}
                        {(s.aliases ?? []).length ? ` · ${s.aliases.join(", ")}` : ""}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </PageSection>

            <PageSection title={t("listening.queries")}>
              <form
                className="mb-4 space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!queryName.trim()) return;
                  queryMutation.mutate();
                }}
              >
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark-tenant:border-slate-700 dark-tenant:bg-slate-950"
                  placeholder={t("listening.queryName")}
                  value={queryName}
                  onChange={(e) => setQueryName(e.target.value)}
                  aria-label={t("listening.queryName")}
                />
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark-tenant:border-slate-700 dark-tenant:bg-slate-950"
                  placeholder={t("listening.includeTermsPlaceholder")}
                  value={includeTerms}
                  onChange={(e) => setIncludeTerms(e.target.value)}
                  aria-label={t("listening.includeTermsPlaceholder")}
                />
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark-tenant:border-slate-700 dark-tenant:bg-slate-950"
                  placeholder={t("listening.excludeTermsPlaceholder")}
                  value={excludeTerms}
                  onChange={(e) => setExcludeTerms(e.target.value)}
                  aria-label={t("listening.excludeTermsPlaceholder")}
                />
                <button type="submit" className="btn-secondary text-sm" disabled={queryMutation.isPending}>
                  {t("listening.addQuery")}
                </button>
              </form>
              {(queriesQuery.data ?? []).length === 0 ? (
                <EmptyState title={t("listening.noQueries")} description={t("listening.noQueriesHint")} />
              ) : (
                <ul className="space-y-2 text-sm">
                  {(queriesQuery.data ?? []).map((q) => (
                    <li key={q.id} className="rounded-md border border-slate-200 px-3 py-2 dark-tenant:border-slate-800">
                      <div className="font-medium">{q.name}</div>
                      <div className="text-xs text-slate-500">
                        include: {(q.include_terms ?? []).join(", ") || "—"}
                      </div>
                      <div className="text-xs text-slate-500">
                        exclude: {(q.exclude_terms ?? []).join(", ") || "—"}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </PageSection>
          </div>

          <PageSection title={t("listening.sources")} className="mt-6">
            {(sourcesQuery.data ?? []).length === 0 ? (
              <EmptyState title={t("listening.noSources")} description={t("listening.noSourcesHint")} />
            ) : (
              <ul className="grid gap-3 md:grid-cols-2">
                {(sourcesQuery.data ?? []).map((s) => (
                  <li key={s.id} className="rounded-lg border border-slate-200 px-4 py-3 dark-tenant:border-slate-800">
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-medium">{s.display_name}</p>
                      <StatusBadge variant="neutral">{s.capability_status}</StatusBadge>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {s.source_type} · freshness {s.freshness_status}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </PageSection>

          <PageSection title={t("listening.manualImport")} className="mt-6">
            <p className="mb-3 text-sm text-slate-600 dark-tenant:text-slate-300">
              {t("listening.manualImportHint")}
            </p>
            <textarea
              className="min-h-[180px] w-full rounded-md border border-slate-300 bg-white p-3 font-mono text-xs dark-tenant:border-slate-700 dark-tenant:bg-slate-950"
              value={importJson}
              onChange={(e) => setImportJson(e.target.value)}
              aria-label={t("listening.manualImport")}
            />
            <button
              type="button"
              className="btn-primary mt-3 text-sm"
              disabled={importMutation.isPending}
              onClick={() => importMutation.mutate()}
            >
              {t("listening.runImport")}
            </button>
          </PageSection>
        </>
      ) : null}
    </PageShell>
  );
}
