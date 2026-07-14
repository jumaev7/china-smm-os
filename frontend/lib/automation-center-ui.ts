import type { LucideIcon } from "lucide-react";
import {
  Instagram,
  ShoppingBag,
  Trophy,
  UserPlus,
  XCircle,
  Zap,
  Bell,
  Activity,
  HeartPulse,
} from "lucide-react";
import type {
  AutomationActionType,
  AutomationExecutionSummary as ApiExecution,
  AutomationFlowDetail,
  AutomationFlowSummary,
  AutomationJobSummary as ApiJob,
  AutomationKpiResponse,
} from "@/lib/api";

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
  executionKind?: "event" | "manual" | "retry";
  retryNumber?: number;
  retryEligible?: boolean;
  retryBlockedReason?: string;
  isRetryable?: boolean | null;
  errorCategory?: string | null;
  rootExecutionId?: string | null;
  retryOfExecutionId?: string | null;
  triggerEvent?: string;
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
  retryCountToday?: number;
  retrySuccessCountToday?: number;
  partialPublishFailuresToday?: number;
  averageDurationMs?: number | null;
  executionsToday?: number;
  successRateToday?: number;
  scheduledJobs?: number;
  dueJobs?: number;
  runningJobs?: number;
  failedJobs?: number;
  deadLetterJobs?: number;
  recoveredLeasesToday?: number;
  automaticRetriesToday?: number;
  automaticRetrySuccessToday?: number;
  averageScheduleDelayMs?: number | null;
}

export type AutomationJobStatusUi =
  | "scheduled"
  | "leased"
  | "running"
  | "succeeded"
  | "failed"
  | "dead_letter"
  | "cancelled";

