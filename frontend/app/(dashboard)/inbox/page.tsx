"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  operatorApi,
  clientsApi,
  Client,
  InboxStatus,
  InboxPriority,
  OperatorInboxAiSuggestion,
  OperatorInboxItem,
  normalizeList,
} from "@/lib/api";
import { cn, INBOX_PRIORITY_CONFIG } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { format, parseISO } from "date-fns";
import {
  ExternalLink,
  Inbox,
  Layers,
  Plus,
  RotateCcw,
  ScanSearch,
  Sparkles,
  X,
  MessageSquare,
  ListTodo,
} from "lucide-react";
import toast from "react-hot-toast";

const STATUS_TABS: { value: InboxStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "new", label: "New" },
  { value: "used", label: "Used" },
  { value: "ignored", label: "Ignored" },
];

const SMART_FILTERS = [
  { key: "high_priority", label: "High priority" },
  { key: "needs_action", label: "Needs action" },
  { key: "auto_drafted", label: "Auto drafted" },
  { key: "grouped", label: "Grouped" },
] as const;

type SmartFilterKey = (typeof SMART_FILTERS)[number]["key"];

const STATUS_STYLE: Record<InboxStatus, string> = {
  new: "bg-sky-100 text-sky-800 border-sky-200",
  used: "bg-gray-100 text-gray-600 border-gray-200",
  ignored: "bg-stone-100 text-stone-500 border-stone-200",
};

const INTENT_LABEL: Record<string, string> = {
  create_post: "Create post",
  edit_existing: "Edit existing",
  schedule_post: "Schedule post",
  ask_question: "Question",
  unclear: "Unclear",
};

const ACCOUNT_MANAGER_INTENT_LABEL: Record<string, string> = {
  new_content_request: "New content",
  change_request: "Change request",
  media_upload: "Media upload",
  schedule_request: "Schedule",
  question: "Question",
  complaint: "Complaint",
  pricing_billing: "Pricing / billing",
  unclear: "Unclear",
};

function formatMediaSelection(sel: OperatorInboxAiSuggestion["media_selection"]): string {
  const parts: string[] = [];
  if (sel.summary) parts.push(sel.summary);
  if (sel.use_all_media) parts.push("All media");
  if (sel.photo_ordinals?.length) parts.push(`Photos #${sel.photo_ordinals.join(", #")}`);
  if (sel.video_ordinals?.length) parts.push(`Videos #${sel.video_ordinals.join(", #")}`);
  if (sel.buffer_ids?.length) parts.push(`${sel.buffer_ids.length} file(s) by ID`);
  if (sel.use_client_text_as_description) parts.push("Client text → description");
  return parts.length ? parts.join(" · ") : "Default selection";
}

