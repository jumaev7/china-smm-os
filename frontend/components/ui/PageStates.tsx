"use client";

import { AlertCircle, Inbox, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/I18nProvider";
import { formatPartialErrorsForDisplay } from "@/lib/partialErrors";
import {
  getUserFacingApiErrorMessage,
  sanitizeErrorMessage,
} from "@/lib/user-facing-errors";

export function LoadingState({
  message,
  /** @deprecated use message */
  label,
  /** @deprecated use message */
  title,
  className,
  variant = "default",
}: {
  message?: string;
  label?: string;
  title?: string;
  className?: string;
  variant?: "default" | "inline" | "card";
}) {
  const { t } = useTranslation();
  const text = message ?? title ?? label ?? t("common.loading");

  if (variant === "inline") {
    return (
      <span className={cn("inline-flex items-center gap-2 text-sm text-gray-500", className)}>
        <Loader2 size={16} className="animate-spin text-brand-500" />
        {text}
      </span>
    );
  }

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3",
        variant === "card" ? "card-premium p-12 min-h-[200px]" : "p-8 min-h-[240px]",
        className,
      )}
    >
      <div className="relative">
        <div className="w-12 h-12 rounded-2xl bg-brand-50 flex items-center justify-center">
          <Loader2 size={22} className="animate-spin text-brand-600" />
        </div>
      </div>
      <p className="text-sm font-medium text-gray-600">{text}</p>
      <div className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-brand-300 animate-pulse"
            style={{ animationDelay: `${i * 150}ms` }}
          />
        ))}
      </div>
    </div>
  );
}

export function ErrorState({
  message,
  /** @deprecated use message */
  title,
  error,
  onRetry,
  className,
  technical = false,
}: {
  message?: string;
  title?: string;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
  /** Show raw/technical errors (admin tooling). Default: friendly localized message. */
  technical?: boolean;
}) {
  const { t } = useTranslation();
  const rawMessage = message ?? title;
  const displayMessage = technical
    ? rawMessage ?? t("errors.generic")
    : error != null
      ? getUserFacingApiErrorMessage(error, t)
      : rawMessage
        ? sanitizeErrorMessage(rawMessage, t)
        : t("errors.generic");
  return (
    <div
      className={cn(
        "card-premium p-10 flex flex-col items-center justify-center gap-4 text-center max-w-md mx-auto",
        className,
      )}
    >
      <div className="w-12 h-12 rounded-2xl bg-danger-50 border border-danger-200 flex items-center justify-center">
        <AlertCircle size={22} className="text-danger-600" />
      </div>
      <div>
        <p className="text-sm font-semibold text-navy-900">{t("errors.title")}</p>
        <p className="text-sm text-gray-600 mt-1">{displayMessage}</p>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="btn-secondary text-xs"
        >
          <RefreshCw size={14} />
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  message,
  /** @deprecated use description */
  hint,
  action,
  className,
}: {
  title?: string;
  description?: string;
  /** @deprecated use title */
  message?: string;
  hint?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  const { t } = useTranslation();
  const displayTitle = title ?? message ?? t("common.nothingHere");
  const displayDescription = description ?? hint;

  return (
    <div
      className={cn(
        "card-premium p-10 flex flex-col items-center justify-center gap-3 text-center",
        className,
      )}
    >
      <div className="w-14 h-14 rounded-2xl bg-slate-50 border border-gray-100 flex items-center justify-center">
        <Inbox size={26} className="text-gray-300" />
      </div>
      <div className="max-w-sm">
        <p className="font-semibold text-navy-900">{displayTitle}</p>
        {displayDescription && <p className="text-xs text-gray-500 mt-1.5 leading-relaxed">{displayDescription}</p>}
      </div>
      {action}
    </div>
  );
}

export function PartialErrorsBanner({ errors }: { errors?: string[] | null }) {
  const { t } = useTranslation();
  if (!errors?.length) return null;

  const unavailableLabel = t("common.partialErrorsUnavailable");
  const message = formatPartialErrorsForDisplay(errors, unavailableLabel);

  return (
    <div className="rounded-xl border border-warning-200 bg-warning-50 px-4 py-2.5 text-xs text-warning-800 flex items-start gap-2">
      <Sparkles size={14} className="shrink-0 mt-0.5 text-warning-600" />
      <span>{message}</span>
    </div>
  );
}
