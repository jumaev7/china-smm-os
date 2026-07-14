"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AUTOMATION_EXECUTIONS_QUERY_KEY,
  AUTOMATION_JOBS_QUERY_KEY,
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
  mapApiJobToApp,
  mapKpisToSummary,
  type Automation,
  type AutomationFilters,
} from "@/lib/automation-center-ui";

const EXECUTIONS_PAGE_SIZE = 20;
const JOBS_PAGE_SIZE = 20;

export function useAutomationCenter() {
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? "";
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<AutomationFilters>(DEFAULT_AUTOMATION_FILTERS);
  const [mutatingId, setMutatingId] = useState<string | null>(null);
  const [jobMutatingId, setJobMutatingId] = useState<string | null>(null);
  const [runState, setRunState] = useState<{
    flowId: string;
    status: "pending" | "success" | "failed";
    message?: string;
  } | null>(null);
  const [retryState, setRetryState] = useState<{
    executionId: string;
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

  const jobsQuery = useQuery({
    queryKey: [...AUTOMATION_JOBS_QUERY_KEY, tenantId],
    queryFn: () =>
      automationApi.getJobs({ page: 1, page_size: JOBS_PAGE_SIZE }).then((r) => r.data),
    enabled: Boolean(tenantId),
  });

  const jobs = useMemo(
    () => (jobsQuery.data?.items ?? []).map((row) => mapApiJobToApp(row)),
    [jobsQuery.data],
  );

  const nextScheduledByFlow = useMemo(() => {
    const map = new Map<string, string>();
    for (const job of jobs) {
      if (job.status !== "scheduled") continue;
      const prev = map.get(job.flowId);
      if (!prev || new Date(job.scheduledFor).getTime() < new Date(prev).getTime()) {
        map.set(job.flowId, job.scheduledFor);
      }
    }
    return map;
  }, [jobs]);

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
      mapApiFlowToApp(
        flow,
        execByFlow.get(flow.id) ?? [],
        nextScheduledByFlow.get(flow.id) ?? null,
      ),
    );
  }, [flowsQuery.data, executionsQuery.data, nextScheduledByFlow]);

  const summary = useMemo(() => {
    if (kpisQuery.data) return mapKpisToSummary(kpisQuery.data);
    return computeAutomationSummary(automations);
  }, [kpisQuery.data, automations]);

  const invalidateAll = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: AUTOMATION_LIST_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: AUTOMATION_KPI_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: AUTOMATION_EXECUTIONS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: AUTOMATION_JOBS_QUERY_KEY }),
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

  const retryMutation = useMutation({
    mutationFn: (executionId: string) =>
      automationApi.retryExecution(executionId).then((r) => r.data),
    onMutate: (executionId) => {
      setRetryState({ executionId, status: "pending" });
    },
    onSuccess: (data) => {
      setRetryState({
        executionId: data.retry_of_execution_id,
        status: data.status === "success" ? "success" : "failed",
        message:
          data.status === "success"
            ? undefined
            : data.error_message ?? "Retry failed",
      });
    },
    onError: (error: Error, executionId) => {
      const ax = error as Error & { response?: { data?: { detail?: string } } };
      const detail = ax.response?.data?.detail;
      setRetryState({
        executionId,
        status: "failed",
        message: typeof detail === "string" ? detail : error.message,
      });
    },
    onSettled: async () => {
      await invalidateAll();
    },
  });

  const cancelJobMutation = useMutation({
    mutationFn: (jobId: string) => automationApi.cancelJob(jobId).then((r) => r.data),
    onMutate: (jobId) => setJobMutatingId(jobId),
    onSettled: async () => {
      setJobMutatingId(null);
      await invalidateAll();
    },
  });

  const requeueJobMutation = useMutation({
    mutationFn: (jobId: string) => automationApi.requeueJob(jobId).then((r) => r.data),
    onMutate: (jobId) => setJobMutatingId(jobId),
    onSettled: async () => {
      setJobMutatingId(null);
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
    void jobsQuery.refetch();
  }, [flowsQuery, kpisQuery, executionsQuery, jobsQuery]);

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

  const retryExecution = useCallback(
    (executionId: string) => {
      if (retryMutation.isPending) return;
      retryMutation.mutate(executionId);
    },
    [retryMutation],
  );

  const cancelJob = useCallback(
    (jobId: string) => {
      if (cancelJobMutation.isPending) return;
      cancelJobMutation.mutate(jobId);
    },
    [cancelJobMutation],
  );

  const requeueJob = useCallback(
    (jobId: string) => {
      if (requeueJobMutation.isPending) return;
      requeueJobMutation.mutate(jobId);
    },
    [requeueJobMutation],
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
    jobs,
    filters,
    summary,
    isLoading: flowsQuery.isLoading || kpisQuery.isLoading,
    isError: flowsQuery.isError || kpisQuery.isError,
    hasActiveFilters,
    isDemoData: false,
    mutatingId,
    jobMutatingId,
    runState,
    retryState,
    updateFilters,
    resetFilters,
    retry,
    toggleAutomation,
    runTest,
    retryExecution,
    cancelJob,
    requeueJob,
  };
}
