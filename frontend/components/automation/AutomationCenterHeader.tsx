"use client";

import { Activity, Pause, Play, Search, X, Zap } from "lucide-react";
import { KpiCard } from "@/components/ui/design-system/KpiCard";
import { PageHeader } from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";
import {
  SECTION_FILTERS,
  type AutomationFilters,
  type AutomationSectionFilter,
} from "@/lib/automation-center-ui";
import { cn } from "@/lib/utils";

export function AutomationCenterHeader({
  healthScore,
  activeCount,
  pausedCount,
  failedCount,
  filters,
  onFiltersChange,
}: {
  healthScore: number;
  activeCount: number;
  pausedCount: number;
  failedCount: number;
  filters: AutomationFilters;
  onFiltersChange: (patch: Partial<AutomationFilters>) => void;
}) {
  const { t } = useTranslation();

  const healthLabel =
    healthScore >= 90
      ? t("automationCenter.health.excellent")
      : healthScore >= 70
        ? t("automationCenter.health.good")
        : t("automationCenter.health.attention");

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("automationCenter.title")}
        subtitle={t("automationCenter.subtitle")}
        icon={Zap}
      />

      <section
        className="grid grid-cols-2 sm:grid-cols-4 gap-3 animate-fade-in-up"
        aria-label={t("automationCenter.summaryLabel")}
      >
        <KpiCard
          label={t("automationCenter.kpi.health")}
          value={`${healthScore}%`}
          sub={healthLabel}
          icon={Activity}
          iconClassName="bg-violet-50 text-violet-600 dark-tenant:bg-violet-500/15 dark-tenant:text-violet-400"
        />
        <KpiCard
          label={t("automationCenter.kpi.active")}
          value={activeCount}
          sub={t("automationCenter.kpi.activeSub")}
          icon={Play}
          iconClassName="bg-emerald-50 text-emerald-600 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-400"
        />
        <KpiCard
          label={t("automationCenter.kpi.paused")}
          value={pausedCount}
          sub={pausedCount > 0 ? t("automationCenter.kpi.pausedSub") : t("automationCenter.kpi.nonePaused")}
          icon={Pause}
          iconClassName="bg-amber-50 text-amber-600 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-400"
        />
        <KpiCard
          label={t("automationCenter.kpi.failed")}
          value={failedCount}
          sub={failedCount > 0 ? t("automationCenter.kpi.failedSub") : t("automationCenter.kpi.noneFailed")}
          icon={Zap}
          iconClassName="bg-red-50 text-red-600 dark-tenant:bg-red-500/15 dark-tenant:text-red-400"
        />
      </section>

      <nav aria-label={t("automationCenter.filters.label")}>
        <div className="flex flex-wrap gap-2">
          {SECTION_FILTERS.map((item) => {
            const active = filters.section === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onFiltersChange({ section: item.id as AutomationSectionFilter })}
                aria-pressed={active}
                className={
                  active
                    ? "rounded-xl bg-brand-600 px-3.5 py-2 text-xs font-semibold text-white shadow-sm dark-tenant:bg-violet-600"
                    : "rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-xs font-medium text-gray-600 hover:border-brand-200 hover:text-brand-700 dark-tenant:border-white/10 dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-400 dark-tenant:hover:border-violet-500/30 dark-tenant:hover:text-violet-300"
                }
              >
                {t(item.labelKey)}
              </button>
            );
          })}
        </div>
      </nav>

      <div className="relative max-w-md">
        <Search
          size={15}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark-tenant:text-slate-500"
          aria-hidden
        />
        <input
          type="search"
          value={filters.search}
          onChange={(e) => onFiltersChange({ search: e.target.value })}
          placeholder={t("automationCenter.searchPlaceholder")}
          aria-label={t("automationCenter.searchPlaceholder")}
          className={cn(
            "w-full rounded-xl border border-gray-200 bg-white py-2 pl-9 pr-9 text-sm",
            "text-gray-900 placeholder:text-gray-400",
            "focus:outline-none focus:ring-2 focus:ring-brand-500/30 focus:border-brand-300",
            "dark-tenant:border-white/10 dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-100",
            "dark-tenant:placeholder:text-slate-500 dark-tenant:focus:ring-violet-500/30 dark-tenant:focus:border-violet-500/40",
          )}
        />
        {filters.search ? (
          <button
            type="button"
            onClick={() => onFiltersChange({ search: "" })}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md text-gray-400 hover:text-gray-600 dark-tenant:hover:text-slate-300"
            aria-label={t("automationCenter.searchClear")}
          >
            <X size={14} />
          </button>
        ) : null}
      </div>
    </div>
  );
}
