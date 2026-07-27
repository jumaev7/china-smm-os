"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Radio } from "lucide-react";
import toast from "react-hot-toast";

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

export default function ListeningProjectsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const projectsQuery = useQuery({
    queryKey: [...LISTENING_QUERY_KEY, "projects"],
    queryFn: () => listeningApi.listProjects({ limit: 50 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      listeningApi.createProject({
        name: name.trim(),
        description: description.trim() || null,
      }),
    onSuccess: () => {
      toast.success(t("listening.projectCreated"));
      setName("");
      setDescription("");
      queryClient.invalidateQueries({ queryKey: LISTENING_QUERY_KEY });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const items = projectsQuery.data?.items ?? [];

  return (
    <PageShell wide>
      <PageHeader
        title={t("listening.configTitle")}
        subtitle={t("listening.configSubtitle")}
        icon={Radio}
        badge={<StatusBadge variant="neutral">{t("listening.readOnlyBadge")}</StatusBadge>}
      />
      <ListeningSubNav />

      <ActionBar>
        <form
          className="flex w-full flex-col gap-3 md:flex-row md:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return;
            createMutation.mutate();
          }}
        >
          <label className="flex flex-1 flex-col gap-1 text-xs text-slate-500">
            <span>{t("listening.projectName")}</span>
            <input
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark-tenant:border-slate-700 dark-tenant:bg-slate-950"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={200}
              aria-label={t("listening.projectName")}
            />
          </label>
          <label className="flex flex-[2] flex-col gap-1 text-xs text-slate-500">
            <span>{t("listening.projectDescription")}</span>
            <input
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark-tenant:border-slate-700 dark-tenant:bg-slate-950"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={4000}
              aria-label={t("listening.projectDescription")}
            />
          </label>
          <button type="submit" className="btn-primary text-sm" disabled={createMutation.isPending}>
            {t("listening.createProject")}
          </button>
        </form>
      </ActionBar>

      <div
        className="mb-6 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 dark-tenant:border-slate-800 dark-tenant:bg-slate-900 dark-tenant:text-slate-200"
        role="note"
      >
        {t("listening.configLimitations")}
      </div>

      {projectsQuery.isLoading ? <LoadingState message={t("listening.loadingProjects")} /> : null}
      {projectsQuery.isError && !projectsQuery.isLoading ? (
        <ErrorState
          title={t("listening.loadError")}
          message={getApiErrorMessage(projectsQuery.error)}
          onRetry={() => projectsQuery.refetch()}
        />
      ) : null}

      {!projectsQuery.isLoading && !projectsQuery.isError ? (
        items.length === 0 ? (
          <EmptyState title={t("listening.noProjects")} description={t("listening.noProjectsHint")} />
        ) : (
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>{t("listening.projectName")}</DataTableTh>
                <DataTableTh>{t("listening.colStatus")}</DataTableTh>
                <DataTableTh>{t("listening.colUpdated")}</DataTableTh>
                <DataTableTh>{t("listening.colActions")}</DataTableTh>
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {items.map((p) => (
                <DataTableRow key={p.id}>
                  <DataTableTd className="font-medium">
                    <Link href={`/listening/projects/${p.id}`} className="hover:underline">
                      {p.name}
                    </Link>
                    {p.description ? (
                      <p className="mt-1 line-clamp-1 text-xs font-normal text-slate-500">
                        {p.description}
                      </p>
                    ) : null}
                  </DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant={p.status === "active" ? "success" : "neutral"}>
                      {p.status}
                    </StatusBadge>
                  </DataTableTd>
                  <DataTableTd className="text-xs text-slate-500">
                    {new Date(p.updated_at).toLocaleString()}
                  </DataTableTd>
                  <DataTableTd>
                    <Link href={`/listening/projects/${p.id}`} className="btn-secondary text-xs">
                      {t("listening.open")}
                    </Link>
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
