"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import {
  formatRelativeTime,
  formatSuccessRate,
  STATUS_DOT_STYLES,
  STATUS_STYLES,
  type Automation,
} from "@/lib/automation-center-ui";

function AutomationFlow({ steps }: { steps: Automation["steps"] }) {
  return (
    <div
      className="flex flex-wrap items-center gap-1.5 mt-3"
      aria-label="Automation flow"
    >
      {steps.map((step, idx) => (
        <div key={step.id} className="flex items-center gap-1.5">
          {idx > 0 ? (
            <ChevronDown
              size={14}
              className="text-gray-300 rotate-[-90deg] dark-tenant:text-slate-600 shrink-0"
              aria-hidden
            />
          ) : null}
          <span
            className={cn(
              "inline-flex items-center rounded-lg px-2.5 py-1 text-[11px] font-medium",
              idx === 0
                ? "bg-violet-100 text-violet-800 dark-tenant:bg-violet-500/15 dark-tenant:text-violet-300"
                : "bg-slate-100 text-slate-700 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-300",
            )}
          >
            {step.label}
          </span>
        </div>
      ))}
    </div>
  );
}

export function AutomationCard({
  automation,
  onSelect,
  onToggle,
  index = 0,
  compact = false,
}: {
  automation: Automation;
  onSelect: (automation: Automation) => void;
  onToggle?: (id: string) => void;
  index?: number;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const Icon = automation.icon;
  const isFailed = automation.status === "failed";
  const isPaused = automation.status === "paused" || !automation.enabled;

  return (
    <article
      className={cn(
        "group relative flex flex-col rounded-2xl border p-5 transition-all duration-300 animate-fade-in-up",
        "focus-within:ring-2 focus-within:ring-brand-500/40 focus-within:ring-offset-2 dark-tenant:focus-within:ring-violet-500/40",
        isFailed
          ? "border-red-200/80 bg-red-50/20 shadow-card dark-tenant:border-red-500/20 dark-tenant:bg-red-500/5"
          : isPaused
            ? "border-amber-200/60 bg-amber-50/15 shadow-card dark-tenant:border-amber-500/15 dark-tenant:bg-amber-500/5"
            : "border-slate-200 bg-white shadow-card hover:shadow-card-hover hover:border-brand-200 dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card dark-tenant:hover:border-violet-500/30",
        compact && "p-4",
      )}
      style={{ animationDelay: `${index * 35}ms` }}
    >
      {isFailed ? (
        <div className="absolute top-0 left-5 right-5 h-0.5 rounded-full bg-gradient-to-r from-red-400 to-red-600" />
      ) : automation.status === "active" && automation.enabled ? (
        <div className="absolute top-0 left-5 right-5 h-0.5 rounded-full bg-gradient-to-r from-emerald-400 to-violet-500 dark-tenant:from-emerald-500 dark-tenant:to-violet-600" />
      ) : null}

      <div className="flex items-start gap-4">
        <div
          className={cn(
            "shrink-0 flex items-center justify-center w-11 h-11 rounded-xl ring-1",
            automation.iconClassName,
            "ring-black/5 dark-tenant:ring-white/10",
          )}
        >
          <Icon size={20} aria-hidden />
        </div>

        <div className="flex-1 min-w-0">
          <button
            type="button"
            onClick={() => onSelect(automation)}
            className="text-left w-full"
            aria-label={automation.name}
          >
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-semibold text-[15px] text-navy-900 dark-tenant:text-slate-100">
                {automation.name}
              </h3>
              <span
                className={cn(
                  "text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full",
                  STATUS_STYLES[automation.status],
                )}
              >
                {t(`automationCenter.status.${automation.status}`)}
              </span>
            </div>
            {!compact ? (
              <p className="text-sm text-gray-600 mt-1 leading-relaxed line-clamp-2 dark-tenant:text-slate-400">
                {automation.description}
              </p>
            ) : null}
          </button>

          {!compact ? <AutomationFlow steps={automation.steps} /> : null}
        </div>

        <div className="shrink-0 flex flex-col items-end gap-1.5 text-right">
          {automation.lastExecution ? (
            <time
              dateTime={automation.lastExecution}
              className="text-[11px] text-gray-400 whitespace-nowrap dark-tenant:text-slate-500"
            >
              {formatRelativeTime(automation.lastExecution)}
            </time>
          ) : (
            <span className="text-[11px] text-gray-400 dark-tenant:text-slate-600">
              {t("automationCenter.neverRun")}
            </span>
          )}
          {automation.successRate > 0 ? (
            <span className="text-[11px] font-medium text-gray-500 dark-tenant:text-slate-500">
              {formatSuccessRate(automation.successRate)} {t("automationCenter.successRate")}
            </span>
          ) : null}
          <span className="flex items-center gap-1 text-[10px] text-gray-400 dark-tenant:text-slate-600">
            <span
              className={cn("w-1.5 h-1.5 rounded-full", STATUS_DOT_STYLES[automation.status])}
              aria-hidden
            />
            {t(`automationCenter.status.${automation.status}`)}
          </span>
        </div>
      </div>

      <div className="mt-4 pt-3 border-t border-slate-100 dark-tenant:border-white/[0.06] flex items-center justify-between gap-2">
        {onToggle ? (
          <button
            type="button"
            onClick={() => onToggle(automation.id)}
            aria-label={
              automation.enabled
                ? t("automationCenter.actions.pause")
                : t("automationCenter.actions.enable")
            }
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
              automation.enabled
                ? "bg-amber-100 text-amber-800 hover:bg-amber-200 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-300"
                : "bg-emerald-100 text-emerald-800 hover:bg-emerald-200 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-300",
            )}
          >
            {automation.enabled
              ? t("automationCenter.actions.pause")
              : t("automationCenter.actions.enable")}
          </button>
        ) : (
          <span />
        )}

        <button
          type="button"
          onClick={() => onSelect(automation)}
          className="inline-flex items-center gap-0.5 text-xs font-medium text-gray-400 hover:text-brand-700 dark-tenant:hover:text-violet-300 transition-colors"
        >
          {t("automationCenter.viewDetails")}
          <ChevronRight size={14} aria-hidden />
        </button>
      </div>
    </article>
  );
}
