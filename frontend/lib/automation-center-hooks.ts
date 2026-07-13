"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AUTOMATION_EXECUTIONS_QUERY_KEY,
  AUTOMATION_KPI_QUERY_KEY,
  AUTOMATION_LIST_QUERY_KEY,
  automationApi,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-store";
import {
  computeAutomationSummary,
  DEFAULT_AUTOMATION_FILTERS,
  filterAutomations,
  getActiveAutomations,
  getDisabledAutomations,
  getRecentExecutions,
  getUpcomingAutomations,
  mapApiExecutionToApp,
  mapApiFlowToApp,
  mapKpisToSummary,
  type Automation,
  type AutomationFilters,
} from "@/lib/automation-center-ui";

const EXECUTIONS_PAGE_SIZE = 20;

export function useAutomationCenter() {
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? "";
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<AutomationFilters>(DEFAULT_AUTOMATION_FILTERS);
  const [mutatingId, setMutatingId] = useState<string | null>(null);
  const [runState, setRunState] = useState<{
    flowId: string;
    status: "pending" | "success" | "failed";
    message?: string;
  } | null>(null);

  const flowsQuery = useQuery({
    queryKey: [...AUTOMATION_LIST_QUERY_KEY, tenantId, filters],
    queryFn: () => automationApi.getFlows().then((r) => r.data),
    enabled: Boolean(tenantId),
  });

  const kpisQuery = useQuery({
    queryKey: [...AUTOMATION_KPI_QUERY_KEY, tenantId],
    queryFn: () => automationApi.getKpis().then((r) => r.data),
    enabled: Boolean(tenantId),
  });

  const executionsQuery = useQuery({
    queryKey: [...AUTOMATION_EXECUTIONS_QUERY_KEY, tenantId],
    queryFn: () =>
      automationApi
        .getExecutions({ page: 1, page_size: EXECUTIONS_PAGE_SIZE })
        .then((r) => r.data),
    enabled: Boolean(tenantId),
  });

  const automations = useMemo(() => {
    if (!flowsQuery.data) return [];
    const execByFlow = new Map<string, ReturnType<typeof mapApiExecutionToApp>[]>();
    for (const row of executionsQuery.data?.items ?? []) {
      const mapped = mapApiExecutionToApp(row);
      const list = execByFlow.get(mapped.automationId) ?? [];
      list.push(mapped);
      execByFlow.set(mapped.automationId, list);
    }
    return flowsQuery.data.items.map((flow) =>
      mapApiFlowToApp(flow, execByFlow.get(flow.id) ?? []),
    );
  }, [flowsQuery.data, executionsQuery.data]);

  const summary = useMemo(() => {
    if (kpisQuery.data) return mapKpisToSummary(kpisQuery.data);
    return computeAutomationSummary(automations);
  }, [kpisQuery.data, automations]);

  const invalidateAll = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: AUTOMATION_LIST_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: AUTOMATION_KPI_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: AUTOMATION_EXECUTIONS_QUERY_KEY }),
    ]);
  }, [queryClient]);

  const toggleMutation = useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) => {
      setMutatingId(id);
      if (enabled) {
        return automationApi.pauseFlow(id).then((r) => r.data);
      }
      return automationApi.enableFlow(id).then((r) => r.data);
    },
    onSettled: async () => {
      setMutatingId(null);
      await invalidateAll();
    },
  });

  const runMutation = useMutation({
    mutationFn: (id: string) => automationApi.runFlow(id).then((r) => r.data),
    onMutate: (id) => {
      setRunState({ flowId: id, status: "pending" });
    },
    onSuccess: (data) => {
      setRunState({
        flowId: data.flow_id,
        status: data.status === "success" ? "success" : "failed",
        message: data.error_message ?? undefined,
      });
    },
    onError: (error: Error) => {
      setRunState({ flowId: "", status: "failed", message: error.message });
    },
    onSettled: async () => {
      await invalidateAll();
    },
  });

  const updateFilters = useCallback((patch: Partial<AutomationFilters>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
  }, []);

  const resetFilters = useCallback(() => {
    setFilters(DEFAULT_AUTOMATION_FILTERS);
  }, []);

  const retry = useCallback(() => {
    void flowsQuery.refetch();
    void kpisQuery.refetch();
    void executionsQuery.refetch();
  }, [flowsQuery, kpisQuery, executionsQuery]);

  const toggleAutomation = useCallback(
    (id: string) => {
      const flow = automations.find((a) => a.id === id);
      if (!flow || mutatingId === id) return;
      toggleMutation.mutate({ id, enabled: flow.enabled });
    },
    [automations, mutatingId, toggleMutation],
  );

  const runTest = useCallback(
    (id: string) => {
      if (runMutation.isPending) return;
      runMutation.mutate(id);
    },
    [runMutation],
  );

  const filtered = useMemo(
    () => filterAutomations(automations, filters),
    [automations, filters],
  );

  const activeAutomations = useMemo(() => getActiveAutomations(automations), [automations]);
  const recentExecutions = useMemo(() => {
    const fromApi = (executionsQuery.data?.items ?? []).map((e) => mapApiExecutionToApp(e));
    if (fromApi.length > 0) return fromApi.slice(0, 8);
    return getRecentExecutions(automations);
  }, [executionsQuery.data, automations]);
  const upcomingAutomations = useMemo(() => getUpcomingAutomations(automations), [automations]);
  const disabledAutomations = useMemo(() => getDisabledAutomations(automations), [automations]);

  const hasActiveFilters =
    filters.section !== "all" || filters.search.trim().length > 0;

  return {
    tenantId,
    automations,
    filtered,
    activeAutomations,
    recentExecutions,
    upcomingAutomations,
    disabledAutomations,
    filters,
    summary,
    isLoading: flowsQuery.isLoading || kpisQuery.isLoading,
    isError: flowsQuery.isError || kpisQuery.isError,
    hasActiveFilters,
    isDemoData: false,
    mutatingId,
    runState,
    updateFilters,
    resetFilters,
    retry,
    toggleAutomation,
    runTest,
  };
}
