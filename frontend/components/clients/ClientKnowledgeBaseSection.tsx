"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Brain, Pencil, Plus, Sparkles, Trash2, X } from "lucide-react";
import toast from "react-hot-toast";
import {
  clientKnowledgeBaseApi,
  ClientKnowledgeBaseEntry,
  KbImportance,
  KbSection,
  normalizeList,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const SECTION_LABELS: Record<KbSection, string> = {
  company_profile: "Company profile",
  products_services: "Products & services",
  pricing: "Pricing",
  target_audience: "Target audience",
  tone_style: "Tone & style",
  faq: "FAQ",
  past_campaigns: "Past campaigns",
  do_not_say: "Do not say",
  competitors: "Competitors",
  notes: "Notes",
};

const IMPORTANCE_STYLE: Record<KbImportance, string> = {
  high: "bg-red-50 text-red-700 border-red-200",
  medium: "bg-amber-50 text-amber-800 border-amber-200",
  low: "bg-gray-50 text-gray-600 border-gray-200",
};

const SOURCE_LABELS: Record<string, string> = {
  manual: "Manual",
  telegram: "Telegram",
  content: "Content",
  ai_summary: "AI summary",
};

interface Props {
  clientId: string;
}

type FormState = {
  section: KbSection;
  title: string;
  content: string;
  importance: KbImportance;
};

const EMPTY_FORM: FormState = {
  section: "notes",
  title: "",
  content: "",
  importance: "medium",
};

function EntryForm({
  initial,
  onSave,
  onCancel,
  busy,
}: {
  initial: FormState;
  onSave: (data: FormState) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const [form, setForm] = useState(initial);
  return (
    <div className="rounded-lg border border-brand-200 bg-brand-50/40 p-3 space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="block col-span-2 sm:col-span-1">
          <span className="text-[10px] font-medium text-gray-500">Section</span>
          <select
            className="input text-xs mt-0.5 w-full"
            value={form.section}
            onChange={(e) => setForm((f) => ({ ...f, section: e.target.value as KbSection }))}
          >
            {(Object.keys(SECTION_LABELS) as KbSection[]).map((s) => (
              <option key={s} value={s}>{SECTION_LABELS[s]}</option>
            ))}
          </select>
        </label>
        <label className="block col-span-2 sm:col-span-1">
          <span className="text-[10px] font-medium text-gray-500">Importance</span>
          <select
            className="input text-xs mt-0.5 w-full"
            value={form.importance}
            onChange={(e) => setForm((f) => ({ ...f, importance: e.target.value as KbImportance }))}
          >
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>
      </div>
      <label className="block">
        <span className="text-[10px] font-medium text-gray-500">Title</span>
        <input
          className="input text-xs mt-0.5 w-full"
          value={form.title}
          onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
          placeholder="Short label"
        />
      </label>
      <label className="block">
        <span className="text-[10px] font-medium text-gray-500">Content</span>
        <textarea
          className="input text-xs mt-0.5 w-full min-h-[80px]"
          value={form.content}
          onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
          placeholder="Facts AI should remember about this client"
        />
      </label>
      <div className="flex gap-2 justify-end">
        <button type="button" className="btn-secondary text-xs" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={busy || !form.title.trim() || !form.content.trim()}
          onClick={() => onSave(form)}
        >
          Save
        </button>
      </div>
    </div>
  );
}

function EntryCard({
  entry,
  onEdit,
  onDelete,
}: {
  entry: ClientKnowledgeBaseEntry;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="rounded-lg border border-gray-100 bg-white p-3">
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">{entry.title}</p>
          <div className="flex flex-wrap gap-1 mt-1">
            <span className={cn("text-[10px] px-1.5 py-0.5 rounded border font-medium capitalize", IMPORTANCE_STYLE[entry.importance])}>
              {entry.importance}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
              {SOURCE_LABELS[entry.source] ?? entry.source}
            </span>
          </div>
        </div>
        <div className="flex gap-1 shrink-0">
          <button type="button" className="p-1 text-gray-400 hover:text-gray-700" onClick={onEdit}>
            <Pencil size={13} />
          </button>
          <button type="button" className="p-1 text-gray-400 hover:text-red-600" onClick={onDelete}>
            <Trash2 size={13} />
          </button>
        </div>
      </div>
      <p className="text-xs text-gray-600 whitespace-pre-wrap line-clamp-4">{entry.content}</p>
      <p className="text-[10px] text-gray-400 mt-2">
        Updated {format(parseISO(entry.updated_at), "MMM d, yyyy HH:mm")}
      </p>
    </div>
  );
}

export function ClientKnowledgeBaseSection({ clientId }: Props) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["client-kb", clientId],
    queryFn: () => clientKnowledgeBaseApi.list(clientId).then((r) => r.data),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["client-kb", clientId] });

  const summarizeMutation = useMutation({
    mutationFn: () => clientKnowledgeBaseApi.aiSummarize(clientId),
    onSuccess: (res) => {
      toast.success(res.data.message);
      invalidate();
    },
    onError: () => toast.error("AI summarize failed"),
  });

  const createMutation = useMutation({
    mutationFn: (form: FormState) =>
      clientKnowledgeBaseApi.create(clientId, { ...form, source: "manual" }),
    onSuccess: () => {
      toast.success("Entry added");
      setAdding(false);
      invalidate();
    },
    onError: () => toast.error("Failed to add entry"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, form }: { id: string; form: FormState }) =>
      clientKnowledgeBaseApi.update(clientId, id, form),
    onSuccess: () => {
      toast.success("Entry updated");
      setEditingId(null);
      invalidate();
    },
    onError: () => toast.error("Failed to update entry"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => clientKnowledgeBaseApi.delete(clientId, id),
    onSuccess: () => {
      toast.success("Entry deleted");
      invalidate();
    },
    onError: () => toast.error("Failed to delete entry"),
  });

  const items = normalizeList<ClientKnowledgeBaseEntry>(data);

  const grouped = useMemo(() => {
    const map = new Map<KbSection, ClientKnowledgeBaseEntry[]>();
    for (const s of Object.keys(SECTION_LABELS) as KbSection[]) {
      map.set(s, []);
    }
    for (const item of items) {
      const list = map.get(item.section) ?? [];
      list.push(item);
      map.set(item.section, list);
    }
    return map;
  }, [items]);

  const editingEntry = editingId ? items.find((i) => i.id === editingId) : null;

  return (
    <div className="card p-5 mb-5">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Brain size={16} className="text-brand-600" />
            AI Knowledge Base
          </h2>
          <p className="text-xs text-gray-500 mt-1 max-w-xl">
            This memory is used by AI when generating content, plans, replies, and media requests.
            It supplements the brand profile — it does not replace it.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-secondary text-xs"
            disabled={summarizeMutation.isPending}
            onClick={() => summarizeMutation.mutate()}
          >
            <Sparkles size={13} className={summarizeMutation.isPending ? "animate-pulse" : ""} />
            {summarizeMutation.isPending ? "Summarizing…" : "AI summarize client knowledge"}
          </button>
          {!adding && (
            <button type="button" className="btn-primary text-xs" onClick={() => setAdding(true)}>
              <Plus size={13} /> Add entry
            </button>
          )}
        </div>
      </div>

      {adding && (
        <div className="mb-4">
          <EntryForm
            initial={EMPTY_FORM}
            busy={createMutation.isPending}
            onCancel={() => setAdding(false)}
            onSave={(form) => createMutation.mutate(form)}
          />
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-gray-400">Loading knowledge base…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-gray-500 py-4 text-center border border-dashed border-gray-200 rounded-lg">
          No knowledge entries yet. Add manually or run AI summarize.
        </p>
      ) : (
        <div className="space-y-5">
          {(Object.keys(SECTION_LABELS) as KbSection[]).map((section) => {
            const sectionItems = grouped.get(section) ?? [];
            if (sectionItems.length === 0) return null;
            return (
              <div key={section}>
                <h3 className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-2">
                  {SECTION_LABELS[section]}
                  <span className="text-[10px] font-normal text-gray-400">({sectionItems.length})</span>
                </h3>
                <div className="grid gap-2 sm:grid-cols-2">
                  {sectionItems.map((entry) =>
                    editingId === entry.id ? (
                      <EntryForm
                        key={entry.id}
                        initial={{
                          section: entry.section,
                          title: entry.title,
                          content: entry.content,
                          importance: entry.importance,
                        }}
                        busy={updateMutation.isPending}
                        onCancel={() => setEditingId(null)}
                        onSave={(form) => updateMutation.mutate({ id: entry.id, form })}
                      />
                    ) : (
                      <EntryCard
                        key={entry.id}
                        entry={entry}
                        onEdit={() => setEditingId(entry.id)}
                        onDelete={() => {
                          if (confirm(`Delete "${entry.title}"?`)) {
                            deleteMutation.mutate(entry.id);
                          }
                        }}
                      />
                    ),
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {editingEntry && editingId && !grouped.get(editingEntry.section)?.some((e) => e.id === editingId) && (
        <button type="button" className="text-xs text-gray-400 mt-2" onClick={() => setEditingId(null)}>
          <X size={12} className="inline" /> Close editor
        </button>
      )}
    </div>
  );
}
