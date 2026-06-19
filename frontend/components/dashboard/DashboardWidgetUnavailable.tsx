"use client";

import { AlertCircle } from "lucide-react";
import { useTranslation } from "@/lib/I18nProvider";

/** Inline empty state for optional dashboard widgets — never blocks the page. */
export function DashboardWidgetUnavailable({ title }: { title: string }) {
  const { t } = useTranslation();

  return (
    <div className="card p-4 space-y-2 border-dashed border-gray-200 bg-gray-50/40">
      <p className="text-sm font-semibold text-gray-700">{title}</p>
      <p className="text-xs text-gray-500 flex items-start gap-1.5">
        <AlertCircle size={14} className="shrink-0 mt-0.5 text-gray-400" />
        {t("dashboard.widgetUnavailable")}
      </p>
    </div>
  );
}
