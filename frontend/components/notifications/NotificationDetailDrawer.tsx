"use client";

import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  ExternalLink,
  Lightbulb,
  ListTree,
  Tag,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/I18nProvider";
import {
  CATEGORY_LABEL_KEYS,
  formatRelativeTime,
  SEVERITY_LABEL_KEYS,
  SEVERITY_STYLES,
  type AppNotification,
} from "@/lib/notification-center-ui";

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

export function NotificationDetailDrawer({
  notification,
  onClose,
  onMarkRead,
  onDismiss,
}: {
  notification: AppNotification | null;
  onClose: () => void;
  onMarkRead: (id: string) => void;
  onDismiss: (id: string) => void;
}) {
  const { t } = useTranslation();
  if (!notification) return null;

  const Icon = notification.icon;

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
        aria-labelledby="notification-drawer-title"
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
                  notification.iconClassName,
                  "ring-black/5 dark-tenant:ring-white/10",
                )}
              >
                <Icon size={22} aria-hidden />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-gray-500 dark-tenant:text-slate-500 font-medium uppercase tracking-wide">
                  {t(CATEGORY_LABEL_KEYS[notification.category])}
                </p>
                <h2
                  id="notification-drawer-title"
                  className="text-lg font-semibold text-gray-900 dark-tenant:text-slate-100 mt-0.5"
                >
                  {notification.title}
                </h2>
                <div className="flex flex-wrap items-center gap-2 mt-1.5">
                  <span
                    className={cn(
                      "text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full",
                      SEVERITY_STYLES[notification.severity],
                    )}
                  >
                    {t(SEVERITY_LABEL_KEYS[notification.severity])}
                  </span>
                  <time
                    dateTime={notification.createdAt}
                    className="text-xs text-gray-500 flex items-center gap-1 dark-tenant:text-slate-500"
                  >
                    <Clock size={11} aria-hidden />
                    {formatRelativeTime(notification.createdAt)}
                  </time>
                  {!notification.read ? (
                    <span className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-brand-100 text-brand-700 dark-tenant:bg-violet-500/15 dark-tenant:text-violet-300">
                      {t("notifications.unread")}
                    </span>
                  ) : null}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark-tenant:hover:bg-white/[0.06] dark-tenant:hover:text-slate-200"
              aria-label={t("notifications.closeDetails")}
            >
              <X size={18} />
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          <DrawerSection title={t("notifications.sections.overview")} icon={CheckCircle2}>
            <p className="text-sm text-gray-600 dark-tenant:text-slate-400 leading-relaxed">
              {notification.description}
            </p>
          </DrawerSection>

          <DrawerSection title={t("notifications.sections.suggestedAction")} icon={Lightbulb}>
            <p className="text-sm text-gray-700 dark-tenant:text-slate-300 leading-relaxed rounded-xl border border-amber-200/60 bg-amber-50/40 p-3 dark-tenant:border-amber-500/20 dark-tenant:bg-amber-500/5">
              {notification.suggestedAction}
            </p>
          </DrawerSection>

          <DrawerSection title={t("notifications.sections.timeline")} icon={ListTree}>
            <ol className="relative border-l border-gray-200 ml-2 space-y-4 dark-tenant:border-white/10">
              {notification.timeline.map((event, idx) => (
                <li key={event.id} className="ml-4 relative">
                  <span
                    className={cn(
                      "absolute -left-[1.3rem] top-1 w-2.5 h-2.5 rounded-full ring-2 ring-white dark-tenant:ring-surface-dark-page",
                      idx === 0
                        ? "bg-brand-500 dark-tenant:bg-violet-500"
                        : "bg-gray-300 dark-tenant:bg-slate-600",
                    )}
                    aria-hidden
                  />
                  <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-200">
                    {event.label}
                  </p>
                  {event.detail ? (
                    <p className="text-xs text-gray-500 mt-0.5 dark-tenant:text-slate-500">
                      {event.detail}
                    </p>
                  ) : null}
                  <time
                    dateTime={event.timestamp}
                    className="text-[11px] text-gray-400 mt-0.5 block dark-tenant:text-slate-600"
                  >
                    {formatRelativeTime(event.timestamp)}
                  </time>
                </li>
              ))}
            </ol>
          </DrawerSection>

          {Object.keys(notification.metadata).length > 0 ? (
            <DrawerSection title={t("notifications.sections.metadata")} icon={Tag}>
              <dl className="rounded-xl border border-gray-100 divide-y divide-gray-100 dark-tenant:border-white/[0.06] dark-tenant:divide-white/[0.06]">
                {Object.entries(notification.metadata).map(([key, value]) => (
                  <div key={key} className="flex items-start justify-between gap-3 px-3 py-2 text-sm">
                    <dt className="text-gray-500 capitalize dark-tenant:text-slate-500">
                      {key.replace(/([A-Z])/g, " $1").trim()}
                    </dt>
                    <dd className="font-medium text-gray-900 text-right dark-tenant:text-slate-200">
                      {String(value)}
                    </dd>
                  </div>
                ))}
              </dl>
            </DrawerSection>
          ) : null}

          <DrawerSection title={t("notifications.sections.relatedModule")} icon={ExternalLink}>
            <Link
              href={notification.relatedModuleHref}
              className="inline-flex items-center gap-2 text-sm font-medium text-brand-700 hover:text-brand-800 dark-tenant:text-violet-300 dark-tenant:hover:text-violet-200"
            >
              {notification.relatedModule}
              <ArrowRight size={14} aria-hidden />
            </Link>
          </DrawerSection>
        </div>

        <footer className="shrink-0 p-4 border-t border-gray-100 dark-tenant:border-white/[0.06] flex flex-wrap gap-2">
          <Link
            href={notification.primaryAction.href}
            className={cn(
              "inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-semibold",
              "bg-brand-600 text-white hover:bg-brand-700 dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500",
            )}
          >
            {notification.primaryAction.label}
          </Link>
          {notification.secondaryAction ? (
            <Link
              href={notification.secondaryAction.href}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark-tenant:border-white/10 dark-tenant:text-slate-300 dark-tenant:hover:bg-white/[0.04]"
            >
              {notification.secondaryAction.label}
            </Link>
          ) : null}
          {!notification.read ? (
            <button
              type="button"
              onClick={() => onMarkRead(notification.id)}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark-tenant:border-white/10 dark-tenant:text-slate-300 dark-tenant:hover:bg-white/[0.04]"
            >
              {t("notifications.markAsRead")}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => onDismiss(notification.id)}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl px-3 py-2.5 text-sm text-gray-400 hover:text-red-600 hover:bg-red-50 dark-tenant:hover:bg-red-500/10 dark-tenant:hover:text-red-400"
            aria-label={t("notifications.delete")}
          >
            <Trash2 size={15} />
          </button>
        </footer>
      </aside>
    </>
  );
}
