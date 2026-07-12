"use client";

import { useEffect, useState } from "react";
import { NotificationCard } from "@/components/notifications/NotificationCard";
import { NotificationCenterHeader } from "@/components/notifications/NotificationCenterHeader";
import { NotificationCenterSkeleton } from "@/components/notifications/NotificationCenterSkeleton";
import { NotificationDetailDrawer } from "@/components/notifications/NotificationDetailDrawer";
import { NotificationEmptyState } from "@/components/notifications/NotificationPanels";
import { ErrorState } from "@/components/ui/PageStates";
import { PageShell } from "@/components/ui/design-system";
import { getApiErrorMessage } from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { useNotificationCenter } from "@/lib/notification-center-hooks";
import type { AppNotification } from "@/lib/notification-center-ui";
import { cn } from "@/lib/utils";

export default function NotificationsPage() {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<AppNotification | null>(null);

  const {
    filtered,
    filters,
    summary,
    isLoading,
    isLoadingMore,
    isError,
    error,
    hasActiveFilters,
    hasMore,
    total,
    updateFilters,
    resetFilters,
    markAsRead,
    markAllAsRead,
    dismissNotification,
    loadMore,
    retry,
    isMutating,
  } = useNotificationCenter();

  const handleSelect = (notification: AppNotification) => {
    setSelected(notification);
    if (!notification.read) {
      markAsRead(notification.id);
    }
  };

  const handleDismiss = (id: string) => {
    dismissNotification(id);
    setSelected((prev) => (prev?.id === id ? null : prev));
  };

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
    };
    if (selected) {
      document.addEventListener("keydown", onKeyDown);
      return () => document.removeEventListener("keydown", onKeyDown);
    }
  }, [selected]);

  return (
    <PageShell wide>
      <NotificationCenterHeader
        unreadCount={summary.unreadCount}
        criticalCount={summary.criticalCount}
        warningCount={summary.warningCount}
        resolvedTodayCount={summary.resolvedTodayCount}
        filters={filters}
        onFiltersChange={updateFilters}
        onMarkAllRead={markAllAsRead}
        markAllDisabled={summary.unreadCount === 0 || isMutating}
      />

      {isLoading ? <NotificationCenterSkeleton /> : null}

      {isError && !isLoading ? (
        <ErrorState
          title={t("notifications.errorTitle")}
          message={getApiErrorMessage(error)}
          onRetry={retry}
        />
      ) : null}

      {!isLoading && !isError ? (
        <section aria-label={t("notifications.feedAria")} className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="section-title">
              {filters.category === "all"
                ? t("notifications.allNotifications")
                : t("notifications.filteredNotifications")}
            </h2>
            <span className="text-xs text-gray-500 dark-tenant:text-slate-500">
              {t("notifications.countLabel", { count: total })}
            </span>
          </div>

          {filtered.length === 0 ? (
            <NotificationEmptyState hasFilters={hasActiveFilters} onResetFilters={resetFilters} />
          ) : (
            <div className="space-y-4">
              {filtered.map((notification, index) => (
                <NotificationCard
                  key={notification.id}
                  notification={notification}
                  onSelect={handleSelect}
                  index={index}
                />
              ))}
            </div>
          )}

          {hasMore ? (
            <div className="flex justify-center pt-2">
              <button
                type="button"
                onClick={loadMore}
                disabled={isLoadingMore || isMutating}
                className={cn(
                  "rounded-xl border border-gray-200 bg-white px-5 py-2.5 text-sm font-semibold text-gray-700",
                  "hover:border-brand-200 hover:text-brand-700 disabled:opacity-50",
                  "dark-tenant:border-white/10 dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-300",
                )}
              >
                {isLoadingMore ? t("common.loading") : t("notifications.loadMore")}
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      <NotificationDetailDrawer
        notification={selected}
        onClose={() => setSelected(null)}
        onMarkRead={markAsRead}
        onDismiss={handleDismiss}
      />
    </PageShell>
  );
}
