"use client";

import type { AttentionCategory, AttentionPriority, OperatorAttentionItem, OperatorWorkspaceSummary, ResponsibleParty } from "@/lib/api";

export type { AttentionCategory, AttentionPriority, OperatorAttentionItem, OperatorWorkspaceSummary, ResponsibleParty };

export type WorkspaceFilterCategory = AttentionCategory | "all";
export type WorkspaceFilterPriority = AttentionPriority | "all";
export type WorkspaceFilterResponsible = ResponsibleParty | "all";

export interface WorkspaceFilters {
  clientId: string | null;
  category: WorkspaceFilterCategory;
  priority: WorkspaceFilterPriority;
  responsible: WorkspaceFilterResponsible;
}

export const DEFAULT_WORKSPACE_FILTERS: WorkspaceFilters = {
  clientId: null,
  category: "all",
  priority: "all",
  responsible: "all",
};

export const PRIORITY_BADGE: Record<AttentionPriority, string> = {
  critical: "bg-red-100 text-red-800 border-red-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-sky-100 text-sky-800 border-sky-200",
};

export const RESPONSIBLE_BADGE: Record<ResponsibleParty, string> = {
  operator: "bg-violet-100 text-violet-800 border-violet-200",
  client: "bg-blue-100 text-blue-800 border-blue-200",
  system: "bg-gray-100 text-gray-700 border-gray-200",
  provider: "bg-rose-100 text-rose-800 border-rose-200",
};

export function categoryLabelKey(category: AttentionCategory): string {
  return `operatorWorkspace.categories.${category}`;
}

export function priorityLabelKey(priority: AttentionPriority): string {
  return `operatorWorkspace.priority.${priority}`;
}

export function responsibleLabelKey(party: ResponsibleParty): string {
  return `operatorWorkspace.responsible.${party}`;
}

export function suggestedActionLabelKey(item: OperatorAttentionItem): string {
  const code = item.metadata?.reason_code as string | undefined;
  if (code?.startsWith("publish")) return "operatorWorkspace.actions.reviewPublish";
  if (code === "internal_review") return "operatorWorkspace.actions.reviewContent";
  if (code?.startsWith("client")) return "operatorWorkspace.actions.openClientReview";
  if (code === "schedule_overdue") return "operatorWorkspace.actions.reviewQueue";
  if (code === "integration_attention") return "operatorWorkspace.actions.openIntegrations";
  if (code === "telegram_failed") return "operatorWorkspace.actions.reviewTelegram";
  if (code?.startsWith("automation")) return "operatorWorkspace.actions.openAutomation";
  if (code === "publish_alert") return "operatorWorkspace.actions.reviewAlert";
  return "operatorWorkspace.actions.review";
}

export function actionLabelKey(actionId: string): string {
  const map: Record<string, string> = {
    open: "operatorWorkspace.actionButtons.open",
    acknowledge_alert: "operatorWorkspace.actionButtons.acknowledge",
    resolve_alert: "operatorWorkspace.actionButtons.resolve",
    retry_publish: "operatorWorkspace.actionButtons.retryPublish",
    approve_content: "operatorWorkspace.actionButtons.approve",
  };
  return map[actionId] ?? "operatorWorkspace.actionButtons.open";
}

export function actionConfirmKey(actionId: string): string | null {
  const map: Record<string, string> = {
    resolve_alert: "operatorWorkspace.confirm.resolve",
    retry_publish: "operatorWorkspace.confirm.retryPublish",
    approve_content: "operatorWorkspace.confirm.approve",
  };
  return map[actionId] ?? null;
}

export function reasonLabelKey(item: OperatorAttentionItem): string {
  const code = item.metadata?.reason_code as string | undefined;
  if (code) return `operatorWorkspace.reasons.${code}`;
  return "operatorWorkspace.reasons.generic";
}

export function formatRelativeTime(iso: string | null | undefined, t: (k: string, p?: Record<string, string | number>) => string): string {
  if (!iso) return "";
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return t("operatorWorkspace.time.today");
  if (diffDays === 1) return t("operatorWorkspace.time.yesterday");
  return t("operatorWorkspace.time.daysAgo", { count: diffDays });
}

export interface SummaryCardDef {
  key: keyof OperatorWorkspaceSummary;
  labelKey: string;
  filterCategory?: AttentionCategory;
  filterResponsible?: ResponsibleParty;
}

export const SUMMARY_CARDS: SummaryCardDef[] = [
  { key: "needs_action_now", labelKey: "operatorWorkspace.summary.needsAction", filterResponsible: "operator" },
  { key: "waiting_for_client", labelKey: "operatorWorkspace.summary.waitingClient", filterCategory: "waiting_for_client" },
  { key: "publishing_issues", labelKey: "operatorWorkspace.summary.publishing", filterCategory: "publishing_issue" },
  { key: "due_today", labelKey: "operatorWorkspace.summary.dueToday", filterCategory: "scheduling_issue" },
  { key: "integration_issues", labelKey: "operatorWorkspace.summary.integrations", filterCategory: "integration_issue" },
  { key: "automation_failures", labelKey: "operatorWorkspace.summary.automation", filterCategory: "automation_failure" },
];
