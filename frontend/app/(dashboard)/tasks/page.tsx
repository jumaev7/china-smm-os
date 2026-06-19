"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { format, parseISO } from "date-fns";
import {
  ListTodo,
  ExternalLink,
  Play,
  CheckCircle2,
  Clock,
  XCircle,
  Inbox,
  FileText,
  Zap,
  Loader2,
  Send,
  AlertCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  tasksApi,
  OperatorTask,
  TaskStatus,
  TaskSourceType,
  TaskExecuteResponse,
  normalizeList,
} from "@/lib/api";
import { cn, INBOX_PRIORITY_CONFIG } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const KANBAN_COLUMNS: { status: TaskStatus; label: string; color: string }[] = [
  { status: "todo", label: "Todo", color: "border-sky-200 bg-sky-50/50" },
  { status: "in_progress", label: "In Progress", color: "border-indigo-200 bg-indigo-50/50" },
  { status: "waiting_client", label: "Waiting Client", color: "border-amber-200 bg-amber-50/50" },
  { status: "done", label: "Done", color: "border-emerald-200 bg-emerald-50/50" },
];

const SOURCE_LABELS: Record<TaskSourceType, string> = {
  telegram_inbox: "Telegram inbox",
  content: "Content",
  media_request: "Media request",
  client_review: "Client review",
  client_brief: "Client brief",
  manual: "Manual",
};

const CREATED_BY_LABELS: Record<string, string> = {
  ai_account_manager: "AI Account Manager",
  admin: "Admin",
  system: "System",
};

const ACTION_LABELS: Record<string, string> = {
  create_content: "Draft created",
  request_media: "Media request sent",
  edit_content: "Draft updated",
  suggest_reply: "Suggested reply ready",
};

function sourceHref(task: OperatorTask): string | null {
  if (task.source_type === "telegram_inbox" && task.source_id) {
    return `/inbox?highlight=${task.source_id}`;
  }
  if (task.source_type === "content" && task.source_id) {
    return `/content/${task.source_id}`;
  }
  if (task.source_type === "client_review" && task.source_id) {
    return `/content/${task.source_id}`;
  }
  if (task.source_type === "client_brief" && task.linked_content_id) {
    return `/content/${task.linked_content_id}`;
  }
  return null;
}

function ExecutionResultPanel({
  task,
  executeResult,
  busy,
  onSendReply,
}: {
  task: OperatorTask;
  executeResult?: TaskExecuteResponse | null;
  busy: boolean;
  onSendReply: (text?: string) => void;
}) {
  const result = executeResult ?? null;
  const stored = task.execution_result;
  const ok = result?.ok ?? task.execution_status === "success";
  const failed = task.execution_status === "failed" || result?.ok === false;
  const action = result?.action ?? stored?.action;
  const message = result?.message ?? stored?.message ?? stored?.error;
  const contentId = result?.content_id ?? stored?.content_id ?? task.linked_content_id;
  const suggestedReply = result?.suggested_reply ?? stored?.suggested_reply;
  const replySent = stored?.reply_sent;

  if (!result && !stored && !failed) return null;

  return (
    <div
      className={cn(
        "rounded-lg border p-2.5 text-xs space-y-1.5",
        failed
          ? "border-red-200 bg-red-50 text-red-900"
          : "border-teal-200 bg-teal-50 text-teal-900",
      )}
    >
      {failed && (
        <p className="font-medium flex items-center gap-1 text-red-950">
          <AlertCircle size={12} />
          Execution failed
        </p>
      )}
      {action && !failed && (
        <p className="font-medium text-teal-950">
          {ACTION_LABELS[action] ?? action}
        </p>
      )}
      {message && <p>{message}</p>}
      {contentId && (action === "create_content" || action === "edit_content" || action === "request_media") && (
        <Link
          href={`/content/${contentId}`}
          className="inline-flex items-center gap-1 text-[11px] font-medium text-brand-700 hover:text-brand-900"
        >
          <FileText size={11} />
          Open content
          <ExternalLink size={10} />
        </Link>
      )}
      {action === "request_media" && stored?.media_request_message && (
        <p className="text-[10px] text-teal-800 line-clamp-3 italic">
          “{stored.media_request_message.slice(0, 160)}
          {stored.media_request_message.length > 160 ? "…" : ""}”
        </p>
      )}
      {suggestedReply && (
        <div className="space-y-1.5 pt-1 border-t border-teal-200/60">
          <p className="font-medium text-teal-950">Suggested reply</p>
          <p className="whitespace-pre-wrap text-teal-900">{suggestedReply}</p>
          {!replySent && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onSendReply(suggestedReply)}
              className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded border border-violet-300 bg-violet-100 text-violet-900 hover:bg-violet-200 disabled:opacity-50"
            >
              {busy ? <Loader2 size={10} className="animate-spin" /> : <Send size={10} />}
              Send reply to client
            </button>
          )}
          {replySent && (
            <p className="text-[10px] text-emerald-700 font-medium">Reply sent to client</p>
          )}
        </div>
      )}
      {ok && task.executed_at && (
        <p className="text-[10px] text-teal-700/80">
          Executed {format(parseISO(task.executed_at), "MMM d, HH:mm")}
        </p>
      )}
    </div>
  );
}

