"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clientsApi,
  getApiErrorMessage,
  normalizeList,
  operatorWorkspaceApi,
  type Client,
  type OperatorWorkspaceActionResult,
} from "@/lib/api";
import { useOnboardingTenantId } from "@/lib/onboarding-hooks";
import {
  DEFAULT_WORKSPACE_FILTERS,
  type WorkspaceFilters,
} from "@/lib/operator-workspace-ui";

export const OPERATOR_WORKSPACE_QUERY_KEY = ["operator-workspace"] as const;

export function useOperatorWorkspace() {
  const tenantId = useOnboardingTenantId();
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<WorkspaceFilters>(DEFAULT_WORKSPACE_FILTERS);
  const [page, setPage] = useState(1);
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const params = useMemo(
    () => ({
      client_id: filters.clientId ?? undefined,
      category: filters.category === "all" ? undefined : filters.category,
      priority: filters.priority === "all" ? undefined : filters.priority,
      responsible_party: filters.responsible === "all" ? undefined : filters.responsible,
      page,
      page_size: 50,
    }),
    [filters, page],
  );

  const itemsQuery = useQuery({
    queryKey: [...OPERATOR_WORKSPACE_QUERY_KEY, "items", tenantId, params],
    queryFn: () => operatorWorkspaceApi.listItems(params).then((r) => r.data),
    enabled: Boolean(tenantId),
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });

  const summaryQuery = useQuery({
    queryKey: [...OPERATOR_WORKSPACE_QUERY_KEY, "summary", tenantId, filters.clientId],
    queryFn: () =>
      operatorWorkspaceApi
        .getSummary(filters.clientId ? { client_id: filters.clientId } : undefined)
        .then((r) => r.data),
    enabled: Boolean(tenantId),
    staleTime: 30_000,
  });

  const clientsQuery = useQuery({
    queryKey: ["clients", "operator-workspace", tenantId],
    queryFn: () => clientsApi.list({ limit: 300 }).then((r) => r.data),
    enabled: Boolean(tenantId),
    staleTime: 60_000,
  });

  const clients = useMemo(
    () => normalizeList<Client>(clientsQuery.data),
    [clientsQuery.data],
  );

  const refreshWorkspace = useCallback(async () => {
    await Promise.all([
      itemsQuery.refetch(),
      summaryQuery.refetch(),
    ]);
  }, [itemsQuery, summaryQuery]);

  const actionMutation = useMutation({
    mutationFn: async ({
      attentionId,
      actionId,
      note,
    }: {
      attentionId: string;
      actionId: string;
      note?: string;
    }) => {
      const key = `${attentionId}:${actionId}`;
      setPendingKey(key);
      try {
        const res = await operatorWorkspaceApi.executeAction(
          attentionId,
          actionId,
          note ? { note } : undefined,
        );
        return res.data;
      } finally {
        setPendingKey(null);
      }
    },
    onSuccess: async (result: OperatorWorkspaceActionResult) => {
      if (result.refresh_recommended !== false) {
        await queryClient.invalidateQueries({ queryKey: OPERATOR_WORKSPACE_QUERY_KEY });
        await refreshWorkspace();
      }
    },
  });

  const updateFilters = useCallback((patch: Partial<WorkspaceFilters>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
    setPage(1);
  }, []);

  const resetFilters = useCallback(() => {
    setFilters(DEFAULT_WORKSPACE_FILTERS);
    setPage(1);
  }, []);

  const applySummaryFilter = useCallback(
    (category?: string, responsible?: string) => {
      setFilters((prev) => ({
        ...prev,
        category: (category as WorkspaceFilters["category"]) ?? "all",
        responsible: (responsible as WorkspaceFilters["responsible"]) ?? "all",
      }));
      setPage(1);
    },
    [],
  );

  const isActionPending = useCallback(
    (attentionId: string, actionId: string) =>
      pendingKey === `${attentionId}:${actionId}` ||
      (actionMutation.isPending && pendingKey?.startsWith(`${attentionId}:`) === true),
    [pendingKey, actionMutation.isPending],
  );

  return {
    filters,
    updateFilters,
    resetFilters,
    applySummaryFilter,
    page,
    setPage,
    clients,
    items: itemsQuery.data?.items ?? [],
    total: itemsQuery.data?.total ?? 0,
    summary: summaryQuery.data?.summary ?? itemsQuery.data?.summary,
    isLoading: itemsQuery.isLoading,
    isError: itemsQuery.isError,
    error: itemsQuery.error,
    retry: () => {
      void itemsQuery.refetch();
      void summaryQuery.refetch();
    },
    refreshWorkspace,
    executeAction: actionMutation.mutateAsync,
    actionError: actionMutation.error ? getApiErrorMessage(actionMutation.error) : null,
    isActionPending,
    hasActiveFilters:
      filters.category !== "all" ||
      filters.priority !== "all" ||
      filters.responsible !== "all" ||
      Boolean(filters.clientId),
  };
}
