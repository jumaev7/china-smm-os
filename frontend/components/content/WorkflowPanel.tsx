"use client";

import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  workflowApi,
  WorkflowProgress,
  WorkflowStepId,
  VoiceoverLang,
  SubtitleBurnLang,
  VoiceoverMode,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Check, Loader2, RefreshCw, Rocket, XCircle } from "lucide-react";
import toast from "react-hot-toast";

const DISPLAY_STEPS: { id: WorkflowStepId; label: string }[] = [
  { id: "subtitles", label: "subtitles" },
  { id: "translations", label: "translations" },
  { id: "captions", label: "captions" },
  { id: "voice", label: "voice" },
  { id: "export", label: "export" },
];

interface Props {
  contentId: string;
  voiceLang: VoiceoverLang;
  subtitleLang: SubtitleBurnLang;
  voiceMode: VoiceoverMode;
  sourceLanguage?: string;
  sourceText?: string;
  contextHint?: string;
  disabled?: boolean;
}

function stepIcon(status: string) {
  if (status === "completed" || status === "skipped") {
    return <Check size={14} className="text-green-600 shrink-0" />;
  }
  if (status === "running") {
    return <Loader2 size={14} className="text-brand-600 animate-spin shrink-0" />;
  }
  if (status === "failed") {
    return <XCircle size={14} className="text-red-500 shrink-0" />;
  }
  return <span className="w-3.5 h-3.5 rounded-full border border-gray-300 shrink-0" />;
}

export function WorkflowPanel({
  contentId,
  voiceLang,
  subtitleLang,
  voiceMode,
  sourceLanguage,
  sourceText,
  contextHint,
  disabled,
}: Props) {
  const qc = useQueryClient();

  const { data: progress, refetch } = useQuery({
    queryKey: ["workflow", contentId],
    queryFn: () => workflowApi.progress(contentId).then((r) => r.data),
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 1500 : false,
  });

  const prepareMutation = useMutation({
    mutationFn: () =>
      workflowApi.prepare(contentId, {
        voice_lang: voiceLang,
        subtitle_lang: subtitleLang,
        voice_mode: voiceMode,
        source_language: sourceLanguage,
        source_text: sourceText?.trim() || undefined,
        context_hint: contextHint?.trim() || undefined,
      }),
    onSuccess: () => {
      refetch();
      toast.success("Workflow started");
    },
    onError: () => toast.error("Failed to start workflow"),
  });

  const retryMutation = useMutation({
    mutationFn: () => workflowApi.retry(contentId),
    onSuccess: () => {
      refetch();
      toast.success("Retrying failed steps");
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Retry failed");
    },
  });

  useEffect(() => {
    if (progress?.status === "completed" || progress?.status === "failed") {
      qc.invalidateQueries({ queryKey: ["content", contentId] });
    }
  }, [progress?.status, contentId, qc]);

  const running = progress?.status === "running";
  const showPanel = running || progress?.status === "completed" || progress?.status === "failed";

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => prepareMutation.mutate()}
        disabled={disabled || running || prepareMutation.isPending}
        className="w-full inline-flex items-center justify-center gap-2 text-sm font-semibold py-2.5 px-4 rounded-xl bg-gradient-to-r from-brand-600 to-purple-600 text-white hover:from-brand-700 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-colors"
      >
        {running ? (
          <Loader2 size={16} className="animate-spin" />
        ) : (
          <Rocket size={16} />
        )}
        {running ? "Preparing…" : "🚀 Prepare Everything"}
      </button>

      {showPanel && progress && (
        <WorkflowProgressView progress={progress} onRetry={() => retryMutation.mutate()} retrying={retryMutation.isPending} />
      )}
    </div>
  );
}

function WorkflowProgressView({
  progress,
  onRetry,
  retrying,
}: {
  progress: WorkflowProgress;
  onRetry: () => void;
  retrying: boolean;
}) {
  const stepMap = new Map(progress.steps.map((s) => [s.id, s]));
  const running = progress.status === "running";
  const done = progress.status === "completed";

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3 space-y-2">
      <p className="text-xs font-medium text-gray-700">
        {running ? "Preparing…" : done ? "✅ Everything ready" : progress.message || "Workflow finished"}
      </p>

      <ul className="space-y-1">
        {DISPLAY_STEPS.map(({ id, label }) => {
          const step = stepMap.get(id);
          const status = step?.status ?? "pending";
          return (
            <li key={id} className="flex items-start gap-2 text-xs text-gray-600">
              {stepIcon(status)}
              <span className={cn(status === "completed" && "text-gray-800")}>
                {status === "completed" || status === "skipped" ? "✔" : ""} {label}
                {status === "failed" && step?.error && (
                  <span className="block text-[10px] text-red-500 mt-0.5">{step.error}</span>
                )}
              </span>
            </li>
          );
        })}
      </ul>

      {(progress.steps.some((s) => ["hashtags", "post_time", "status"].includes(s.id) && s.status !== "pending")) && (
        <ul className="pt-1 border-t border-gray-100 space-y-0.5">
          {(["hashtags", "post_time", "status"] as WorkflowStepId[]).map((id) => {
            const step = stepMap.get(id);
            if (!step || step.status === "pending") return null;
            return (
              <li key={id} className="flex items-center gap-2 text-[10px] text-gray-500">
                {stepIcon(step.status)}
                <span>{step.label}{step.status === "failed" && step.error ? `: ${step.error}` : ""}</span>
              </li>
            );
          })}
        </ul>
      )}

      {progress.can_retry && !running && (
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="mt-1 w-full text-xs inline-flex items-center justify-center gap-1.5 py-1.5 rounded-lg border border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100 disabled:opacity-50"
        >
          <RefreshCw size={12} className={retrying ? "animate-spin" : ""} />
          Retry failed steps
        </button>
      )}
    </div>
  );
}