export interface AutomationJobRow {
  id: string;
  flowId: string;
  flowName: string;
  executionId?: string | null;
  rootExecutionId?: string | null;
  status: AutomationJobStatusUi;
  scheduledFor: string;
  availableAt: string;
  attemptNumber: number;
  maxAttempts: number;
  errorMessage?: string | null;
  canCancel: boolean;
  canRequeue: boolean;
  createdAt: string;
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

const TRIGGER_LABELS: Record<string, string> = {
  "tenant.content.publish_failed": "Publishing failed",
  "tenant.content.publish_partial_failed": "Partial publishing failure",
  "tenant.integration.disconnected": "Integration disconnected",
  "tenant.buyer.created": "Buyer created",
  "tenant.crm.lead_created": "CRM lead created",
  "tenant.crm.deal_stage_changed": "Deal stage changed",
  "tenant.customer_success.milestone": "Journey milestone",
  "tenant.onboarding.platform_ready": "Platform ready",
};

const ACTION_LABELS: Record<AutomationActionType, string> = {
  create_notification: "Create notification",
  create_crm_lead: "Create CRM lead",
  update_customer_success_progress: "Update customer success",
  record_activity: "Record activity",
};

const CATEGORY_ICONS: Record<string, { icon: LucideIcon; iconClassName: string }> = {
  publishing: {
    icon: XCircle,
    iconClassName: "text-red-600 bg-red-50 dark-tenant:bg-red-500/10 dark-tenant:text-red-400",
  },
  integrations: {
    icon: Instagram,
    iconClassName: "text-pink-600 bg-pink-50 dark-tenant:bg-pink-500/10 dark-tenant:text-pink-400",
  },
  crm: {
    icon: UserPlus,
    iconClassName: "text-blue-600 bg-blue-50 dark-tenant:bg-blue-500/10 dark-tenant:text-blue-400",
  },
  customer_success: {
    icon: Trophy,
    iconClassName: "text-amber-600 bg-amber-50 dark-tenant:bg-amber-500/10 dark-tenant:text-amber-400",
  },
  automation: {
    icon: Zap,
    iconClassName: "text-violet-600 bg-violet-50 dark-tenant:bg-violet-500/10 dark-tenant:text-violet-400",
  },
};

const ACTION_ICONS: Record<AutomationActionType, LucideIcon> = {
  create_notification: Bell,
  create_crm_lead: ShoppingBag,
  update_customer_success_progress: HeartPulse,
  record_activity: Activity,
};

function mapApiStatus(flow: AutomationFlowSummary): AutomationStatus {
  if (flow.enabled && flow.last_execution_status === "failed") return "failed";
  if (flow.status === "enabled") return "active";
  if (flow.status === "paused") return "paused";
  return "draft";
}

function relatedModulesFor(flow: AutomationFlowSummary): RelatedModule[] {
  const modules: RelatedModule[] = [{ label: "Automation", href: "/automation" }];
  if (flow.category === "publishing") modules.push({ label: "Publishing", href: "/publishing" });
  if (flow.category === "integrations") modules.push({ label: "Integrations", href: "/integrations" });
  if (flow.category === "crm") modules.push({ label: "CRM", href: "/crm" });
  if (flow.action_type === "create_notification") {
    modules.push({ label: "Notifications", href: "/notifications" });
  }
  if (flow.category === "customer_success") {
    modules.push({ label: "Customer Success", href: "/customer-success" });
  }
  return modules;
}

function buildSteps(flow: Pick<AutomationFlowSummary, "trigger_event" | "action_type">): AutomationStep[] {
  const triggerLabel = TRIGGER_LABELS[flow.trigger_event] ?? flow.trigger_event;
  const actionLabel = ACTION_LABELS[flow.action_type] ?? flow.action_type;
  return [
    { id: "trigger", label: triggerLabel },
    { id: "action", label: actionLabel },
  ];
}

function iconFor(flow: AutomationFlowSummary): { icon: LucideIcon; iconClassName: string } {
  const byCategory = CATEGORY_ICONS[flow.category];
  if (byCategory) return byCategory;
  return CATEGORY_ICONS.automation;
}

export function mapApiExecutionToApp(
  row: ApiExecution,
  automationName?: string,
): AutomationExecution {
  const result: ExecutionResult =
    row.status === "success" ? "success" : row.status === "skipped" ? "skipped" : "failed";
  const kindLabel =
    row.execution_kind === "retry"
      ? `Retry #${row.retry_number ?? 1}`
      : row.execution_kind === "manual" || row.is_manual_test
        ? "Manual test run"
        : undefined;
  const categoryLabel = row.error_category
    ? `Error: ${row.error_category}`
    : undefined;
  const detailParts = [row.error_message, kindLabel, categoryLabel].filter(Boolean);
  return {
    id: row.id,
    automationId: row.automation_flow_id,
    automationName: row.automation_name ?? automationName ?? "Automation",
    timestamp: row.finished_at ?? row.started_at,
    result,
    detail: detailParts.length > 0 ? detailParts.join(" · ") : undefined,
    durationMs: row.duration_ms ?? undefined,
    executionKind: row.execution_kind ?? (row.is_manual_test ? "manual" : "event"),
    retryNumber: row.retry_number ?? 0,
    retryEligible: Boolean(row.retry_eligible),
    retryBlockedReason: row.retry_blocked_reason ?? undefined,
    isRetryable: row.is_retryable,
    errorCategory: row.error_category ?? null,
    rootExecutionId: row.root_execution_id ?? null,
    retryOfExecutionId: row.retry_of_execution_id ?? null,
    triggerEvent: row.trigger_event,
  };
}

export function mapApiFlowToApp(
  flow: AutomationFlowSummary,
  executions: AutomationExecution[] = [],
  nextScheduled: string | null = null,
): Automation {
  const visual = iconFor(flow);
  return {
    id: flow.id,
    name: flow.name,
    description: flow.description ?? "",
    status: mapApiStatus(flow),
    enabled: flow.enabled,
    steps: buildSteps(flow),
    conditions: [TRIGGER_LABELS[flow.trigger_event] ?? flow.trigger_event],
    relatedModules: relatedModulesFor(flow),
    lastExecution: flow.last_executed_at ?? null,
    successRate: flow.success_rate,
    executionHistory: executions,
    nextScheduled,
    icon: visual.icon,
    iconClassName: visual.iconClassName,
    createdAt: flow.created_at,
    updatedAt: flow.updated_at,
  };
}

export function mapApiJobToApp(row: ApiJob): AutomationJobRow {
  return {
    id: row.id,
    flowId: row.automation_flow_id,
    flowName: row.automation_name ?? "Automation",
    executionId: row.execution_id,
    rootExecutionId: row.root_execution_id,
    status: row.status,
    scheduledFor: row.scheduled_for,
    availableAt: row.available_at,
    attemptNumber: row.attempt_number,
    maxAttempts: row.max_attempts,
    errorMessage: row.error_message,
    canCancel: row.can_cancel,
    canRequeue: row.can_requeue,
    createdAt: row.created_at,
  };
}

export function mapKpisToSummary(kpis: AutomationKpiResponse): AutomationSummary {
  return {
    healthScore: kpis.health_score,
    activeCount: kpis.active_count,
    pausedCount: kpis.paused_count,
    failedCount: kpis.failed_flow_count,
    draftCount: kpis.disabled_count,
    disabledCount: kpis.disabled_count,
    totalExecutions24h: kpis.total_executions_24h,
    successRateOverall: kpis.success_rate_overall,
    retryCountToday: kpis.retry_count_today ?? 0,
    retrySuccessCountToday: kpis.retry_success_count_today ?? 0,
    partialPublishFailuresToday: kpis.partial_publish_failures_today ?? 0,
    averageDurationMs: kpis.average_duration_ms ?? null,
    executionsToday: kpis.executions_today ?? 0,
    successRateToday: kpis.success_rate ?? kpis.success_rate_overall,
    scheduledJobs: kpis.scheduled_jobs ?? 0,
    dueJobs: kpis.due_jobs ?? 0,
    runningJobs: kpis.running_jobs ?? 0,
    failedJobs: kpis.failed_jobs ?? 0,
    deadLetterJobs: kpis.dead_letter_jobs ?? 0,
    recoveredLeasesToday: kpis.recovered_leases_today ?? 0,
    automaticRetriesToday: kpis.automatic_retries_today ?? 0,
    automaticRetrySuccessToday: kpis.automatic_retry_success_today ?? 0,
    averageScheduleDelayMs: kpis.average_schedule_delay_ms ?? null,
  };
}

export function mapApiFlowDetailToApp(detail: AutomationFlowDetail): Automation {
  const executions = detail.recent_executions.map((e) => mapApiExecutionToApp(e, detail.name));
  return mapApiFlowToApp(detail, executions);
}
