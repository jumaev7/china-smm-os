"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { AutomationCard } from "@/components/automation/AutomationCard";
import { AutomationCenterHeader } from "@/components/automation/AutomationCenterHeader";
import { AutomationCenterSkeleton } from "@/components/automation/AutomationCenterSkeleton";
import { AutomationDetailDrawer } from "@/components/automation/AutomationDetailDrawer";
import {
  AutomationDisabledPanel,
  AutomationEmptyState,
  AutomationExecutionHistoryPanel,
  AutomationJobsPanel,
  AutomationOverviewStrip,
  AutomationUpcomingPanel,
} from "@/components/automation/AutomationPanels";
import { ErrorState } from "@/components/ui/PageStates";
import { PageShell } from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";
import { useAutomationCenter } from "@/lib/automation-center-hooks";
import type { Automation } from "@/lib/automation-center-ui";
import { cn } from "@/lib/utils";

export default function AutomationPage() {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<Automation | null>(null);

  const {
    filtered,
    activeAutomations,
    recentExecutions,
    upcomingAutomations,
    disabledAutomations,
    jobs,
    automations,
    filters,
    summary,
    isLoading,
    isError,
    hasActiveFilters,
    updateFilters,
    resetFilters,
    retry,
    toggleAutomation,
    runTest,
    retryExecution,
    cancelJob,
    requeueJob,
    mutatingId,
    jobMutatingId,
    runState,
    retryState,
    tenantId,
  } = useAutomationCenter();

  const handleSelect = (automation: Automation) => {
    setSelected(automation);
  };

  const handleToggle = (id: string) => {
    toggleAutomation(id);
  };

  useEffect(() => {
    setSelected(null);
  }, [tenantId, filters.section, filters.search]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
    };
    if (selected) {
      document.addEventListener("keydown", onKeyDown);
      return () => document.removeEventListener("keydown", onKeyDown);
    }
  }, [selected]);

  const showMainList = !hasActiveFilters || filters.section === "all" || filters.section === "active" || filters.section === "failed";

  return (
    <PageShell wide>
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="flex-1 min-w-0">
          <AutomationCenterHeader
            healthScore={summary.healthScore}
            activeCount={summary.activeCount}
            pausedCount={summary.pausedCount}
            failedCount={summary.failedCount}
            filters={filters}
            onFiltersChange={updateFilters}
          />
        </div>
        <button
          type="button"
          onClick={retry}
          disabled={isLoading}
          className={cn(
            "inline-flex items-center gap-2 self-start rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium",
            "text-gray-700 hover:border-brand-200 hover:text-brand-700 transition-colors disabled:opacity-60",
            "dark-tenant:bg-surface-dark-elevated dark-tenant:border-white/10 dark-tenant:text-slate-300",
            "dark-tenant:hover:border-violet-500/30 dark-tenant:hover:text-violet-300",
          )}
          aria-label={t("common.refresh")}
        >
          <RefreshCw size={14} className={cn(isLoading && "animate-spin")} />
          {t("common.refresh")}
        </button>
      </div>

      {isLoading ? <AutomationCenterSkeleton /> : null}

      {isError ? (
        <ErrorState
          message={t("automationCenter.error")}
          onRetry={retry}
          className="mt-6"
        />
      ) : null}

      {!isLoading && !isError ? (
        <div className="space-y-8 mt-2">
          <AutomationOverviewStrip
            successRate={summary.successRateOverall}
            executions24h={summary.totalExecutions24h}
            retryCountToday={summary.retryCountToday ?? 0}
            partialPublishFailuresToday={summary.partialPublishFailuresToday ?? 0}
            averageDurationMs={summary.averageDurationMs ?? null}
            scheduledJobs={summary.scheduledJobs ?? 0}
            deadLetterJobs={summary.deadLetterJobs ?? 0}
            automaticRetriesToday={summary.automaticRetriesToday ?? 0}
          />

          <AutomationJobsPanel
            jobs={jobs}
            mutatingId={jobMutatingId}
            onCancel={cancelJob}
            onRequeue={requeueJob}
          />

          {showMainList ? (
            <section aria-label={t("automationCenter.sections.automations")} className="space-y-4">
              <div className="flex items-center justify-between gap-2">
                <h2 className="section-title">
                  {hasActiveFilters
                    ? t("automationCenter.sections.filtered")
                    : t("automationCenter.sections.automations")}
                </h2>
                <span className="text-xs text-gray-500 dark-tenant:text-slate-500">
                  {filtered.length}{" "}
                  {filtered.length === 1
                    ? t("automationCenter.automationSingular")
                    : t("automationCenter.automationPlural")}
                </span>
              </div>

              {filtered.length === 0 ? (
                <AutomationEmptyState hasFilters={hasActiveFilters} onResetFilters={resetFilters} />
              ) : (
                <div className="space-y-4">
                  {(hasActiveFilters ? filtered : activeAutomations).map((automation, index) => (
                    <AutomationCard
                      key={automation.id}
                      automation={automation}
                      onSelect={handleSelect}
                      onToggle={toggleAutomation}
                      index={index}
                    />
                  ))}
                </div>
              )}
            </section>
          ) : null}

          {!hasActiveFilters ? (
            <>
              <AutomationExecutionHistoryPanel
                executions={recentExecutions}
                automations={automations}
                onSelectAutomation={handleSelect}
                onRetryExecution={retryExecution}
                retryState={retryState}
              />

              <AutomationUpcomingPanel
                automations={upcomingAutomations}
                onSelect={handleSelect}
              />

              <AutomationDisabledPanel
                automations={disabledAutomations}
                onSelect={handleSelect}
                onToggle={toggleAutomation}
              />
            </>
          ) : null}

          {hasActiveFilters && filters.section === "disabled" ? (
            <AutomationDisabledPanel
              automations={filtered}
              onSelect={handleSelect}
              onToggle={toggleAutomation}
            />
          ) : null}

          {hasActiveFilters && filters.section === "paused" ? (
            <section className="space-y-4">
              {filtered.map((automation, index) => (
                <AutomationCard
                  key={automation.id}
                  automation={automation}
                  onSelect={handleSelect}
                  onToggle={toggleAutomation}
                  index={index}
                />
              ))}
            </section>
          ) : null}

          {hasActiveFilters && filters.section === "draft" ? (
            <section className="space-y-4">
              {filtered.length === 0 ? (
                <AutomationEmptyState hasFilters onResetFilters={resetFilters} />
              ) : (
                filtered.map((automation, index) => (
                  <AutomationCard
                    key={automation.id}
                    automation={automation}
                    onSelect={handleSelect}
                    onToggle={toggleAutomation}
                    index={index}
                  />
                ))
              )}
            </section>
          ) : null}
        </div>
      ) : null}

      <AutomationDetailDrawer
        automation={selected}
        onClose={() => setSelected(null)}
        onToggle={handleToggle}
        onRunTest={runTest}
        onRetryExecution={retryExecution}
        isToggling={Boolean(selected && mutatingId === selected.id)}
        runState={runState}
        retryState={retryState}
      />
    </PageShell>
  );
}
