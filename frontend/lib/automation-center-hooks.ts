"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-store";
import {
  AUTOMATION_CENTER_USES_DEMO_DATA,
  createDemoAutomations,
} from "@/lib/automation-center-demo-data";
import {
  computeAutomationSummary,
  DEFAULT_AUTOMATION_FILTERS,
  filterAutomations,
  getActiveAutomations,
  getDisabledAutomations,
  getRecentExecutions,
  getUpcomingAutomations,
  type Automation,
  type AutomationFilters,
} from "@/lib/automation-center-ui";

export function useAutomationCenter() {
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? "";
  const [filters, setFilters] = useState<AutomationFilters>(DEFAULT_AUTOMATION_FILTERS);
  const [automations, setAutomations] = useState<Automation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);
  const loadAttempt = useRef(0);

  const loadDemoData = useCallback(() => {
    setIsLoading(true);
    setIsError(false);
    const attempt = ++loadAttempt.current;

    const timer = window.setTimeout(() => {
      if (attempt !== loadAttempt.current) return;
      try {
        setAutomations(createDemoAutomations());
        setIsLoading(false);
      } catch {
        setIsError(true);
        setIsLoading(false);
      }
    }, 380);

    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!tenantId) {
      setAutomations([]);
      setIsLoading(false);
      setIsError(false);
      return;
    }
    const cleanup = loadDemoData();
    return cleanup;
  }, [tenantId, loadDemoData]);

  const retry = useCallback(() => {
    if (!tenantId) return;
    loadDemoData();
  }, [tenantId, loadDemoData]);

  const updateFilters = useCallback((patch: Partial<AutomationFilters>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
  }, []);

  const resetFilters = useCallback(() => {
    setFilters(DEFAULT_AUTOMATION_FILTERS);
  }, []);

  const toggleAutomation = useCallback((id: string) => {
    setAutomations((prev) =>
      prev.map((a) => {
        if (a.id !== id) return a;
        const nextEnabled = !a.enabled;
        return {
          ...a,
          enabled: nextEnabled,
          status: nextEnabled
            ? a.status === "paused" || a.status === "draft"
              ? "active"
              : a.status
            : "paused",
          updatedAt: new Date().toISOString(),
        };
      }),
    );
  }, []);

  const filtered = useMemo(
    () => filterAutomations(automations, filters),
    [automations, filters],
  );

  const summary = useMemo(() => computeAutomationSummary(automations), [automations]);
  const activeAutomations = useMemo(() => getActiveAutomations(automations), [automations]);
  const recentExecutions = useMemo(() => getRecentExecutions(automations), [automations]);
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
    isLoading,
    isError,
    hasActiveFilters,
    isDemoData: AUTOMATION_CENTER_USES_DEMO_DATA,
    updateFilters,
    resetFilters,
    retry,
    toggleAutomation,
  };
}