function TaskCard({
  task,
  busy,
  executing,
  executeResult,
  onStart,
  onMarkDone,
  onWaitClient,
  onCancel,
  onExecute,
  onSendReply,
}: {
  task: OperatorTask;
  busy: boolean;
  executing: boolean;
  executeResult?: TaskExecuteResponse | null;
  onStart: () => void;
  onMarkDone: () => void;
  onWaitClient: () => void;
  onCancel: () => void;
  onExecute: () => void;
  onSendReply: (text?: string) => void;
}) {
  const priorityCfg = INBOX_PRIORITY_CONFIG[task.priority];
  const sourceLink = sourceHref(task);
  const isDone = task.status === "done";
  const canExecute = !isDone && task.status !== "canceled";

  return (
    <div className="card p-3 flex flex-col gap-2 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 leading-snug">{task.title}</p>
          <Link
            href={`/clients/${task.client_id}`}
            className="text-xs text-gray-500 hover:text-brand-700 truncate block"
          >
            {task.company_name ?? "Client"}
          </Link>
        </div>
        <span
          className={cn(
            "text-[10px] px-2 py-0.5 rounded-full border font-medium shrink-0",
            priorityCfg.color,
          )}
        >
          {priorityCfg.label}
        </span>
      </div>

      {task.description && (
        <p className="text-xs text-gray-600 line-clamp-3">{task.description}</p>
      )}

      <div className="flex flex-wrap gap-1.5 text-[10px] text-gray-500">
        <span className="px-1.5 py-0.5 rounded bg-gray-100 border border-gray-200">
          {SOURCE_LABELS[task.source_type]}
        </span>
        <span className="px-1.5 py-0.5 rounded bg-violet-50 border border-violet-200 text-violet-800">
          {CREATED_BY_LABELS[task.created_by] ?? task.created_by}
        </span>
        {task.due_at && (
          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-orange-50 border border-orange-200 text-orange-800">
            <Clock size={10} />
            {format(parseISO(task.due_at), "MMM d, HH:mm")}
          </span>
        )}
      </div>

      {task.linked_content_id && (
        <Link
          href={`/content/${task.linked_content_id}`}
          className="inline-flex items-center gap-1 text-[11px] text-brand-700 hover:text-brand-900"
        >
          <FileText size={11} />
          Open content
          <ExternalLink size={10} />
        </Link>
      )}

      <ExecutionResultPanel
        task={task}
        executeResult={executeResult}
        busy={busy}
        onSendReply={onSendReply}
      />

      <div className="flex flex-wrap gap-1 pt-1 border-t border-gray-100">
        {canExecute && (
          <button
            type="button"
            disabled={busy || executing}
            onClick={onExecute}
            className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded border border-teal-300 bg-teal-50 text-teal-900 hover:bg-teal-100 disabled:opacity-50 font-medium"
          >
            {executing ? (
              <Loader2 size={10} className="animate-spin" />
            ) : (
              <Zap size={10} />
            )}
            Execute
          </button>
        )}
        {!isDone && task.status !== "in_progress" && (
          <button
            type="button"
            disabled={busy || executing}
            onClick={onStart}
            className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded border border-indigo-200 bg-indigo-50 text-indigo-800 hover:bg-indigo-100 disabled:opacity-50"
          >
            <Play size={10} /> Start
          </button>
        )}
        {!isDone && (
          <button
            type="button"
            disabled={busy || executing}
            onClick={onMarkDone}
            className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded border border-emerald-200 bg-emerald-50 text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
          >
            <CheckCircle2 size={10} /> Done
          </button>
        )}
        {!isDone && task.status !== "waiting_client" && (
          <button
            type="button"
            disabled={busy || executing}
            onClick={onWaitClient}
            className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded border border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100 disabled:opacity-50"
          >
            <Clock size={10} /> Wait client
          </button>
        )}
        {!isDone && (
          <button
            type="button"
            disabled={busy || executing}
            onClick={onCancel}
            className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded border border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100 disabled:opacity-50"
          >
            <XCircle size={10} /> Cancel
          </button>
        )}
        {sourceLink && (
          <Link
            href={sourceLink}
            className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded border border-sky-200 bg-sky-50 text-sky-800 hover:bg-sky-100"
          >
            <Inbox size={10} /> Open source
          </Link>
        )}
      </div>
    </div>
  );
}

