"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import {
  Bot,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Loader2,
  Play,
  ShieldAlert,
  Sparkles,
  Terminal,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  aiCommandApi,
  AiCommandPlanResult,
  AiCommandSuggestionItem,
} from "@/lib/api";
import { buildAiCommandPayload, useAiCommandContext } from "@/lib/useAiCommandContext";
import { cn } from "@/lib/utils";

function RiskBadge({ level }: { level: string }) {
  return (
    <span
      className={cn(
        "text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase",
        level === "high"
          ? "bg-red-100 text-red-800"
          : level === "medium"
            ? "bg-amber-100 text-amber-800"
            : "bg-emerald-100 text-emerald-800",
      )}
    >
      {level} risk
    </span>
  );
}

export function ContextAiAssistant() {
  const ctx = useAiCommandContext();
  const [open, setOpen] = useState(false);
  const [command, setCommand] = useState("");
  const [plan, setPlan] = useState<AiCommandPlanResult | null>(null);
  const [suggestions, setSuggestions] = useState<AiCommandSuggestionItem[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const contextPayload = useMemo(
    () => buildAiCommandPayload(ctx),
    [
      ctx.current_page,
      ctx.entity_type,
      ctx.entity_id,
      ctx.selected_items.join(","),
      JSON.stringify(ctx.user_context_json),
    ],
  );

  const loadSuggestions = useCallback(async () => {
    setLoadingSuggestions(true);
    try {
      const { data } = await aiCommandApi.suggestions(contextPayload);
      setSuggestions(data.suggestions ?? []);
    } catch {
      setSuggestions([]);
    } finally {
      setLoadingSuggestions(false);
    }
  }, [contextPayload]);

  useEffect(() => {
    if (open) loadSuggestions();
  }, [open, loadSuggestions]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ command?: string }>).detail;
      setOpen(true);
      if (detail?.command) setCommand(detail.command);
    };
    window.addEventListener("ai-command-open", handler);
    return () => window.removeEventListener("ai-command-open", handler);
  }, []);

  const planMutation = useMutation({
    mutationFn: (cmd: string) =>
      aiCommandApi.plan({ command: cmd, ...contextPayload }).then((r) => r.data),
    onSuccess: (data) => {
      setPlan(data);
      toast.success("Plan ready — confirm before execution");
    },
    onError: (err: Error) => toast.error(err.message || "Planning failed"),
  });

  const executeMutation = useMutation({
    mutationFn: (commandId: string) => aiCommandApi.execute(commandId).then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.status === "completed" ? "Actions executed" : "Execution finished");
      setPlan(null);
      setCommand("");
    },
    onError: (err: Error) => toast.error(err.message || "Execution failed"),
  });

  const runSuggestion = (item: AiCommandSuggestionItem) => {
    if (item.kind === "link" && item.href) return;
    setCommand(item.command);
    planMutation.mutate(item.command);
  };

  const contextHint = ctx.entity_label
    ? `${ctx.entity_type?.replace(/_/g, " ")}: ${ctx.entity_label}`
    : ctx.entity_type
      ? `On ${ctx.entity_type.replace(/_/g, " ")} page`
      : null;

  return (
    <>
      <button
        type="button"
        data-keep-overlay
        aria-label="Open AI Command Assistant"
        className={cn(
          "fixed z-40 flex items-center gap-2 rounded-full shadow-lg border transition-all",
          open
            ? "right-6 bottom-6 px-4 py-2.5 bg-violet-700 border-violet-800 text-white"
            : "right-6 bottom-24 px-4 py-2.5 bg-violet-600 border-violet-700 text-white hover:bg-violet-700",
        )}
        onClick={() => setOpen((v) => !v)}
      >
        <Terminal size={16} />
        <span className="text-sm font-medium">AI Commands</span>
      </button>

      {open && (
        <div
          ref={panelRef}
          data-keep-overlay
          className="fixed z-50 right-6 bottom-36 w-[min(420px,calc(100vw-3rem))] max-h-[min(70vh,560px)] flex flex-col rounded-xl border border-gray-200 bg-white shadow-2xl overflow-hidden"
        >
          <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-gray-100 bg-violet-50/50">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                <Sparkles size={14} className="text-violet-600" />
                Context-Aware Assistant
              </p>
              {contextHint && (
                <p className="text-[10px] text-violet-700 truncate mt-0.5">{contextHint}</p>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <Link
                href="/ai-command-center"
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                title="Open full Command Center"
              >
                <ExternalLink size={14} />
              </Link>
              <button
                type="button"
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                onClick={() => setOpen(false)}
              >
                <X size={14} />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {(suggestions.length > 0 || loadingSuggestions) && (
              <div>
                <p className="text-[10px] uppercase text-gray-400 mb-1.5">Quick actions</p>
                {loadingSuggestions ? (
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <Loader2 size={12} className="animate-spin" />
                    Loading suggestions…
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {suggestions.map((item) =>
                      item.kind === "link" && item.href ? (
                        <Link
                          key={item.label}
                          href={item.href}
                          className="text-[10px] px-2 py-1 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                        >
                          {item.label}
                        </Link>
                      ) : (
                        <button
                          key={item.label}
                          type="button"
                          className="text-[10px] px-2 py-1 rounded-lg border border-violet-200 text-violet-800 hover:bg-violet-50"
                          disabled={planMutation.isPending}
                          onClick={() => runSuggestion(item)}
                        >
                          {item.label}
                        </button>
                      ),
                    )}
                  </div>
                )}
              </div>
            )}

            <div>
              <label className="text-[10px] uppercase text-gray-400">Command</label>
              <textarea
                className="input min-h-[72px] text-sm mt-1"
                placeholder={
                  ctx.entity_type === "product"
                    ? 'e.g. "Find buyers for this product"'
                    : "Describe a safe admin action…"
                }
                value={command}
                onChange={(e) => setCommand(e.target.value)}
              />
            </div>

            <button
              type="button"
              className="btn-primary w-full text-sm flex items-center justify-center gap-1.5"
              disabled={!command.trim() || planMutation.isPending}
              onClick={() => {
                setPlan(null);
                planMutation.mutate(command);
              }}
            >
              {planMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Bot size={14} />
              )}
              Generate plan
            </button>

            {plan && (
              <div className="rounded-lg border border-gray-100 p-3 space-y-2 bg-gray-50/50">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs text-gray-700">{plan.summary}</p>
                  <RiskBadge level={plan.risk_level} />
                </div>
                {plan.context_summary && (
                  <p className="text-[10px] text-violet-700">Context: {plan.context_summary}</p>
                )}
                {plan.unsupported_parts.length > 0 && (
                  <div className="text-[10px] text-amber-800 bg-amber-50 rounded p-2">
                    <ShieldAlert size={10} className="inline mr-1" />
                    {plan.unsupported_parts.join("; ")}
                  </div>
                )}
                <ul className="space-y-1">
                  {plan.actions.map((a, i) => (
                    <li key={i} className="text-[10px] text-gray-600 flex items-center gap-1">
                      <ChevronDown size={10} className="rotate-[-90deg] shrink-0" />
                      {a.label}
                    </li>
                  ))}
                </ul>
                {plan.requires_confirmation && (
                  <button
                    type="button"
                    className="btn-primary w-full text-xs flex items-center justify-center gap-1"
                    disabled={executeMutation.isPending || plan.actions.length === 0}
                    onClick={() => executeMutation.mutate(plan.command_id)}
                  >
                    {executeMutation.isPending ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Play size={12} />
                    )}
                    Confirm & Execute
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 text-[10px] text-gray-400 flex items-center gap-1">
            <ChevronUp size={10} />
            Safe actions only — confirmation required
          </div>
        </div>
      )}
    </>
  );
}
