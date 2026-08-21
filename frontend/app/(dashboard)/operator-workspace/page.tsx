"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, Loader2, RefreshCw } from "lucide-react";
import toast from "react-hot-toast";
import { PageHeader, PageShell } from "@/components/ui/design-system";
import { ErrorState } from "@/components/ui/PageStates";
import {
  getApiErrorMessage,
  type OperatorAttentionItem,
  type OperatorWorkspaceAction,
  type OperatorWorkspaceMetricsResponse,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { useOperatorWorkspace } from "@/lib/operator-workspace-hooks";
import {
  PRIORITY_BADGE,
  RESPONSIBLE_BADGE,
  SUMMARY_CARDS,
  actionConfirmKey,
  actionLabelKey,
  categoryLabelKey,
  formatRelativeTime,
  priorityLabelKey,
  reasonLabelKey,
  responsibleLabelKey,
  suggestedActionLabelKey,
} from "@/lib/operator-workspace-ui";
import { cn } from "@/lib/utils";

function formatDuration(seconds: number | null | undefined, t: (k: string, p?: Record<string, string | number>) => string): string {
  if (seconds == null || Number.isNaN(seconds)) return t("operatorWorkspace.metrics.unavailable");
  if (seconds < 60) return t("operatorWorkspace.metrics.durationSeconds", { count: Math.round(seconds) });
  if (seconds < 3600) return t("operatorWorkspace.metrics.durationMinutes", { count: Math.round(seconds / 60) });
  if (seconds < 86400) return t("operatorWorkspace.metrics.durationHours", { count: Math.round(seconds / 3600) });
  return t("operatorWorkspace.metrics.durationDays", { count: Math.round(seconds / 86400) });
}

function MetricsStrip({
  metrics,
  window,
  onWindowChange,
  loading,
}: {
  metrics: OperatorWorkspaceMetricsResponse | undefined;
  window: "24h" | "7d" | "30d";
  onWindowChange: (w: "24h" | "7d" | "30d") => void;
  loading: boolean;
}) {
  const { t } = useTranslation();
  if (!metrics && !loading) return null;

  const attentionTotal = metrics?.attention?.total ?? 0;
  const actionsTotal = metrics?.actions?.total ?? 0;
  const medianRes = metrics?.resolution?.median_resolution_seconds;
  const oldest = metrics?.oldest_unresolved_age_seconds;
  const topIssue = metrics?.top_recurring_issue;
  const topCandidate = (metrics?.automation_candidates ?? []).find(
    (c) => c.available && !c.never_auto && c.level && c.level !== "D",
  );

  const categoryEntries = Object.entries(metrics?.attention?.by_category ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  return (
    <div className="mb-6 rounded-lg border border-gray-200 bg-gray-50/70 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h2 className="text-sm font-semibold text-gray-900">
          {t("operatorWorkspace.metrics.title")}
        </h2>
        <div className="inline-flex rounded-md border border-gray-200 bg-white p-0.5 text-xs">
          {(["24h", "7d", "30d"] as const).map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => onWindowChange(w)}
              className={cn(
                "px-2.5 py-1 rounded transition",
                window === w ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-100",
              )}
            >
              {t(`operatorWorkspace.metrics.windows.${w}`)}
            </button>
          ))}
        </div>
      </div>

      {loading && !metrics ? (
        <div className="text-sm text-gray-400">{t("common.loading")}</div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
          <div>
            <div className="text-xs text-gray-500">{t("operatorWorkspace.metrics.needsAttention")}</div>
            <div className="text-lg font-semibold tabular-nums text-gray-900">{attentionTotal}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500">{t("operatorWorkspace.metrics.oldest")}</div>
            <div className="text-lg font-semibold tabular-nums text-gray-900">
              {formatDuration(oldest, t)}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500">{t("operatorWorkspace.metrics.actionsInWindow")}</div>
            <div className="text-lg font-semibold tabular-nums text-gray-900">{actionsTotal}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500">{t("operatorWorkspace.metrics.medianResolution")}</div>
            <div className="text-lg font-semibold tabular-nums text-gray-900">
              {formatDuration(medianRes, t)}
            </div>
          </div>
        </div>
      )}

      {metrics && (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600">
          {topIssue && (
            <span>
              {t("operatorWorkspace.metrics.topIssue")}:{" "}
              <span className="font-medium text-gray-800">
                {t(`operatorWorkspace.categories.${topIssue}`)}
              </span>
            </span>
          )}
          {categoryEntries.length > 0 && (
            <span>
              {t("operatorWorkspace.metrics.byCategory")}:{" "}
              {categoryEntries.map(([cat, n], i) => (
                <span key={cat}>
                  {i > 0 ? " · " : ""}
                  {t(`operatorWorkspace.categories.${cat}`)} ({n})
                </span>
              ))}
            </span>
          )}
          {topCandidate && (
            <span>
              {t("operatorWorkspace.metrics.topCandidate")}:{" "}
              <span className="font-medium text-gray-800">
                {t(`operatorWorkspace.metrics.candidates.${topCandidate.action_key}`)}{" "}
                ({t(`operatorWorkspace.metrics.levels.${topCandidate.level}`)})
              </span>
            </span>
          )}
          <span className="text-gray-400">{t("operatorWorkspace.metrics.advisoryOnly")}</span>
        </div>
      )}
    </div>
  );
}