export default function TasksPage() {
  const queryClient = useQueryClient();
  const [executeResults, setExecuteResults] = useState<Record<string, TaskExecuteResponse>>({});

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["operator-tasks"],
    queryFn: () => tasksApi.list({ limit: 200 }).then((r) => r.data),
  });

  const statusMutation = useMutation({
    mutationFn: async ({
      id,
      action,
    }: {
      id: string;
      action: "start" | "markDone" | "waitClient" | "cancel";
    }) => {
      switch (action) {
        case "start":
          return tasksApi.start(id);
        case "markDone":
          return tasksApi.markDone(id);
        case "waitClient":
          return tasksApi.waitClient(id);
        case "cancel":
          return tasksApi.cancel(id);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["operator-tasks"] });
      queryClient.invalidateQueries({ queryKey: ["operator-inbox"] });
    },
    onError: (err: Error) => toast.error(err.message || "Action failed"),
  });

  const executeMutation = useMutation({
    mutationFn: (id: string) => tasksApi.execute(id).then((r) => r.data),
    onSuccess: (result) => {
      setExecuteResults((prev) => ({ ...prev, [result.task.id]: result }));
      queryClient.invalidateQueries({ queryKey: ["operator-tasks"] });
      queryClient.invalidateQueries({ queryKey: ["operator-inbox"] });
      if (result.ok) {
        toast.success(result.message);
      } else {
        toast.error(result.message || "Execution failed");
      }
    },
    onError: (err: Error) => toast.error(err.message || "Execution failed"),
  });

  const sendReplyMutation = useMutation({
    mutationFn: ({ id, text }: { id: string; text?: string }) =>
      tasksApi.sendReply(id, text).then((r) => r.data),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["operator-tasks"] });
      toast.success(result.message);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to send reply"),
  });

  const byStatus = useMemo(() => {
    const map: Record<TaskStatus, OperatorTask[]> = {
      todo: [],
      in_progress: [],
      waiting_client: [],
      done: [],
      canceled: [],
    };
    for (const task of normalizeList<OperatorTask>(data)) {
      if (task.status in map) {
        map[task.status].push(task);
      }
    }
    return map;
  }, [data]);

  const busyId =
    statusMutation.isPending
      ? statusMutation.variables?.id
      : sendReplyMutation.isPending
        ? sendReplyMutation.variables?.id
        : null;
  const executingId = executeMutation.isPending ? executeMutation.variables : null;

  if (isLoading) {
    return <LoadingState message="Loading tasks…" />;
  }

  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load tasks"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <ListTodo size={20} className="text-indigo-600" />
          Tasks
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Actionable work from Account Manager — execute safely with one click
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 items-start">
        {KANBAN_COLUMNS.map(({ status, label, color }) => (
          <div key={status} className={cn("rounded-xl border p-3 min-h-[200px]", color)}>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-800">{label}</h2>
              <span className="text-xs text-gray-500 tabular-nums">
                {byStatus[status].length}
              </span>
            </div>
            <div className="space-y-2">
              {byStatus[status].length === 0 ? (
                <p className="text-xs text-gray-400 text-center py-6">No tasks</p>
              ) : (
                byStatus[status].map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    busy={busyId === task.id}
                    executing={executingId === task.id}
                    executeResult={executeResults[task.id]}
                    onStart={() => statusMutation.mutate({ id: task.id, action: "start" })}
                    onMarkDone={() => statusMutation.mutate({ id: task.id, action: "markDone" })}
                    onWaitClient={() => statusMutation.mutate({ id: task.id, action: "waitClient" })}
                    onCancel={() => statusMutation.mutate({ id: task.id, action: "cancel" })}
                    onExecute={() => executeMutation.mutate(task.id)}
                    onSendReply={(text) => sendReplyMutation.mutate({ id: task.id, text })}
                  />
                ))
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