function InboxCard({
  item,
  busy,
  selected,
  onToggleSelect,
  suggestion,
  suggestLoading,
  smartLoading,
  onSuggest,
  onSmartAnalyze,
  onApplySuggestion,
  onCreate,
  onCreateFromGroup,
  onIgnore,
  onRestore,
}: {
  item: OperatorInboxItem;
  busy: boolean;
  selected: boolean;
  onToggleSelect: () => void;
  suggestion?: OperatorInboxAiSuggestion | null;
  suggestLoading: boolean;
  smartLoading: boolean;
  onSuggest: () => void;
  onSmartAnalyze: () => void;
  onApplySuggestion: () => void;
  onCreate: () => void;
  onCreateFromGroup: () => void;
  onIgnore: () => void;
  onRestore: () => void;
}) {
  const isNew = item.status === "new";
  const isIgnored = item.status === "ignored";
  const hasLink = !!item.linked_content_id;
  const isGrouped = (item.group_message_count ?? 1) > 1;
  const priorityCfg = item.priority
    ? INBOX_PRIORITY_CONFIG[item.priority]
    : null;

  return (
    <div
      className={cn(
        "card p-4 flex flex-col gap-3",
        isNew && "ring-1 ring-sky-200",
        selected && "ring-2 ring-brand-400",
      )}
    >
      <div className="flex items-start gap-2">
        {isNew && !hasLink && (
          <input
            type="checkbox"
            className="mt-1 rounded border-gray-300"
            checked={selected}
            onChange={onToggleSelect}
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-gray-900">{item.company_name}</p>
              {item.telegram_group_title && (
                <p className="text-xs text-gray-500">{item.telegram_group_title}</p>
              )}
            </div>
            <div className="flex flex-col items-end gap-1 shrink-0">
              {priorityCfg && (
                <span
                  className={cn(
                    "text-[10px] px-2 py-0.5 rounded-full border font-medium",
                    priorityCfg.color,
                  )}
                >
                  {priorityCfg.label}
                </span>
              )}
              {item.auto_drafted && (
                <span className="text-[10px] px-2 py-0.5 rounded-full border font-medium bg-emerald-100 text-emerald-800 border-emerald-200">
                  Auto drafted
                </span>
              )}
              {item.related_to_media_request && (
                <span className="text-[10px] px-2 py-0.5 rounded-full border font-medium bg-sky-100 text-sky-800 border-sky-200">
                  Related to media request
                </span>
              )}
              {isGrouped && (
                <span className="text-[10px] px-2 py-0.5 rounded-full border font-medium bg-indigo-100 text-indigo-800 border-indigo-200">
                  Grouped · {item.group_message_count} msgs
                </span>
              )}
              <span
                className={cn(
                  "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
                  STATUS_STYLE[item.status],
                )}
              >
                {item.status}
              </span>
            </div>
          </div>
        </div>
      </div>

      {item.account_manager_summary && (
        <div className="rounded-lg border border-violet-200 bg-violet-50 p-2.5 text-xs text-violet-900">
          <p className="font-medium text-violet-950 mb-1 flex items-center gap-1 flex-wrap">
            <MessageSquare size={11} />
            Account Manager
            {item.account_manager_intent && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-white border border-violet-200 font-normal">
                {ACCOUNT_MANAGER_INTENT_LABEL[item.account_manager_intent] ?? item.account_manager_intent}
              </span>
            )}
            {item.account_manager_priority && (
              <span
                className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded border font-normal capitalize",
                  INBOX_PRIORITY_CONFIG[item.account_manager_priority]?.color,
                )}
              >
                {item.account_manager_priority}
              </span>
            )}
          </p>
          <p className="text-violet-900">{item.account_manager_summary}</p>
          {item.account_manager_recommended_action && (
            <p className="mt-1.5 text-violet-800">
              <span className="font-medium">Recommended: </span>
              {item.account_manager_recommended_action}
            </p>
          )}
          {item.account_manager_related_content_id && (
            <Link
              href={`/content/${item.account_manager_related_content_id}`}
              className="inline-flex items-center gap-1 mt-1.5 text-[11px] text-violet-700 hover:text-violet-900"
            >
              Related content <ExternalLink size={10} />
            </Link>
          )}
          <p className="mt-1.5 text-[10px] text-violet-700">
            {item.account_manager_reply_sent
              ? `AI reply sent${item.account_manager_reply_text ? `: “${item.account_manager_reply_text.slice(0, 80)}${item.account_manager_reply_text.length > 80 ? "…" : ""}”` : ""}`
              : "AI reply not sent"}
          </p>
          {item.operator_task_id && (
            <Link
              href="/tasks"
              className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-medium text-indigo-800 hover:text-indigo-950 bg-white/80 border border-indigo-200 rounded px-2 py-1"
            >
              <ListTodo size={11} />
              Task: {item.operator_task_title ?? "View task"}
              {item.operator_task_status && (
                <span className="text-[10px] font-normal capitalize text-indigo-600">
                  · {item.operator_task_status.replace("_", " ")}
                </span>
              )}
            </Link>
          )}
        </div>
      )}

      {item.ai_summary && !item.account_manager_summary && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5 text-xs text-slate-800">
          <p className="font-medium text-slate-900 mb-0.5 flex items-center gap-1">
            <ScanSearch size={11} /> AI summary
          </p>
          <p>{item.ai_summary}</p>
        </div>
      )}

      {item.message_text && !item.ai_summary && !item.account_manager_summary && (
        <p className="text-sm text-gray-700 whitespace-pre-wrap line-clamp-4">
          {item.message_text}
        </p>
      )}

      {(item.suggested_platforms?.length ?? 0) > 0 && (
        <p className="text-[11px] text-gray-600">
          <span className="font-medium">Platforms:</span>{" "}
          {item.suggested_platforms!.join(", ")}
        </p>
      )}

      {item.suggested_publish_date && (
        <p className="text-[11px] text-purple-700">
          <span className="font-medium">Suggested publish:</span>{" "}
          {format(parseISO(item.suggested_publish_date), "MMM d, yyyy HH:mm")} UTC
        </p>
      )}

      {item.detected_offer && (
        <p className="text-[11px] text-orange-800 bg-orange-50 border border-orange-100 rounded px-2 py-1">
          Offer: {item.detected_offer}
        </p>
      )}

      {item.detected_deadline && (
        <p className="text-[11px] text-red-700">
          Deadline: {item.detected_deadline}
        </p>
      )}

      {item.media_previews.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {item.media_previews.map((m) =>
            m.url ? (
              <div
                key={m.buffer_id}
                className="w-16 h-16 rounded-lg overflow-hidden border border-gray-200 bg-gray-50"
              >
                {m.media_type === "video" ? (
                  <video src={m.url} className="w-full h-full object-cover" />
                ) : (
                  <img src={m.url} alt="" className="w-full h-full object-cover" />
                )}
              </div>
            ) : null,
          )}
        </div>
      )}

      <p className="text-[11px] text-gray-400">
        {isGrouped
          ? `${item.group_media_count ?? item.media_count} media · ${item.group_message_count} messages`
          : `${item.media_count} media`}
        {" · "}
        {format(parseISO(item.message_at), "MMM d, yyyy HH:mm")}
        {item.detected_language && ` · ${item.detected_language}`}
      </p>

      {suggestion && (
        <div className="rounded-lg border border-violet-200 bg-violet-50/80 p-3 text-xs space-y-1.5">
          <p className="font-semibold text-violet-900 flex items-center gap-1">
            <Sparkles size={12} /> AI suggestion
            {suggestion.source && (
              <span className="font-normal text-violet-600">({suggestion.source})</span>
            )}
          </p>
          <p>
            <span className="text-violet-700">Intent:</span>{" "}
            {INTENT_LABEL[suggestion.intent] ?? suggestion.intent}
          </p>
          <p>
            <span className="text-violet-700">Action:</span> {suggestion.suggested_action}
          </p>
          {suggestion.suggested_platforms.length > 0 && (
            <p>
              <span className="text-violet-700">Platforms:</span>{" "}
              {suggestion.suggested_platforms.join(", ")}
            </p>
          )}
          {suggestion.suggested_schedule && (
            <p>
              <span className="text-violet-700">Schedule:</span>{" "}
              {format(parseISO(suggestion.suggested_schedule), "MMM d, yyyy HH:mm")} UTC
            </p>
          )}
          <p>
            <span className="text-violet-700">Media:</span>{" "}
            {formatMediaSelection(suggestion.media_selection)}
          </p>
          <p className="text-violet-800/90 italic">{suggestion.reason}</p>
        </div>
      )}

      <div className="flex flex-wrap gap-2 pt-1 border-t border-gray-100">
        {hasLink && (
          <Link
            href={`/content/${item.linked_content_id}`}
            className="btn-secondary text-xs py-1"
          >
            <ExternalLink size={12} /> Open content
          </Link>
        )}
        {isNew && !hasLink && (
          <>
            <button
              type="button"
              className="btn-secondary text-xs py-1"
              disabled={busy || smartLoading}
              onClick={onSmartAnalyze}
            >
              <ScanSearch size={12} />
              {smartLoading ? "Analyzing…" : "Smart analyze"}
            </button>
            <button
              type="button"
              className="btn-secondary text-xs py-1"
              disabled={busy || suggestLoading}
              onClick={onSuggest}
            >
              <Sparkles size={12} />
              {suggestLoading ? "Suggesting…" : "AI Suggest"}
            </button>
            {suggestion &&
              suggestion.intent !== "ask_question" &&
              suggestion.intent !== "unclear" &&
              (suggestion.intent !== "edit_existing" ||
                !!suggestion.active_content_id) && (
                <button
                  type="button"
                  className="btn-primary text-xs py-1"
                  disabled={busy}
                  onClick={onApplySuggestion}
                >
                  <Sparkles size={12} /> Apply suggestion
                </button>
              )}
            {isGrouped && (
              <button
                type="button"
                className="btn-primary text-xs py-1"
                disabled={busy}
                onClick={onCreateFromGroup}
              >
                <Layers size={12} /> Create from group
              </button>
            )}
            <button
              type="button"
              className="btn-primary text-xs py-1"
              disabled={busy}
              onClick={onCreate}
            >
              <Plus size={12} /> Create content
            </button>
            <button
              type="button"
              className="btn-secondary text-xs py-1"
              disabled={busy}
              onClick={onIgnore}
            >
              <X size={12} /> Ignore
            </button>
          </>
        )}
        {isIgnored && !hasLink && (
          <button
            type="button"
            className="btn-secondary text-xs py-1"
            disabled={busy}
            onClick={onRestore}
          >
            <RotateCcw size={12} /> Restore
          </button>
        )}
      </div>
    </div>
  );
}

