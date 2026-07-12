"use client";

import { AlertTriangle, Bell, CheckCircle2, Inbox, Search, X } from "lucide-react";
import { KpiCard } from "@/components/ui/design-system/KpiCard";
import { PageHeader } from "@/components/ui/design-system";
import {
  NOTIFICATION_CATEGORIES,
  READ_FILTER_OPTIONS,
  SEVERITY_OPTIONS,
  TIME_FILTER_OPTIONS,
  type NotificationCategory,
  type NotificationFilters,
} from "@/lib/notification-center-ui";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";

export function NotificationCenterHeader({
  unreadCount,
  criticalCount,
  warningCount,
  resolvedTodayCount,
  filters,
  onFiltersChange,
  onMarkAllRead,
  markAllDisabled,
}: {
  unreadCount: number;
  criticalCount: number;
  warningCount: number;
  resolvedTodayCount: number;
  filters: NotificationFilters;
  onFiltersChange: (patch: Partial<NotificationFilters>) => void;
  onMarkAllRead: () => void;
  markAllDisabled: boolean;
}) {
  const { t } = useTranslation();

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <PageHeader
          title={t("notifications.title")}
          subtitle={t("notifications.subtitle")}
          icon={Bell}
        />
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          {unreadCount > 0 ? (
            <span
              className="inline-flex items-center gap-1.5 rounded-full bg-brand-600 px-3 py-1 text-xs font-semibold text-white dark-tenant:bg-violet-600"
              aria-live="polite"
            >
              <Inbox size={12} aria-hidden />
              {t("notifications.unreadCount", { count: unreadCount })}
            </span>
          ) : null}
          <button
            type="button"
            onClick={onMarkAllRead}
            disabled={markAllDisabled}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-xl border px-3.5 py-2 text-xs font-semibold transition-colors",
              "border-gray-200 bg-white text-gray-700 hover:border-brand-200 hover:text-brand-700",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "dark-tenant:border-white/10 dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-300",
              "dark-tenant:hover:border-violet-500/30 dark-tenant:hover:text-violet-300",
            )}
          >
            <CheckCircle2 size={14} aria-hidden />
            {t("notifications.markAllAsRead")}
          </button>
        </div>
      </div>

      <section
        className="grid grid-cols-2 sm:grid-cols-4 gap-3 animate-fade-in-up"
        aria-label={t("notifications.summaryAria")}
      >
        <KpiCard
          label={t("notifications.unread")}
          value={unreadCount}
          sub={unreadCount > 0 ? t("notifications.unreadSub") : t("notifications.allCaughtUp")}
          icon={Inbox}
          iconClassName="bg-sky-50 text-sky-600 dark-tenant:bg-sky-500/15 dark-tenant:text-sky-400"
        />
        <KpiCard
          label={t("notifications.critical")}
          value={criticalCount}
          sub={criticalCount > 0 ? t("notifications.criticalSub") : t("notifications.noCritical")}
          icon={AlertTriangle}
          iconClassName="bg-red-50 text-red-600 dark-tenant:bg-red-500/15 dark-tenant:text-red-400"
        />
        <KpiCard
          label={t("notifications.warnings")}
          value={warningCount}
          sub={warningCount > 0 ? t("notifications.warningsSub") : t("notifications.allClear")}
          icon={AlertTriangle}
          iconClassName="bg-amber-50 text-amber-600 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-400"
        />
        <KpiCard
          label={t("notifications.resolvedToday")}
          value={resolvedTodayCount}
          sub={t("notifications.resolvedTodaySub")}
          icon={CheckCircle2}
          iconClassName="bg-emerald-50 text-emerald-600 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-400"
        />
      </section>

      <nav aria-label={t("notifications.categoriesAria")}>
        <div className="flex flex-wrap gap-2">
          {NOTIFICATION_CATEGORIES.map((cat) => {
            const active = filters.category === cat.id;
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => onFiltersChange({ category: cat.id as NotificationCategory })}
                aria-pressed={active}
                className={
                  active
                    ? "rounded-xl bg-brand-600 px-3.5 py-2 text-xs font-semibold text-white shadow-sm dark-tenant:bg-violet-600"
                    : "rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-xs font-medium text-gray-600 hover:border-brand-200 hover:text-brand-700 dark-tenant:border-white/10 dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-400 dark-tenant:hover:border-violet-500/30 dark-tenant:hover:text-violet-300"
                }
              >
                {t(cat.labelKey)}
              </button>
            );
          })}
        </div>
      </nav>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative flex-1 max-w-md">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark-tenant:text-slate-500"
            aria-hidden
          />
          <input
            type="search"
            value={filters.search}
            onChange={(e) => onFiltersChange({ search: e.target.value })}
            placeholder={t("notifications.searchPlaceholder")}
            aria-label={t("notifications.searchPlaceholder")}
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
              aria-label={t("notifications.clearSearch")}
            >
              <X size={14} />
            </button>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-2" role="group" aria-label={t("notifications.filtersAria")}>
          <FilterSelect
            label={t("notifications.filters.severity")}
            value={filters.severity}
            options={SEVERITY_OPTIONS.map((opt) => ({ id: opt.id, label: t(opt.labelKey) }))}
            onChange={(value) =>
              onFiltersChange({ severity: value as NotificationFilters["severity"] })
            }
          />
          <FilterSelect
            label={t("notifications.filters.status")}
            value={filters.read}
            options={READ_FILTER_OPTIONS.map((opt) => ({ id: opt.id, label: t(opt.labelKey) }))}
            onChange={(value) =>
              onFiltersChange({ read: value as NotificationFilters["read"] })
            }
          />
          <FilterSelect
            label={t("notifications.filters.time")}
            value={filters.time}
            options={TIME_FILTER_OPTIONS.map((opt) => ({ id: opt.id, label: t(opt.labelKey) }))}
            onChange={(value) =>
              onFiltersChange({ time: value as NotificationFilters["time"] })
            }
          />
        </div>
      </div>
    </div>
  );
}

function FilterSelect<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <label className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark-tenant:text-slate-500">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        aria-label={label}
        className={cn(
          "rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700",
          "focus:outline-none focus:ring-2 focus:ring-brand-500/30",
          "dark-tenant:border-white/10 dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-300",
          "dark-tenant:focus:ring-violet-500/30",
        )}
      >
        {options.map((opt) => (
          <option key={opt.id} value={opt.id}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}
