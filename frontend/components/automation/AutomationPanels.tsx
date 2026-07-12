"use client";

import { CalendarClock, FilterX, History, PauseCircle, Zap } from "lucide-react";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import {
  EXECUTION_RESULT_DOT,
  EXECUTION_RESULT_STYLES,
  formatDuration,
  formatRelativeTime,
  type Automation,
  type AutomationExecution,
} from "@/lib/automation-center-ui";
import { AutomationCard } from "./AutomationCard";

export function AutomationEmptyState({
  hasFilters,
  onResetFilters,
}: {
  hasFilters: boolean;
  onResetFilters: () => void;
}) {
  const { t } = useTranslation();

  if (hasFilters) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center rounded-2xl border border-dashed py-16 px-6 text-center",
          "border-gray-200 bg-gray-50/50 dark-tenant:border-white/[0.08] dark-tenant:bg-white/[0.02]",
        )}
      >
        <div className="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mb-4 dark-tenant:bg-white/[0.06]">
          <FilterX size={28} className="text-slate-400 dark-tenant:text-slate-500" aria-hidden />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 dark-tenant:text-slate-100">
          {t("automationCenter.empty.filtered")}
        </h3>
        <p className="text-sm text-gray-500 mt-2 max-w-md dark-tenant:text-slate-500">
          {t("automationCenter.empty.filteredHint")}
        </p>
        <button
          type="button"
          onClick={onResetFilters}
          className={cn(
            "mt-6 inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold",
            "bg-brand-600 text-white hover:bg-brand-700 dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500",
          )}
        >
          {t("automationCenter.empty.clearFilters")}
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-2xl border border-dashed py-16 px-6 text-center",
        "border-violet-200/60 bg-violet-50/30 dark-tenant:border-violet-500/20 dark-tenant:bg-violet-500/5",
      )}
    >
      <div className="relative mb-6">
        <div className="w-24 h-24 rounded-3xl bg-gradient-to-br from-violet-100 to-indigo-100 flex items-center justify-center dark-tenant:from-violet-500/20 dark-tenant:to-indigo-600/10">
          <Zap size={40} className="text-violet-600 dark-tenant:text-violet-400" aria-hidden />
        </div>
        <div className="absolute -top-2 -right-2 w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center ring-4 ring-white dark-tenant:bg-emerald-500/20 dark-tenant:ring-surface-dark-page">
          <svg viewBox="0 0 24 24" className="w-5 h-5 text-emerald-600 dark-tenant:text-emerald-400" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div className="absolute -bottom-1 -left-3 w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center ring-4 ring-white dark-tenant:bg-amber-500/20 dark-tenant:ring-surface-dark-page">
          <CalendarClock size={14} className="text-amber-600 dark-tenant:text-amber-400" aria-hidden />
        </div>
      </div>
      <h3 className="text-lg font-semibold text-gray-900 dark-tenant:text-slate-100">
        {t("automationCenter.empty.title")}
      </h3>
      <p className="text-sm text-gray-500 mt-2 max-w-md leading-relaxed dark-tenant:text-slate-500">
        {t("automationCenter.empty.hint")}
      </p>
    </div>
  );
}

