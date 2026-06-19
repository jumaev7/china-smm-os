"use client";

import { useQuery } from "@tanstack/react-query";
import { contentApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AlertCircle, CheckCircle2, ClipboardCheck, Sparkles } from "lucide-react";

interface Props {
  contentId: string;
  intent?: "approve" | "schedule";
  onFixWithAi?: () => void;
  fixingWithAi?: boolean;
}

export function PublishingChecklist({
  contentId,
  intent = "approve",
  onFixWithAi,
  fixingWithAi,
}: Props) {
  const { data: readiness, isLoading } = useQuery({
    queryKey: ["content-readiness", contentId, intent],
    queryFn: () => contentApi.readiness(contentId, intent).then((r) => r.data),
  });

  if (isLoading || !readiness) {
    return (
      <div className="card p-4 animate-pulse">
        <div className="h-4 bg-gray-100 rounded w-40 mb-3" />
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-3 bg-gray-100 rounded w-full" />
          ))}
        </div>
      </div>
    );
  }

  const canApprove = readiness.ready_for_approve;
  const missingCaptions = readiness.items.some(
    (i) => (i.id === "caption" || i.id === "hashtags") && !i.ready,
  );

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <ClipboardCheck size={15} className="text-brand-600 shrink-0" />
          <h3 className="text-sm font-semibold text-gray-900">Publishing checklist</h3>
        </div>
        <span
          className={cn(
            "text-[10px] font-medium px-2 py-0.5 rounded-full",
            canApprove
              ? "bg-emerald-100 text-emerald-700"
              : "bg-amber-100 text-amber-800",
          )}
        >
          {canApprove ? "Ready to publish" : "Not ready"}
        </span>
      </div>

      <ul className="space-y-2">
        {readiness.items.map((check) => (
          <li key={check.id} className="flex items-start gap-2 text-xs">
            {check.ready ? (
              <CheckCircle2 size={14} className="text-emerald-500 shrink-0 mt-0.5" />
            ) : (
              <AlertCircle
                size={14}
                className={cn(
                  "shrink-0 mt-0.5",
                  check.critical ? "text-amber-500" : "text-gray-400",
                )}
              />
            )}
            <div className="min-w-0">
              <span className={cn(check.ready ? "text-gray-700" : "text-gray-900")}>
                {check.label}
              </span>
              {!check.ready && check.message && (
                <p className="text-[10px] text-amber-700 mt-0.5">{check.message}</p>
              )}
            </div>
          </li>
        ))}
      </ul>

      {missingCaptions && onFixWithAi && (
        <button
          type="button"
          className="btn-secondary text-xs w-full mt-3"
          onClick={onFixWithAi}
          disabled={fixingWithAi}
        >
          <Sparkles size={13} />
          {fixingWithAi ? "Generating…" : "Fix with AI"}
        </button>
      )}
    </div>
  );
}

export function useContentReadiness(
  contentId: string,
  intent: "approve" | "schedule" = "approve",
  enabled = true,
) {
  return useQuery({
    queryKey: ["content-readiness", contentId, intent],
    queryFn: () => contentApi.readiness(contentId, intent).then((r) => r.data),
    enabled: enabled && !!contentId,
  });
}
