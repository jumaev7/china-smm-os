"use client";

import Link from "next/link";
import {
  ArrowRight,
  ChevronDown,
  Clock,
  ExternalLink,
  GitBranch,
  History,
  ListChecks,
  Play,
  Target,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import {
  EXECUTION_RESULT_DOT,
  EXECUTION_RESULT_LABELS,
  EXECUTION_RESULT_STYLES,
  formatDuration,
  formatRelativeTime,
  formatSuccessRate,
  STATUS_STYLES,
  type Automation,
} from "@/lib/automation-center-ui";

function DrawerSection({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: LucideIcon;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark-tenant:text-slate-500 flex items-center gap-1.5">
        <Icon size={13} />
        {title}
      </h3>
      {children}
    </section>
  );
}

export function AutomationDetailDrawer({
  automation,
  onClose,
  onToggle,
  onRunTest,
  onRetryExecution,
  isToggling = false,
  runState,
  retryState,
}: {
  automation: Automation | null;
  onClose: () => void;
  onToggle: (id: string) => void;
  onRunTest?: (id: string) => void;
  onRetryExecution?: (executionId: string) => void;
  isToggling?: boolean;
  runState?: { flowId: string; status: "pending" | "success" | "failed"; message?: string } | null;
  retryState?: {
    executionId: string;
    status: "pending" | "success" | "failed";
    message?: string;
  } | null;
}) {
  const { t } = useTranslation();

  if (!automation) return null;

  const Icon = automation.icon;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-30 backdrop-blur-[1px]"
        onClick={onClose}
        data-app-modal
        aria-hidden
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="automation-drawer-title"
        className={cn(
          "fixed inset-y-0 right-0 w-full max-w-lg z-40 flex flex-col",
          "bg-white border-l border-gray-200 shadow-2xl",
          "dark-tenant:bg-surface-dark-page dark-tenant:border-white/[0.08]",
        )}
      >
        <header className="shrink-0 p-4 border-b border-gray-100 dark-tenant:border-white/[0.06]">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3 min-w-0">
              <div
                className={cn(
                  "shrink-0 flex items-center justify-center w-12 h-12 rounded-xl ring-1",
                  automation.iconClassName,
                  "ring-black/5 dark-tenant:ring-white/10",
                )}
              >
                <Icon size={22} aria-hidden />
              </div>
              <div className="min-w-0">
                <h2
                  id="automation-drawer-title"
                  className="text-lg font-semibold text-gray-900 dark-tenant:text-slate-100"
                >
                  {automation.name}
                </h2>
                <div className="flex flex-wrap items-center gap-2 mt-1.5">
                  <span
                    className={cn(
                      "text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full",
                      STATUS_STYLES[automation.status],
                    )}
                  >
                    {t(`automationCenter.status.${automation.status}`)}
                  </span>
                  {automation.lastExecution ? (
                    <time
                      dateTime={automation.lastExecution}
                      className="text-xs text-gray-500 flex items-center gap-1 dark-tenant:text-slate-500"
                    >
                      <Clock size={11} aria-hidden />
                      {t("automationCenter.lastExecution")}: {formatRelativeTime(automation.lastExecution)}
                    </time>
                  ) : null}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark-tenant:hover:bg-white/[0.06] dark-tenant:hover:text-slate-200"
              aria-label={t("automationCenter.close")}
            >
              <X size={18} />
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          <p className="text-sm text-gray-600 dark-tenant:text-slate-400 leading-relaxed">
            {automation.description}
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl border border-gray-100 p-3 dark-tenant:border-white/[0.06] dark-tenant:bg-white/[0.02]">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark-tenant:text-slate-500">
                {t("automationCenter.successRate")}
              </p>
              <p className="text-xl font-bold text-gray-900 mt-1 dark-tenant:text-slate-100">
                {automation.successRate > 0 ? formatSuccessRate(automation.successRate) : "—"}
              </p>
            </div>
            <div className="rounded-xl border border-gray-100 p-3 dark-tenant:border-white/[0.06] dark-tenant:bg-white/[0.02]">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark-tenant:text-slate-500">
                {t("automationCenter.executions")}
              </p>
              <p className="text-xl font-bold text-gray-900 mt-1 dark-tenant:text-slate-100">
                {automation.executionHistory.length}
              </p>
            </div>
          </div>

          <DrawerSection title={t("automationCenter.drawer.trigger")} icon={Target}>
            <div className="rounded-xl border border-violet-200/60 bg-violet-50/40 p-3 dark-tenant:border-violet-500/20 dark-tenant:bg-violet-500/5">
              <p className="text-sm font-medium text-violet-900 dark-tenant:text-violet-200">
                {automation.steps[0]?.label}
              </p>
            </div>
          </DrawerSection>

          {automation.conditions.length > 0 ? (
            <DrawerSection title={t("automationCenter.drawer.conditions")} icon={ListChecks}>
              <ul className="space-y-2">
                {automation.conditions.map((condition) => (
                  <li
                    key={condition}
                    className="flex items-start gap-2 text-sm text-gray-700 dark-tenant:text-slate-300"
                  >
                    <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-violet-500 shrink-0" aria-hidden />
                    {condition}
                  </li>
                ))}
              </ul>
            </DrawerSection>
          ) : null}

          <DrawerSection title={t("automationCenter.drawer.actions")} icon={GitBranch}>
            <div className="space-y-2">
              {automation.steps.slice(1).map((step, idx) => (
                <div key={step.id} className="flex items-center gap-2">
                  {idx > 0 ? (
                    <ChevronDown
                      size={14}
                      className="text-gray-300 -rotate-90 dark-tenant:text-slate-600"
                      aria-hidden
                    />
                  ) : null}
                  <span className="inline-flex items-center rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 text-sm font-medium text-gray-800 flex-1 dark-tenant:border-white/[0.06] dark-tenant:bg-white/[0.04] dark-tenant:text-slate-200">
                    {step.label}
                  </span>
                </div>
              ))}
            </div>
          </DrawerSection>

          {automation.executionHistory.length > 0 ? (
            <DrawerSection title={t("automationCenter.drawer.executionHistory")} icon={History}>
              <ol className="relative border-l border-gray-200 ml-2 space-y-4 dark-tenant:border-white/10">
                {automation.executionHistory.map((event) => {
                  const isRetrying =
                    retryState?.executionId === event.id && retryState.status === "pending";
                  return (
                  <li key={event.id} className="ml-4 relative">
                    <span
                      className={cn(
                        "absolute -left-[1.3rem] top-1 w-2.5 h-2.5 rounded-full ring-2 ring-white dark-tenant:ring-surface-dark-page",
                        EXECUTION_RESULT_DOT[event.result],
                      )}
                      aria-hidden
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-200">
                        {event.detail ?? EXECUTION_RESULT_LABELS[event.result]}
                      </p>
                      <span
                        className={cn(
                          "text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full",
                          EXECUTION_RESULT_STYLES[event.result],
                        )}
                      >
                        {t(`automationCenter.execution.${event.result}`)}
                      </span>
                      {event.executionKind ? (
                        <span className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 dark-tenant:bg-white/10 dark-tenant:text-slate-400">
                          {t(`automationCenter.kind.${event.executionKind}`)}
                          {event.executionKind === "retry" && event.retryNumber
                            ? ` #${event.retryNumber}`
                            : ""}
                        </span>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-3 mt-0.5">
                      <time
                        dateTime={event.timestamp}
                        className="text-[11px] text-gray-400 dark-tenant:text-slate-600"
                      >
                        {formatRelativeTime(event.timestamp)}
                      </time>
                      {event.durationMs ? (
                        <span className="text-[11px] text-gray-400 dark-tenant:text-slate-600">
                          {formatDuration(event.durationMs)}
                        </span>
                      ) : null}
                    </div>
                    {event.result === "failed" && onRetryExecution ? (
                      event.retryEligible ? (
                        <button
                          type="button"
                          onClick={() => onRetryExecution(event.id)}
                          disabled={isRetrying || retryState?.status === "pending"}
                          className="mt-1.5 text-xs font-semibold text-brand-700 hover:text-brand-800 disabled:opacity-60 dark-tenant:text-violet-300"
                        >
                          {isRetrying
                            ? t("automationCenter.retry.pending")
                            : t("automationCenter.retry.action")}
                        </button>
                      ) : event.retryBlockedReason ? (
                        <p className="mt-1.5 text-[11px] text-gray-400 dark-tenant:text-slate-500">
                          {t("automationCenter.retry.blocked")}: {event.retryBlockedReason}
                        </p>
                      ) : null
                    ) : null}
                  </li>
                  );
                })}
              </ol>
            </DrawerSection>
          ) : null}

          <DrawerSection title={t("automationCenter.drawer.relatedModules")} icon={ExternalLink}>
            <div className="flex flex-wrap gap-2">
              {automation.relatedModules.map((mod) => (
                <Link
                  key={`${mod.href}-${mod.label}`}
                  href={mod.href}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-50 dark-tenant:border-white/10 dark-tenant:text-violet-300 dark-tenant:hover:bg-violet-500/10"
                >
                  {mod.label}
                  <ArrowRight size={12} aria-hidden />
                </Link>
              ))}
            </div>
          </DrawerSection>
        </div>

        <footer className="shrink-0 p-4 border-t border-gray-100 dark-tenant:border-white/[0.06] flex flex-col gap-2">
          {runState && automation && runState.flowId === automation.id ? (
            <p
              className={cn(
                "text-xs rounded-lg px-3 py-2",
                runState.status === "pending" && "bg-slate-100 text-slate-600 dark-tenant:bg-white/5 dark-tenant:text-slate-400",
                runState.status === "success" && "bg-emerald-50 text-emerald-800 dark-tenant:bg-emerald-500/10 dark-tenant:text-emerald-300",
                runState.status === "failed" && "bg-red-50 text-red-800 dark-tenant:bg-red-500/10 dark-tenant:text-red-300",
              )}
              role="status"
            >
              {runState.status === "pending"
                ? t("automationCenter.runTest.pending")
                : runState.status === "success"
                  ? t("automationCenter.runTest.success")
                  : runState.message ?? t("automationCenter.runTest.failed")}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onToggle(automation.id)}
            disabled={isToggling}
            className={cn(
              "inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-semibold disabled:opacity-60",
              automation.enabled
                ? "border border-gray-200 text-gray-700 hover:bg-gray-50 dark-tenant:border-white/10 dark-tenant:text-slate-300 dark-tenant:hover:bg-white/[0.04]"
                : "bg-brand-600 text-white hover:bg-brand-700 dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500",
            )}
          >
            <Play size={14} aria-hidden />
            {automation.enabled
              ? t("automationCenter.actions.pause")
              : t("automationCenter.actions.enable")}
          </button>
          {onRunTest ? (
            <button
              type="button"
              onClick={() => onRunTest(automation.id)}
              disabled={runState?.status === "pending"}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-brand-200 px-4 py-2.5 text-sm font-semibold text-brand-700 hover:bg-brand-50 disabled:opacity-60 dark-tenant:border-violet-500/30 dark-tenant:text-violet-300 dark-tenant:hover:bg-violet-500/10"
            >
              <Play size={14} aria-hidden />
              {t("automationCenter.actions.runTest")}
            </button>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center justify-center rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark-tenant:border-white/10 dark-tenant:text-slate-300 dark-tenant:hover:bg-white/[0.04]"
          >
            {t("automationCenter.close")}
          </button>
          </div>
        </footer>
      </aside>
    </>
  );
}