export function AutomationExecutionHistoryPanel({
  executions,
  onSelectAutomation,
  automations,
}: {
  executions: AutomationExecution[];
  onSelectAutomation: (automation: Automation) => void;
  automations: Automation[];
}) {
  const { t } = useTranslation();

  if (executions.length === 0) return null;

  const findAutomation = (id: string) => automations.find((a) => a.id === id);

  return (
    <section aria-label={t("automationCenter.sections.executionHistory")} className="space-y-4">
      <div className="flex items-center gap-2">
        <History size={18} className="text-gray-400 dark-tenant:text-slate-500" aria-hidden />
        <h2 className="section-title">{t("automationCenter.sections.executionHistory")}</h2>
      </div>

      <div
        className={cn(
          "rounded-2xl border border-gray-200 bg-white p-4 shadow-card",
          "dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card",
        )}
      >
        <ol className="relative border-l border-gray-200 ml-3 space-y-5 dark-tenant:border-white/10">
          {executions.map((event) => {
            const automation = findAutomation(event.automationId);
            return (
              <li key={event.id} className="ml-5 relative">
                <span
                  className={cn(
                    "absolute -left-[1.45rem] top-1.5 w-2.5 h-2.5 rounded-full ring-2 ring-white dark-tenant:ring-surface-dark-card",
                    EXECUTION_RESULT_DOT[event.result],
                  )}
                  aria-hidden
                />
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
                  <div className="min-w-0">
                    <button
                      type="button"
                      onClick={() => automation && onSelectAutomation(automation)}
                      className="text-sm font-semibold text-gray-900 hover:text-brand-700 text-left dark-tenant:text-slate-200 dark-tenant:hover:text-violet-300"
                    >
                      {event.automationName}
                    </button>
                    {event.detail ? (
                      <p className="text-xs text-gray-500 mt-0.5 dark-tenant:text-slate-500">
                        {event.detail}
                      </p>
                    ) : null}
                    <div className="flex flex-wrap items-center gap-2 mt-1.5">
                      <span
                        className={cn(
                          "text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full",
                          EXECUTION_RESULT_STYLES[event.result],
                        )}
                      >
                        {t(`automationCenter.execution.${event.result}`)}
                      </span>
                      {event.durationMs ? (
                        <span className="text-[10px] text-gray-400 dark-tenant:text-slate-600">
                          {formatDuration(event.durationMs)}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <time
                    dateTime={event.timestamp}
                    className="text-[11px] text-gray-400 whitespace-nowrap shrink-0 dark-tenant:text-slate-500"
                  >
                    {formatRelativeTime(event.timestamp)}
                  </time>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

export function AutomationUpcomingPanel({
  automations,
  onSelect,
}: {
  automations: Automation[];
  onSelect: (automation: Automation) => void;
}) {
  const { t } = useTranslation();

  if (automations.length === 0) return null;

  return (
    <section aria-label={t("automationCenter.sections.upcoming")} className="space-y-4">
      <div className="flex items-center gap-2">
        <CalendarClock size={18} className="text-gray-400 dark-tenant:text-slate-500" aria-hidden />
        <h2 className="section-title">{t("automationCenter.sections.upcoming")}</h2>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {automations.map((automation, index) => (
          <button
            key={automation.id}
            type="button"
            onClick={() => onSelect(automation)}
            className={cn(
              "flex items-center gap-3 rounded-xl border p-4 text-left transition-colors",
              "border-gray-200 bg-white hover:border-brand-200 hover:shadow-card",
              "dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-elevated dark-tenant:hover:border-violet-500/30",
            )}
          >
            <div className="w-10 h-10 rounded-xl bg-violet-50 flex items-center justify-center shrink-0 dark-tenant:bg-violet-500/15">
              <CalendarClock size={18} className="text-violet-600 dark-tenant:text-violet-400" aria-hidden />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-gray-900 truncate dark-tenant:text-slate-100">
                {automation.name}
              </p>
              {automation.nextScheduled ? (
                <p className="text-xs text-gray-500 mt-0.5 dark-tenant:text-slate-500">
                  {t("automationCenter.scheduledFor")}{" "}
                  <time dateTime={automation.nextScheduled}>
                    {formatRelativeTime(automation.nextScheduled)}
                  </time>
                </p>
              ) : null}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

export function AutomationDisabledPanel({
  automations,
  onSelect,
  onToggle,
}: {
  automations: Automation[];
  onSelect: (automation: Automation) => void;
  onToggle: (id: string) => void;
}) {
  const { t } = useTranslation();

  if (automations.length === 0) return null;

  return (
    <section aria-label={t("automationCenter.sections.disabled")} className="space-y-4">
      <div className="flex items-center gap-2">
        <PauseCircle size={18} className="text-gray-400 dark-tenant:text-slate-500" aria-hidden />
        <h2 className="section-title">{t("automationCenter.sections.disabled")}</h2>
        <span className="text-xs text-gray-500 dark-tenant:text-slate-500">
          {automations.length}
        </span>
      </div>

      <div className="space-y-3">
        {automations.map((automation, index) => (
          <AutomationCard
            key={automation.id}
            automation={automation}
            onSelect={onSelect}
            onToggle={onToggle}
            index={index}
            compact
          />
        ))}
      </div>
    </section>
  );
}

export function AutomationOverviewStrip({
  successRate,
  executions24h,
}: {
  successRate: number;
  executions24h: number;
}) {
  const { t } = useTranslation();

  return (
    <section
      aria-label={t("automationCenter.sections.overview")}
      className={cn(
        "rounded-2xl border p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4",
        "border-gray-200 bg-gradient-to-r from-white to-violet-50/30",
        "dark-tenant:border-white/[0.08] dark-tenant:from-surface-dark-card dark-tenant:to-violet-500/5",
      )}
    >
      <div>
        <h2 className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100">
          {t("automationCenter.sections.overview")}
        </h2>
        <p className="text-xs text-gray-500 mt-0.5 dark-tenant:text-slate-500">
          {t("automationCenter.overview.subtitle")}
        </p>
      </div>
      <div className="flex flex-wrap gap-6">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark-tenant:text-slate-500">
            {t("automationCenter.overview.executions24h")}
          </p>
          <p className="text-lg font-bold text-gray-900 dark-tenant:text-slate-100">
            {executions24h}
          </p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark-tenant:text-slate-500">
            {t("automationCenter.overview.successRate")}
          </p>
          <p className="text-lg font-bold text-emerald-600 dark-tenant:text-emerald-400">
            {successRate}%
          </p>
        </div>
      </div>
    </section>
  );
}
