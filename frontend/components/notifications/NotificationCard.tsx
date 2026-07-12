"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/I18nProvider";
import {
  CATEGORY_LABEL_KEYS,
  formatRelativeTime,
  SEVERITY_DOT_STYLES,
  SEVERITY_LABEL_KEYS,
  SEVERITY_STYLES,
  type AppNotification,
} from "@/lib/notification-center-ui";

export function NotificationCard({
  notification,
  onSelect,
  index = 0,
}: {
  notification: AppNotification;
  onSelect: (notification: AppNotification) => void;
  index?: number;
}) {
  const { t } = useTranslation();
  const Icon = notification.icon;
  const isUnread = !notification.read;
  const isCritical = notification.severity === "critical";
  const isWarning = notification.severity === "warning";

  return (
    <article
      className={cn(
        "group relative flex flex-col rounded-2xl border p-5 transition-all duration-300 animate-fade-in-up",
        "focus-within:ring-2 focus-within:ring-brand-500/40 focus-within:ring-offset-2 dark-tenant:focus-within:ring-violet-500/40",
        isUnread
          ? isCritical
            ? "border-red-200/80 bg-red-50/20 shadow-card dark-tenant:border-red-500/20 dark-tenant:bg-red-500/5"
            : isWarning
              ? "border-amber-200/80 bg-amber-50/25 shadow-card dark-tenant:border-amber-500/20 dark-tenant:bg-amber-500/5"
              : "border-brand-200/60 bg-brand-50/20 shadow-card dark-tenant:border-violet-500/20 dark-tenant:bg-violet-500/5"
          : "border-slate-200 bg-white shadow-card hover:shadow-card-hover hover:border-brand-200 dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card dark-tenant:hover:border-violet-500/30",
      )}
      style={{ animationDelay: `${index * 35}ms` }}
    >
      {isUnread ? (
        <div
          className={cn(
            "absolute top-0 left-5 right-5 h-0.5 rounded-full bg-gradient-to-r",
            isCritical
              ? "from-red-400 to-red-600"
              : isWarning
                ? "from-amber-400 to-orange-500"
                : "from-brand-400 to-violet-500 dark-tenant:from-violet-400 dark-tenant:to-violet-600",
          )}
        />
      ) : null}

      <button
        type="button"
        onClick={() => onSelect(notification)}
        className="flex flex-col flex-1 text-left w-full"
        aria-label={`${isUnread ? "Unread: " : ""}${notification.title}`}
      >
        <div className="flex items-start gap-4">
          <div className="relative shrink-0">
            <div
              className={cn(
                "flex items-center justify-center w-12 h-12 rounded-xl ring-1",
                notification.iconClassName,
                "ring-black/5 dark-tenant:ring-white/10",
              )}
            >
              <Icon size={22} aria-hidden />
            </div>
            {isUnread ? (
              <span
                className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-brand-600 ring-2 ring-white dark-tenant:bg-violet-500 dark-tenant:ring-surface-dark-card"
                aria-hidden
              />
            ) : null}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3
                className={cn(
                  "font-semibold text-[15px] text-navy-900 dark-tenant:text-slate-100",
                  isUnread && "text-navy-950 dark-tenant:text-white",
                )}
              >
                {notification.title}
              </h3>
              <span
                className={cn(
                  "text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full",
                  SEVERITY_STYLES[notification.severity],
                )}
              >
                {t(SEVERITY_LABEL_KEYS[notification.severity])}
              </span>
            </div>
            <p className="text-[11px] text-gray-500 mt-0.5 dark-tenant:text-slate-500">
              {t(CATEGORY_LABEL_KEYS[notification.category])}
            </p>
            <p className="text-sm text-gray-600 mt-1.5 leading-relaxed line-clamp-2 dark-tenant:text-slate-400">
              {notification.description}
            </p>
          </div>

          <div className="shrink-0 flex flex-col items-end gap-1 text-right">
            <time
              dateTime={notification.createdAt}
              className="text-[11px] text-gray-400 whitespace-nowrap dark-tenant:text-slate-500"
            >
              {formatRelativeTime(notification.createdAt)}
            </time>
            <span className="flex items-center gap-1 text-[10px] text-gray-400 dark-tenant:text-slate-600">
              <span
                className={cn("w-1.5 h-1.5 rounded-full", SEVERITY_DOT_STYLES[notification.severity])}
                aria-hidden
              />
              {t(SEVERITY_LABEL_KEYS[notification.severity])}
            </span>
          </div>
        </div>
      </button>

      <div className="mt-4 pt-4 border-t border-slate-100 dark-tenant:border-white/[0.06] flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Link
            href={notification.primaryAction.href}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
              isCritical
                ? "bg-red-100 text-red-800 hover:bg-red-200 dark-tenant:bg-red-500/15 dark-tenant:text-red-300"
                : isWarning
                  ? "bg-amber-100 text-amber-800 hover:bg-amber-200 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-300"
                  : "bg-brand-600 text-white hover:bg-brand-700 dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500",
            )}
            onClick={(e) => e.stopPropagation()}
          >
            {notification.primaryAction.label}
          </Link>
          {notification.secondaryAction ? (
            <Link
              href={notification.secondaryAction.href}
              className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 dark-tenant:text-slate-400 dark-tenant:hover:bg-white/[0.06]"
              onClick={(e) => e.stopPropagation()}
            >
              {notification.secondaryAction.label}
            </Link>
          ) : null}
        </div>

        <button
          type="button"
          onClick={() => onSelect(notification)}
          className="inline-flex items-center gap-0.5 text-xs font-medium text-gray-400 hover:text-brand-700 dark-tenant:hover:text-violet-300 transition-colors"
        >
          {t("notifications.details")}
          <ChevronRight size={14} aria-hidden />
        </button>
      </div>
    </article>
  );
}
