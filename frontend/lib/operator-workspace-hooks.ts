"use client";

import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { clientsApi, normalizeList, operatorWorkspaceApi, type Client } from "@/lib/api";
import { useOnboardingTenantId } from "@/lib/onboarding-hooks";
import {
  DEFAULT_WORKSPACE_FILTERS,
  type WorkspaceFilters,
} from "@/lib/operator-workspace-ui";

export const OPERATOR_WORKSPACE_QUERY_KEY = ["operator-workspace"] as const;

export function useOperatorWorkspace() {
  const tenantId = useOnboardingTenantId();
  const [filters, setFilters] = useState<WorkspaceFilters>(DEFAULT_WORKSPACE_FILTERS);
  const [page, setPage] = useState(1);

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
    // Prefer dedicated summary endpoint so category/priority filters do not
    // rewrite unrelated card totals. Items payload summary is already unfiltered
    // by client scope only, but summaryQuery mirrors that contract explicitly.
    summary: summaryQuery.data?.summary ?? itemsQuery.data?.summary,
    isLoading: itemsQuery.isLoading,
    isError: itemsQuery.isError,
    error: itemsQuery.error,
    retry: () => {
      void itemsQuery.refetch();
      void summaryQuery.refetch();
    },
    hasActiveFilters:
      filters.category !== "all" ||
      filters.priority !== "all" ||
      filters.responsible !== "all" ||
      Boolean(filters.clientId),
  };
}