function SummaryCards({
  summary,
  onFilter,
}: {
  summary: NonNullable<ReturnType<typeof useOperatorWorkspace>["summary"]>;
  onFilter: ReturnType<typeof useOperatorWorkspace>["applySummaryFilter"];
}) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
      {SUMMARY_CARDS.map((card) => {
        const count = summary[card.key] ?? 0;
        return (
          <button
            key={card.key}
            type="button"
            onClick={() => onFilter(card.filterCategory, card.filterResponsible)}
            className={cn(
              "card p-3 text-left transition hover:ring-2 hover:ring-indigo-200",
              count > 0 && "border-indigo-100",
            )}
          >
            <div className="text-2xl font-semibold text-gray-900 tabular-nums">{count}</div>
            <div className="text-xs text-gray-500 mt-0.5">{t(card.labelKey)}</div>
          </button>
        );
      })}
    </div>
  );
}

function AttentionItemRow({
  item,
  onExecute,
  isPending,
}: {
  item: OperatorAttentionItem;
  onExecute: (item: OperatorAttentionItem, action: OperatorWorkspaceAction) => Promise<void>;
  isPending: (actionId: string) => boolean;
}) {
  const { t } = useTranslation();
  const reasonKey = reasonLabelKey(item);
  const reasonText = t(reasonKey);
  const displayReason = reasonText === reasonKey ? item.reason : reasonText;
  const actions = item.actions?.length
    ? item.actions
    : [
        {
          action_id: "open",
          label: "Open",
          action_type: "navigation" as const,
          enabled: true,
          requires_confirmation: false,
          confirmation_message: null,
          disabled_reason: null,
          destructive: false,
          external_side_effect: false,
          target_resource: null,
          href: item.action_path,
          primary: true,
        },
      ];

  const primary = actions.find((a) => a.primary) ?? actions[0];
  const secondary = actions.filter((a) => a !== primary);

  return (
    <div className="px-4 py-3 border-b border-gray-100 last:border-0 hover:bg-gray-50/60 transition">
      <div className="flex flex-wrap items-start gap-2 mb-1">
        <span
          className={cn(
            "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border",
            PRIORITY_BADGE[item.priority],
          )}
        >
          {t(priorityLabelKey(item.priority))}
        </span>
        <span
          className={cn(
            "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border",
            RESPONSIBLE_BADGE[item.responsible_party],
          )}
        >
          {t(responsibleLabelKey(item.responsible_party))}
        </span>
        {item.overdue && (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border bg-red-50 text-red-700 border-red-200">
            {t("operatorWorkspace.overdue")}
          </span>
        )}
      </div>
      <div className="font-medium text-gray-900 truncate">{item.company_name}</div>
      <div className="text-sm text-gray-700 mt-0.5">{item.title}</div>
      <div className="text-sm text-gray-500 mt-1">{displayReason}</div>
      <div className="flex flex-wrap items-center gap-3 mt-2 text-xs text-gray-400">
        <span>{t(categoryLabelKey(item.attention_type))}</span>
        {item.created_at && (
          <span>{formatRelativeTime(item.created_at, t)}</span>
        )}
        {item.due_at && (
          <span>
            {t("operatorWorkspace.due")}: {new Date(item.due_at).toLocaleString()}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 mt-3">
        {primary && (
          <ActionControl
            item={item}
            action={primary}
            variant="primary"
            onExecute={onExecute}
            pending={isPending(primary.action_id)}
            fallbackLabel={t(suggestedActionLabelKey(item))}
          />
        )}
        {secondary.map((action) => (
          <ActionControl
            key={action.action_id}
            item={item}
            action={action}
            variant="secondary"
            onExecute={onExecute}
            pending={isPending(action.action_id)}
          />
        ))}
      </div>
    </div>
  );
}

function ActionControl({
  item,
  action,
  variant,
  onExecute,
  pending,
  fallbackLabel,
}: {
  item: OperatorAttentionItem;
  action: OperatorWorkspaceAction;
  variant: "primary" | "secondary";
  onExecute: (item: OperatorAttentionItem, action: OperatorWorkspaceAction) => Promise<void>;
  pending: boolean;
  fallbackLabel?: string;
}) {
  const { t } = useTranslation();
  const labelKey = actionLabelKey(action.action_id);
  const translated = t(labelKey);
  const label =
    translated === labelKey
      ? action.label || fallbackLabel || action.action_id
      : translated;

  if (action.action_type === "navigation") {
    const href = action.href || item.action_path;
    return (
      <Link
        href={href}
        className={cn(
          "inline-flex items-center gap-1 text-sm font-medium",
          variant === "primary"
            ? "btn-primary px-3 py-1.5"
            : "text-indigo-600 hover:text-indigo-800",
        )}
      >
        {label}
        <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    );
  }

  const disabled = !action.enabled || pending;
  const title = !action.enabled && action.disabled_reason
    ? action.disabled_reason
    : undefined;

  return (
    <button
      type="button"
      disabled={disabled}
      title={title}
      onClick={() => void onExecute(item, action)}
      className={cn(
        "inline-flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded transition",
        variant === "primary"
          ? "btn-primary disabled:opacity-50"
          : "btn-secondary disabled:opacity-50",
      )}
    >
      {pending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {label}
    </button>
  );
}

export default function OperatorWorkspacePage() {
  const { t } = useTranslation();
  const {
    filters,
    updateFilters,
    resetFilters,
    applySummaryFilter,
    clients,
    items,
    total,
    summary,
    isLoading,
    isError,
    error,
    retry,
    executeAction,
    isActionPending,
    hasActiveFilters,
    metrics,
    metricsWindow,
    setMetricsWindow,
    metricsLoading,
  } = useOperatorWorkspace();
  const [busyItemId, setBusyItemId] = useState<string | null>(null);

  const handleExecute = async (
    item: OperatorAttentionItem,
    action: OperatorWorkspaceAction,
  ) => {
    if (action.action_type !== "mutation" || !action.enabled) return;
    if (busyItemId === item.id) return;

    if (action.requires_confirmation) {
      const confirmKey = actionConfirmKey(action.action_id);
      const message = confirmKey
        ? t(confirmKey)
        : action.confirmation_message || t("operatorWorkspace.confirm.generic");
      if (!window.confirm(message)) return;
    }

    setBusyItemId(item.id);
    try {
      const result = await executeAction({
        attentionId: item.id,
        actionId: action.action_id,
      });
      toast.success(result.message || t("operatorWorkspace.feedback.success"));
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 409) {
        toast.error(t("operatorWorkspace.feedback.stale"));
        retry();
      } else {
        toast.error(getApiErrorMessage(err) || t("operatorWorkspace.feedback.failed"));
      }
    } finally {
      setBusyItemId(null);
    }
  };

  return (
    <PageShell>
      <PageHeader
        title={t("operatorWorkspace.title")}
        subtitle={t("operatorWorkspace.subtitle")}
        actions={
          <button
            type="button"
            onClick={() => retry()}
            className="btn-secondary inline-flex items-center gap-2 text-sm"
          >
            <RefreshCw className="h-4 w-4" />
            {t("common.refresh")}
          </button>
        }
      />

      {isError && (
        <ErrorState
          message={getApiErrorMessage(error)}
          onRetry={() => retry()}
        />
      )}

      {!isError && summary && (
        <SummaryCards summary={summary} onFilter={applySummaryFilter} />
      )}

      {!isError && (
        <MetricsStrip
          metrics={metrics}
          window={metricsWindow}
          onWindowChange={setMetricsWindow}
          loading={metricsLoading}
        />
      )}

      <div className="card mb-4 p-4">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              {t("operatorWorkspace.filters.client")}
            </label>
            <select
              value={filters.clientId ?? ""}
              onChange={(e) =>
                updateFilters({ clientId: e.target.value || null })
              }
              className="input text-sm min-w-[12rem]"
            >
              <option value="">{t("operatorWorkspace.filters.allClients")}</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.company_name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              {t("operatorWorkspace.filters.category")}
            </label>
            <select
              value={filters.category}
              onChange={(e) => updateFilters({ category: e.target.value as typeof filters.category })}
              className="input text-sm"
            >
              <option value="all">{t("operatorWorkspace.filters.all")}</option>
              <option value="content_internal_review">{t("operatorWorkspace.categories.content_internal_review")}</option>
              <option value="waiting_for_client">{t("operatorWorkspace.categories.waiting_for_client")}</option>
              <option value="publishing_issue">{t("operatorWorkspace.categories.publishing_issue")}</option>
              <option value="scheduling_issue">{t("operatorWorkspace.categories.scheduling_issue")}</option>
              <option value="integration_issue">{t("operatorWorkspace.categories.integration_issue")}</option>
              <option value="telegram_ingestion_issue">{t("operatorWorkspace.categories.telegram_ingestion_issue")}</option>
              <option value="automation_failure">{t("operatorWorkspace.categories.automation_failure")}</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              {t("operatorWorkspace.filters.priority")}
            </label>
            <select
              value={filters.priority}
              onChange={(e) => updateFilters({ priority: e.target.value as typeof filters.priority })}
              className="input text-sm"
            >
              <option value="all">{t("operatorWorkspace.filters.all")}</option>
              <option value="critical">{t("operatorWorkspace.priority.critical")}</option>
              <option value="high">{t("operatorWorkspace.priority.high")}</option>
              <option value="medium">{t("operatorWorkspace.priority.medium")}</option>
              <option value="low">{t("operatorWorkspace.priority.low")}</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              {t("operatorWorkspace.filters.responsible")}
            </label>
            <select
              value={filters.responsible}
              onChange={(e) => updateFilters({ responsible: e.target.value as typeof filters.responsible })}
              className="input text-sm"
            >
              <option value="all">{t("operatorWorkspace.filters.all")}</option>
              <option value="operator">{t("operatorWorkspace.responsible.operator")}</option>
              <option value="client">{t("operatorWorkspace.responsible.client")}</option>
              <option value="system">{t("operatorWorkspace.responsible.system")}</option>
              <option value="provider">{t("operatorWorkspace.responsible.provider")}</option>
            </select>
          </div>
          {hasActiveFilters && (
            <button type="button" onClick={resetFilters} className="btn-ghost text-sm">
              {t("operatorWorkspace.filters.clear")}
            </button>
          )}
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">
            {t("operatorWorkspace.queueTitle")}{" "}
            <span className="text-gray-400 font-normal">({total})</span>
          </h2>
        </div>

        {isLoading && (
          <div className="p-8 text-center text-gray-400 text-sm">{t("common.loading")}</div>
        )}

        {!isLoading && items.length === 0 && (
          <div className="p-10 text-center">
            <AlertTriangle className="h-8 w-8 text-emerald-400 mx-auto mb-3" />
            <p className="text-gray-600 font-medium">{t("operatorWorkspace.empty.title")}</p>
            <p className="text-sm text-gray-400 mt-1">{t("operatorWorkspace.empty.subtitle")}</p>
          </div>
        )}

        {!isLoading && items.map((item) => (
          <AttentionItemRow
            key={item.id}
            item={item}
            onExecute={handleExecute}
            isPending={(actionId) =>
              busyItemId === item.id || isActionPending(item.id, actionId)
            }
          />
        ))}
      </div>
    </PageShell>
  );
}
