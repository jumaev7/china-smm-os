"use client";

import { useEffect } from "react";
import { useIsFetching } from "@tanstack/react-query";
import {
  cleanupDocumentInteractionBlockers,
  scheduleDocumentInteractionCleanup,
} from "@/lib/dom-cleanup";

const DASHBOARD_QUERY_ROOTS = new Set([
  "dashboard-overview",
  "system-health",
  "audit-overview",
  "workflows-summary",
]);

/** True for dashboard page widget queries (core + optional cards). */
export function isDashboardWidgetQueryKey(queryKey: readonly unknown[]): boolean {
  const head = queryKey[0];
  if (typeof head !== "string") return false;
  if (DASHBOARD_QUERY_ROOTS.has(head)) return true;
  return head.endsWith("-summary") || head.includes("-widget") || head.endsWith("-overview");
}

/**
 * Clear orphaned login/credential overlays on mount and after dashboard widget
 * queries finish (success or error). Never blocks rendering.
 */
export function useDashboardOverlayCleanup(enabled = true) {
  const pendingWidgetFetches = useIsFetching({
    predicate: (query) => enabled && isDashboardWidgetQueryKey(query.queryKey),
  });

  useEffect(() => {
    if (!enabled) return;
    cleanupDocumentInteractionBlockers();
    return scheduleDocumentInteractionCleanup();
  }, [enabled]);

  useEffect(() => {
    if (!enabled || pendingWidgetFetches > 0) return;
    cleanupDocumentInteractionBlockers();
    return scheduleDocumentInteractionCleanup();
  }, [enabled, pendingWidgetFetches]);
}
