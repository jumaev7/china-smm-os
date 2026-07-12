"use client";

import { BellOff, FilterX, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/I18nProvider";

export function NotificationEmptyState({
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
          {t("notifications.empty.filteredTitle")}
        </h3>
        <p className="text-sm text-gray-500 mt-2 max-w-md dark-tenant:text-slate-500">
          {t("notifications.empty.filteredBody")}
        </p>
        <button
          type="button"
          onClick={onResetFilters}
          className={cn(
            "mt-6 inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold",
            "bg-brand-600 text-white hover:bg-brand-700 dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500",
          )}
        >
          {t("notifications.empty.clearFilters")}
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-2xl border border-dashed py-16 px-6 text-center",
        "border-emerald-200/60 bg-emerald-50/30 dark-tenant:border-emerald-500/20 dark-tenant:bg-emerald-500/5",
      )}
    >
      <div className="relative mb-6">
        <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-brand-100 to-violet-100 flex items-center justify-center dark-tenant:from-violet-500/20 dark-tenant:to-violet-600/10">
          <Inbox size={36} className="text-brand-600 dark-tenant:text-violet-400" aria-hidden />
        </div>
        <div className="absolute -bottom-1 -right-1 w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center ring-4 ring-white dark-tenant:bg-emerald-500/20 dark-tenant:ring-surface-dark-page">
          <BellOff size={14} className="text-emerald-600 dark-tenant:text-emerald-400" aria-hidden />
        </div>
      </div>
      <h3 className="text-lg font-semibold text-gray-900 dark-tenant:text-slate-100">
        {t("notifications.empty.title")}
      </h3>
      <p className="text-sm text-gray-500 mt-2 max-w-md leading-relaxed dark-tenant:text-slate-500">
        {t("notifications.empty.body")}
      </p>
    </div>
  );
}
