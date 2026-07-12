import type { LucideIcon } from "lucide-react";
import { Zap } from "lucide-react";

export type AutomationStatus = "active" | "paused" | "failed" | "draft";

export type ExecutionResult = "success" | "failed" | "skipped";

export type AutomationSectionFilter = "all" | "active" | "paused" | "failed" | "draft" | "disabled";

export interface AutomationStep {
  id: string;
  label: string;
}

export interface AutomationExecution {
  id: string;
  automationId: string;
  automationName: string;
  timestamp: string;
  result: ExecutionResult;
  detail?: string;
  durationMs?: number;
}

export interface RelatedModule {
  label: string;
  href: string;
}

export interface Automation {
  id: string;
  name: string;
  description: string;
  status: AutomationStatus;
  enabled: boolean;
  steps: AutomationStep[];
  conditions: string[];
  relatedModules: RelatedModule[];
  lastExecution?: string | null;
  successRate: number;
  executionHistory: AutomationExecution[];
  nextScheduled?: string | null;
  icon: LucideIcon;
  iconClassName: string;
  createdAt: string;
  updatedAt: string;
}

export interface AutomationFilters {
  section: AutomationSectionFilter;
  search: string;
}

export interface AutomationSummary {
  healthScore: number;
  activeCount: number;
  pausedCount: number;
  failedCount: number;
  draftCount: number;
  disabledCount: number;
  totalExecutions24h: number;
  successRateOverall: number;
}

export const STATUS_LABELS: Record<AutomationStatus, string> = {
  active: "Active",
  paused: "Paused",
  failed: "Failed",
  draft: "Draft",
};

export const STATUS_STYLES: Record<AutomationStatus, string> = {
  active: "bg-emerald-100 text-emerald-700 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-300",
  paused: "bg-amber-100 text-amber-800 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-300",
  failed: "bg-red-100 text-red-700 dark-tenant:bg-red-500/15 dark-tenant:text-red-300",
  draft: "bg-slate-100 text-slate-600 dark-tenant:bg-white/10 dark-tenant:text-slate-400",
};

export const STATUS_DOT_STYLES: Record<AutomationStatus, string> = {
  active: "bg-emerald-500",
  paused: "bg-amber-500",
  failed: "bg-red-500",
  draft: "bg-slate-400",
};

export const EXECUTION_RESULT_STYLES: Record<ExecutionResult, string> = {
  success: "bg-emerald-100 text-emerald-700 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-300",
  failed: "bg-red-100 text-red-700 dark-tenant:bg-red-500/15 dark-tenant:text-red-300",
  skipped: "bg-slate-100 text-slate-600 dark-tenant:bg-white/10 dark-tenant:text-slate-400",
};

export const EXECUTION_RESULT_DOT: Record<ExecutionResult, string> = {
  success: "bg-emerald-500",
  failed: "bg-red-500",
  skipped: "bg-slate-400",
};

export const EXECUTION_RESULT_LABELS: Record<ExecutionResult, string> = {
  success: "Success",
  failed: "Failed",
  skipped: "Skipped",
};

export const SECTION_FILTERS: { id: AutomationSectionFilter; labelKey: string }[] = [
  { id: "all", labelKey: "automationCenter.filters.all" },
  { id: "active", labelKey: "automationCenter.filters.active" },
  { id: "paused", labelKey: "automationCenter.filters.paused" },
  { id: "failed", labelKey: "automationCenter.filters.failed" },
  { id: "draft", labelKey: "automationCenter.filters.draft" },
  { id: "disabled", labelKey: "automationCenter.filters.disabled" },
];

export const DEFAULT_AUTOMATION_FILTERS: AutomationFilters = {
  section: "all",
  search: "",
};

export function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const future = diff < 0;
  const absDiff = Math.abs(diff);
  const mins = Math.floor(absDiff / 60_000);
  if (mins < 1) return future ? "in a moment" : "just now";
  if (mins < 60) return future ? `in ${mins}m` : `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return future ? `in ${hours}h` : `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return future ? "tomorrow" : "yesterday";
  if (days < 7) return future ? `in ${days}d` : `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  return `${mins}m ${secs % 60}s`;
}

export function formatSuccessRate(rate: number): string {
  return `${Math.round(rate)}%`;
}

export function computeAutomationSummary(automations: Automation[]): AutomationSummary {
  const active = automations.filter((a) => a.enabled && a.status === "active");
  const paused = automations.filter((a) => a.status === "paused" || (a.enabled === false && a.status !== "draft"));
  const failed = automations.filter((a) => a.status === "failed");
  const draft = automations.filter((a) => a.status === "draft");
  const disabled = automations.filter((a) => !a.enabled);

  const allExecutions = automations.flatMap((a) => a.executionHistory);
  const dayAgo = Date.now() - 24 * 60 * 60 * 1000;
  const recent = allExecutions.filter((e) => new Date(e.timestamp).getTime() >= dayAgo);
  const successful = recent.filter((e) => e.result === "success");

  const rates = automations.filter((a) => a.enabled && a.successRate > 0).map((a) => a.successRate);
  const avgRate = rates.length > 0 ? rates.reduce((s, r) => s + r, 0) / rates.length : 100;

  const healthScore = Math.round(
    (active.length / Math.max(automations.filter((a) => a.enabled).length, 1)) * 40 +
      avgRate * 0.5 +
      (failed.length === 0 ? 10 : Math.max(0, 10 - failed.length * 5)),
  );

  return {
    healthScore: Math.min(100, Math.max(0, healthScore)),
    activeCount: active.length,
    pausedCount: paused.length,
    failedCount: failed.length,
    draftCount: draft.length,
    disabledCount: disabled.length,
    totalExecutions24h: recent.length,
    successRateOverall: recent.length > 0 ? Math.round((successful.length / recent.length) * 100) : avgRate,
  };
}

export function getRecentExecutions(automations: Automation[], limit = 8): AutomationExecution[] {
  return automations
    .flatMap((a) => a.executionHistory)
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, limit);
}

export function getUpcomingAutomations(automations: Automation[]): Automation[] {
  return automations
    .filter((a) => a.enabled && a.nextScheduled)
    .sort(
      (a, b) =>
        new Date(a.nextScheduled!).getTime() - new Date(b.nextScheduled!).getTime(),
    );
}

export function getDisabledAutomations(automations: Automation[]): Automation[] {
  return automations.filter((a) => !a.enabled || a.status === "draft");
}

export function getActiveAutomations(automations: Automation[]): Automation[] {
  return automations.filter((a) => a.enabled && (a.status === "active" || a.status === "failed"));
}

function matchesSearch(automation: Automation, search: string): boolean {
  if (!search.trim()) return true;
  const q = search.trim().toLowerCase();
  return (
    automation.name.toLowerCase().includes(q) ||
    automation.description.toLowerCase().includes(q) ||
    automation.steps.some((s) => s.label.toLowerCase().includes(q))
  );
}

export function filterAutomations(
  automations: Automation[],
  filters: AutomationFilters,
): Automation[] {
  return automations.filter((a) => {
    if (!matchesSearch(a, filters.search)) return false;
    if (filters.section === "all") return true;
    if (filters.section === "active") return a.enabled && a.status === "active";
    if (filters.section === "paused") return a.status === "paused";
    if (filters.section === "failed") return a.status === "failed";
    if (filters.section === "draft") return a.status === "draft";
    if (filters.section === "disabled") return !a.enabled;
    return true;
  });
}

export const EMPTY_STATE_ICON = Zap;
