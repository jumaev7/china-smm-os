"use client";

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2, Play, ShieldAlert, Terminal } from "lucide-react";
import toast from "react-hot-toast";
import {
  aiCommandApi,
  AiCommandActionResult,
  AiCommandHistoryItem,
  AiCommandPlanResult,
  normalizeList,
} from "@/lib/api";
import { buildAiCommandPayload, useAiCommandContext } from "@/lib/useAiCommandContext";
import { cn } from "@/lib/utils";
import { EmptyState, LoadingState } from "@/components/ui/PageStates";

function renderValue(value: unknown): ReactNode {
  if (value == null) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

const EXAMPLES = [
  "Create a campaign for IT Progress for June with 10 draft posts about solar panels",
  "Find buyers for this product and create follow-up tasks",
  "Run audit and create tasks for critical issues",
  "show hot leads",
  "show neglected leads",
  "score all leads",
  "Create a landing page draft for this product",
  "Create CRM lead from this message: Ali from Tashkent, interested in solar inverters",
];

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

function ActionStatus({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "text-[10px] px-1.5 py-0.5 rounded capitalize",
        status === "completed"
          ? "bg-emerald-100 text-emerald-800"
          : status === "failed"
            ? "bg-red-100 text-red-800"
            : status === "skipped"
              ? "bg-gray-100 text-gray-500"
              : "bg-gray-100 text-gray-600",
      )}
    >
      {status}
    </span>
  );
}

export default function AiCommandCenterPage() {
  const qc = useQueryClient();
  const ctx = useAiCommandContext();
  const [command, setCommand] = useState("");
  const [plan, setPlan] = useState<AiCommandPlanResult | null>(null);
  const [results, setResults] = useState<AiCommandActionResult[] | null>(null);
  const [execStatus, setExecStatus] = useState<string | null>(null);

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ["ai-command-history"],
    queryFn: () => aiCommandApi.history({ limit: 20 }).then((r) => r.data),
  });

  const planMutation = useMutation({
    mutationFn: () =>
      aiCommandApi.plan({ command, ...buildAiCommandPayload(ctx) }).then((r) => r.data),
    onSuccess: (data) => {
      setPlan(data);
      setResults(null);
      setExecStatus(null);
      toast.success("Action plan generated — review and confirm");
    },
    onError: (err: Error) => toast.error(err.message || "Planning failed"),
  });

  const executeMutation = useMutation({
    mutationFn: (commandId: string) => aiCommandApi.execute(commandId).then((r) => r.data),
    onSuccess: (data) => {
      setResults(data.actions);
      setExecStatus(data.status);
      qc.invalidateQueries({ queryKey: ["ai-command-history"] });
      toast.success(data.status === "completed" ? "All actions executed" : "Execution finished with issues");
    },
    onError: (err: Error) => toast.error(err.message || "Execution failed"),
  });

  const displayActions = results ?? plan?.actions.map((a, i) => ({
    id: `plan-${i}`,
    action_type: a.action_type,
    label: a.label,
    status: "pending",
  })) ?? [];

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <Terminal size={22} className="text-violet-600" />
          AI Command Center
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Natural-language commands with admin confirmation — no auto-publish or messaging
        </p>
        {ctx.entity_type && (
          <p className="text-xs text-violet-700 mt-1">
            Page context: {ctx.entity_label ?? ctx.entity_type.replace(/_/g, " ")}
          </p>
        )}
      </div>

      <div className="card p-4 space-y-3">
        <label className="label">Command</label>
        <textarea
          className="input min-h-[100px] text-sm"
          placeholder="Describe what you want the AI sales department to do…"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary text-sm flex items-center gap-1.5"
            disabled={!command.trim() || planMutation.isPending}
            onClick={() => planMutation.mutate()}
          >
            {planMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Bot size={14} />}
            Generate plan
          </button>
        </div>
        <div>
          <p className="text-[10px] uppercase text-gray-400 mb-1.5">Examples</p>
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                className="text-[10px] px-2 py-1 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 text-left"
                onClick={() => setCommand(ex)}
              >
                {ex.length > 60 ? `${ex.slice(0, 60)}…` : ex}
              </button>
            ))}
          </div>
        </div>
      </div>

      {plan && (
        <div className="card p-4 space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-gray-900">Action plan</p>
              <p className="text-xs text-gray-600 mt-1">{plan.summary}</p>
              <p className="text-[10px] text-gray-400 mt-0.5">Intent: {plan.parsed_intent}</p>
            </div>
            <RiskBadge level={plan.risk_level} />
          </div>

          {plan.unsupported_parts.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-3 text-xs text-amber-900">
              <p className="font-semibold flex items-center gap-1 mb-1">
                <ShieldAlert size={12} />
                Unsupported / blocked parts
              </p>
              <ul className="list-disc pl-4 space-y-0.5">
                {plan.unsupported_parts.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          )}

          <ul className="space-y-2">
            {displayActions.map((action) => (
              <li
                key={action.id}
                className="flex items-start justify-between gap-2 rounded-lg border border-gray-100 p-2.5 text-sm"
              >
                <div className="min-w-0">
                  <p className="font-medium text-gray-900">{action.label}</p>
                  <p className="text-[10px] text-gray-400 capitalize">{action.action_type.replace(/_/g, " ")}</p>
                  {"result" in action && action.result != null ? (
                    <pre className="text-[10px] text-gray-500 mt-1 overflow-x-auto">
                      {String(renderValue(action.result)).slice(0, 200)}
                    </pre>
                  ) : null}
                  {"error" in action && action.error ? (
                    <p className="text-[10px] text-red-600 mt-1">{renderValue(action.error)}</p>
                  ) : null}
                </div>
                {"status" in action && <ActionStatus status={action.status} />}
              </li>
            ))}
          </ul>

          {plan.requires_confirmation && !results && (
            <button
              type="button"
              className="btn-primary w-full sm:w-auto flex items-center justify-center gap-1.5"
              disabled={executeMutation.isPending || plan.actions.length === 0}
              onClick={() => executeMutation.mutate(plan.command_id)}
            >
              {executeMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Play size={14} />
              )}
              Confirm & Execute
            </button>
          )}

          {execStatus && (
            <p className="text-xs text-gray-500">
              Command status: <span className="font-medium capitalize">{execStatus}</span>
            </p>
          )}
        </div>
      )}

      <div className="card p-4">
        <p className="text-sm font-semibold text-gray-900 mb-3">Command history</p>
        {historyLoading ? (
          <LoadingState message="Loading history…" />
        ) : normalizeList<AiCommandHistoryItem>(history).length === 0 ? (
          <EmptyState title="No commands yet" description="Generate a plan to start the audit trail." />
        ) : (
          <ul className="space-y-2">
            {normalizeList<AiCommandHistoryItem>(history).map((item) => (
              <li
                key={item.id}
                className="rounded-lg border border-gray-100 p-2.5 text-xs hover:bg-gray-50/50 cursor-pointer"
                onClick={() => {
                  setCommand(item.raw_command);
                  setPlan(null);
                  setResults(null);
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-gray-800 truncate">{item.summary || item.raw_command}</span>
                  <ActionStatus status={item.status} />
                </div>
                <p className="text-gray-500 mt-0.5 truncate">{item.raw_command}</p>
                <p className="text-gray-400 mt-0.5 tabular-nums">
                  {item.completed_count}/{item.action_count} completed
                  {item.failed_count ? ` · ${item.failed_count} failed` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