export default function InboxPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<InboxStatus | "all">("new");
  const [clientFilter, setClientFilter] = useState<string>("");
  const [smartFilters, setSmartFilters] = useState<Set<SmartFilterKey>>(new Set());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [busyId, setBusyId] = useState<string | null>(null);
  const [suggestBusyId, setSuggestBusyId] = useState<string | null>(null);
  const [smartBusyId, setSmartBusyId] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<
    Record<string, OperatorInboxAiSuggestion>
  >({});

  const listParams = useMemo(
    () => ({
      status: statusFilter === "all" ? undefined : statusFilter,
      client_id: clientFilter || undefined,
      priority: smartFilters.has("high_priority") ? ("high" as InboxPriority) : undefined,
      needs_action: smartFilters.has("needs_action") ? true : undefined,
      auto_drafted: smartFilters.has("auto_drafted") ? true : undefined,
      grouped: smartFilters.has("grouped") ? true : undefined,
      limit: 100,
    }),
    [statusFilter, clientFilter, smartFilters],
  );

  const { data: clientsData } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list().then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clientsData);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["operator-inbox", listParams],
    queryFn: () => operatorApi.listInbox(listParams).then((r) => r.data),
    refetchInterval: 20_000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["operator-inbox"] });
    qc.invalidateQueries({ queryKey: ["content"] });
  };

  const toggleSmartFilter = (key: SmartFilterKey) => {
    setSmartFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const createMutation = useMutation({
    mutationFn: ({ id, fromGroup }: { id: string; fromGroup?: boolean }) =>
      operatorApi.createContent(id, fromGroup),
    onMutate: ({ id }) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (res) => {
      toast.success(res.data.message);
      if (res.data.content_id) invalidate();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(
        typeof err.response?.data?.detail === "string"
          ? err.response.data.detail
          : "Create content failed",
      );
    },
  });

  const ignoreMutation = useMutation({
    mutationFn: (id: string) => operatorApi.ignore(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (res) => {
      toast.success(res.data.message);
      invalidate();
    },
    onError: () => toast.error("Ignore failed"),
  });

  const suggestMutation = useMutation({
    mutationFn: (id: string) => operatorApi.aiSuggest(id),
    onMutate: (id) => setSuggestBusyId(id),
    onSettled: () => setSuggestBusyId(null),
    onSuccess: (res, id) => {
      setSuggestions((prev) => ({ ...prev, [id]: res.data.suggestion }));
      toast.success("AI suggestion ready");
    },
    onError: () => toast.error("AI suggest failed"),
  });

  const smartAnalyzeMutation = useMutation({
    mutationFn: (id: string) => operatorApi.smartAnalyze(id),
    onMutate: (id) => setSmartBusyId(id),
    onSettled: () => setSmartBusyId(null),
    onSuccess: () => {
      toast.success("Smart analysis saved");
      invalidate();
    },
    onError: () => toast.error("Smart analyze failed"),
  });

  const groupMutation = useMutation({
    mutationFn: (ids: string[]) => operatorApi.groupInbox(ids),
    onSuccess: (res) => {
      toast.success(res.data.message);
      setSelectedIds(new Set());
      invalidate();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(
        typeof err.response?.data?.detail === "string"
          ? err.response.data.detail
          : "Group failed",
      );
    },
  });

  const applySuggestionMutation = useMutation({
    mutationFn: (id: string) => operatorApi.applyAiSuggestion(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (res, id) => {
      toast.success(res.data.message);
      if (res.data.content_id) {
        setSuggestions((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
        invalidate();
      }
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(
        typeof err.response?.data?.detail === "string"
          ? err.response.data.detail
          : "Apply suggestion failed",
      );
    },
  });

  const restoreMutation = useMutation({
    mutationFn: (id: string) => operatorApi.restore(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (res) => {
      toast.success(res.data.message);
      invalidate();
    },
    onError: () => toast.error("Restore failed"),
  });

  const counts = data?.counts ?? {};

  useEffect(() => {
    const inboxItems = normalizeList(data);
    if (!inboxItems.length) return;
    setSuggestions((prev) => {
      const next = { ...prev };
      for (const item of inboxItems) {
        if (item.ai_suggestion && !next[item.id]) {
          next[item.id] = item.ai_suggestion;
        }
      }
      return next;
    });
  }, [data]);

  const tabCounts = useMemo(
    () => ({
      all: (counts.new ?? 0) + (counts.used ?? 0) + (counts.ignored ?? 0),
      new: counts.new ?? 0,
      used: counts.used ?? 0,
      ignored: counts.ignored ?? 0,
    }),
    [counts],
  );

  const selectedList = Array.from(selectedIds);

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Inbox size={20} className="text-brand-600" />
            Inbox
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            AI operator workspace — analyze, group, and prepare client materials.
          </p>
        </div>
        <div className="flex gap-2">
          {selectedList.length >= 2 && (
            <button
              type="button"
              className="btn-primary text-xs"
              disabled={groupMutation.isPending}
              onClick={() => groupMutation.mutate(selectedList)}
            >
              <Layers size={12} />
              Group selected ({selectedList.length})
            </button>
          )}
          <button
            type="button"
            className="btn-secondary text-xs"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            Refresh
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setStatusFilter(tab.value)}
            className={cn(
              "text-xs px-3 py-1.5 rounded-full border transition-colors",
              statusFilter === tab.value
                ? "bg-brand-600 text-white border-brand-600"
                : "bg-white text-gray-600 border-gray-200 hover:border-gray-300",
            )}
          >
            {tab.label}
            <span className="ml-1 opacity-80">
              ({tabCounts[tab.value as keyof typeof tabCounts] ?? 0})
            </span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        {SMART_FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => toggleSmartFilter(f.key)}
            className={cn(
              "text-xs px-3 py-1.5 rounded-full border transition-colors",
              smartFilters.has(f.key)
                ? "bg-indigo-600 text-white border-indigo-600"
                : "bg-white text-gray-600 border-gray-200 hover:border-gray-300",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="mb-5">
        <label className="label text-xs">Filter by client</label>
        <select
          className="input max-w-xs text-sm"
          value={clientFilter}
          onChange={(e) => setClientFilter(e.target.value)}
        >
          <option value="">All clients</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>
              {c.company_name}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <LoadingState message="Loading inbox…" />
      ) : isError ? (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load inbox"}
          onRetry={() => refetch()}
        />
      ) : !normalizeList(data).length ? (
        <EmptyState title="No items in this view" description="Try another filter or check back later." />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {normalizeList(data).map((item) => (
            <InboxCard
              key={item.id}
              item={item}
              busy={busyId === item.id}
              selected={selectedIds.has(item.id)}
              onToggleSelect={() => toggleSelect(item.id)}
              suggestion={suggestions[item.id]}
              suggestLoading={suggestBusyId === item.id}
              smartLoading={smartBusyId === item.id}
              onSuggest={() => suggestMutation.mutate(item.id)}
              onSmartAnalyze={() => smartAnalyzeMutation.mutate(item.id)}
              onApplySuggestion={() => applySuggestionMutation.mutate(item.id)}
              onCreate={() => createMutation.mutate({ id: item.id })}
              onCreateFromGroup={() =>
                createMutation.mutate({ id: item.id, fromGroup: true })
              }
              onIgnore={() => ignoreMutation.mutate(item.id)}
              onRestore={() => restoreMutation.mutate(item.id)}
            />
          ))}
        </div>
      )}

      {data && data.total > data.items.length && (
        <p className="text-xs text-gray-400 mt-4 text-center">
          Showing {data.items.length} of {data.total}
        </p>
      )}
    </div>
  );
}
