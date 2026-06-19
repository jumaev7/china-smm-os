"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ArrowLeft, Bot, Loader2, MessageSquare, StickyNote, UserPlus, Link2, Send,
  Copy, Check, Briefcase, ListTodo, Sparkles, ExternalLink,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  communicationsApi,
  crmApi,
  CommunicationAiSummary,
  CommunicationCrmExtract,
  CommunicationCrmLeadPayload,
  MessageDirection,
  CHANNEL_LABELS,
  COMM_CRM_TASK_TYPES,
  CommCrmTaskType,
  normalizeList,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const DIRECTION_STYLES: Record<MessageDirection, string> = {
  inbound: "bg-white border-gray-200 ml-0 mr-8",
  outbound: "bg-sky-50 border-sky-100 ml-8 mr-0",
  draft: "bg-violet-50 border-violet-200 mx-4 border-dashed",
  internal_note: "bg-amber-50 border-amber-200 mx-4 border-dashed",
};

const LEAD_STATUSES = ["new", "contacted", "qualified", "proposal_sent", "negotiation", "won", "lost"];
const LEAD_PRIORITIES = ["high", "medium", "low"];

function extractToForm(ext: CommunicationCrmExtract): CommunicationCrmLeadPayload {
  return {
    name: ext.name ?? "",
    company: ext.company ?? "",
    phone: ext.phone ?? "",
    email: ext.email ?? "",
    telegram: ext.telegram ?? "",
    whatsapp: ext.whatsapp ?? "",
    wechat: ext.wechat ?? "",
    country: ext.country ?? "",
    language: ext.language ?? "",
    interest: ext.interest ?? "",
    urgency: ext.urgency ?? "",
    budget: ext.budget ?? "",
    next_follow_up_at: ext.next_follow_up_at ?? "",
    suggested_status: ext.suggested_status,
    suggested_priority: ext.suggested_priority,
  };
}

export default function ThreadDetailPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const [messageText, setMessageText] = useState("");
  const [senderName, setSenderName] = useState("Operator");
  const [noteMode, setNoteMode] = useState(false);
  const [aiResult, setAiResult] = useState<CommunicationAiSummary | null>(null);
  const [linkLeadId, setLinkLeadId] = useState("");
  const [showLinkLead, setShowLinkLead] = useState(false);
  const [crmForm, setCrmForm] = useState<CommunicationCrmLeadPayload | null>(null);
  const [extractDemo, setExtractDemo] = useState(false);
  const [suggestedReply, setSuggestedReply] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [taskType, setTaskType] = useState<CommCrmTaskType>("follow_up");
  const [lastActivitySync, setLastActivitySync] = useState(false);

  const { data: thread, isLoading } = useQuery({
    queryKey: ["communication-thread", id],
    queryFn: () => communicationsApi.getThread(id).then((r) => r.data),
  });

  const { data: leads } = useQuery({
    queryKey: ["crm-leads-link", thread?.client_id],
    queryFn: () =>
      crmApi.listLeads({ client_id: thread!.client_id!, limit: 100 }).then((r) => r.data),
    enabled: !!thread?.client_id && showLinkLead,
  });

  const addMessageMutation = useMutation({
    mutationFn: (direction: MessageDirection) =>
      communicationsApi.addMessage(id, {
        direction,
        sender_name: senderName.trim() || "Operator",
        message_text: messageText.trim(),
      }).then((r) => r.data),
    onSuccess: (data) => {
      setMessageText("");
      setNoteMode(false);
      setLastActivitySync(!!(data as { activity_synced?: boolean }).activity_synced);
      qc.invalidateQueries({ queryKey: ["communication-thread", id] });
      qc.invalidateQueries({ queryKey: ["communications-threads"] });
      toast.success(
        (data as { activity_synced?: boolean }).activity_synced
          ? "Message saved — CRM activity synced"
          : "Message saved",
      );
    },
    onError: (err: Error) => toast.error(err.message || "Failed to save"),
  });

  const aiMutation = useMutation({
    mutationFn: () => communicationsApi.aiSummary(id).then((r) => r.data),
    onSuccess: (data) => {
      setAiResult(data);
      toast.success("Summary generated");
    },
    onError: (err: Error) => toast.error(err.message || "AI summary failed"),
  });

  const extractMutation = useMutation({
    mutationFn: () => communicationsApi.extractCrm(id).then((r) => r.data),
    onSuccess: (data) => {
      setCrmForm(extractToForm(data));
      setExtractDemo(!!data.demo_mode);
      toast.success("CRM fields extracted — review before creating");
    },
    onError: (err: Error) => toast.error(err.message || "Extract failed"),
  });

  const createLeadMutation = useMutation({
    mutationFn: (payload: CommunicationCrmLeadPayload) =>
      communicationsApi.createLead(id, payload).then((r) => r.data),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["communication-thread", id] });
      toast.success(
        data.updated ? `Lead updated: ${data.lead_name}` : `Lead created: ${data.lead_name}`,
      );
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create/update lead"),
  });

  const linkLeadMutation = useMutation({
    mutationFn: (leadId: string) => communicationsApi.linkLead(id, leadId).then((r) => r.data),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["communication-thread", id] });
      setShowLinkLead(false);
      toast.success(`Linked to ${data.lead_name}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to link lead"),
  });

  const suggestReplyMutation = useMutation({
    mutationFn: () => communicationsApi.suggestReply(id).then((r) => r.data),
    onSuccess: (data) => {
      setSuggestedReply(data.reply_text);
      toast.success("Reply suggested — copy and send manually");
    },
    onError: (err: Error) => toast.error(err.message || "Suggest reply failed"),
  });

  const createTaskMutation = useMutation({
    mutationFn: () =>
      communicationsApi.createTask(id, { task_type: taskType }).then((r) => r.data),
    onSuccess: (data) => {
      toast.success(`Task created: ${data.title}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create task"),
  });

  const saveReplyAsNoteMutation = useMutation({
    mutationFn: (text: string) =>
      communicationsApi.addMessage(id, {
        direction: "internal_note",
        sender_name: "Operator",
        message_text: `[Suggested reply — not sent]\n\n${text}`,
      }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["communication-thread", id] });
      toast.success("Saved as internal note");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to save note"),
  });

  const copyReply = async () => {
    if (!suggestedReply) return;
    await navigator.clipboard.writeText(suggestedReply);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast.success("Copied to clipboard");
  };

  const updateCrmField = (key: keyof CommunicationCrmLeadPayload, value: string) => {
    setCrmForm((prev) => ({ ...(prev ?? {}), [key]: value }));
  };

  if (isLoading || !thread) {
    return <div className="p-6 text-sm text-gray-500">Loading thread…</div>;
  }

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <Link href="/communications" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          Communications
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">{thread.title}</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {CHANNEL_LABELS[thread.channel]}
              {thread.contact_name ? ` · ${thread.contact_name}` : ""}
              {thread.client_name ? ` · ${thread.client_name}` : ""}
            </p>
          </div>
          <span className="text-xs px-2 py-1 rounded border capitalize bg-gray-50">{thread.status}</span>
        </div>
        {thread.lead_id && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className="px-2 py-1 rounded bg-emerald-50 text-emerald-800 border border-emerald-100">
              Linked Lead: {thread.lead_name ?? thread.lead_id}
            </span>
            <Link
              href="/crm"
              className="text-brand-700 hover:text-brand-900 inline-flex items-center gap-1"
            >
              Open Lead in CRM
              <ExternalLink size={11} />
            </Link>
            {lastActivitySync && (
              <span className="text-emerald-600">Activity sync enabled</span>
            )}
          </div>
        )}
        {(thread.linked_outreach?.length ?? 0) > 0 && (
          <div className="mt-2 rounded-lg border border-indigo-100 bg-indigo-50/40 p-3 space-y-2">
            <p className="text-xs font-semibold text-indigo-950">Linked outreach</p>
            <ul className="space-y-1.5">
              {(thread.linked_outreach ?? []).map((o) => (
                <li key={o.id} className="flex items-center justify-between gap-2 text-[11px]">
                  <Link href={`/outreach/${o.id}`} className="text-indigo-900 hover:underline font-medium">
                    {o.buyer_company || o.buyer_name || "Outreach"}
                  </Link>
                  <span className="text-[9px] px-1.5 py-0.5 rounded-full border capitalize bg-white text-gray-700">
                    {o.status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* AI CRM Panel */}
      <div className="card p-4 space-y-4 border-sky-100 bg-sky-50/30">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Sparkles size={16} className="text-sky-600" />
          AI CRM Automation
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="text-xs px-3 py-1.5 rounded-lg border border-sky-200 text-sky-800 hover:bg-sky-50 flex items-center gap-1"
            disabled={extractMutation.isPending}
            onClick={() => extractMutation.mutate()}
          >
            {extractMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Briefcase size={12} />}
            Extract CRM Info
          </button>
          {thread.client_id && (
            <button
              type="button"
              className="text-xs px-3 py-1.5 rounded-lg border border-emerald-200 text-emerald-800 hover:bg-emerald-50 flex items-center gap-1"
              disabled={createLeadMutation.isPending || !crmForm}
              onClick={() => crmForm && createLeadMutation.mutate(crmForm)}
            >
              {createLeadMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <UserPlus size={12} />}
              {thread.lead_id ? "Update Lead" : "Create Lead"}
            </button>
          )}
          {thread.client_id && (
            <div className="flex items-center gap-1">
              <select
                className="input text-xs py-1.5 w-auto"
                value={taskType}
                onChange={(e) => setTaskType(e.target.value as CommCrmTaskType)}
              >
                {COMM_CRM_TASK_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
              <button
                type="button"
                className="text-xs px-3 py-1.5 rounded-lg border border-indigo-200 text-indigo-800 hover:bg-indigo-50 flex items-center gap-1"
                disabled={createTaskMutation.isPending}
                onClick={() => createTaskMutation.mutate()}
              >
                {createTaskMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <ListTodo size={12} />}
                Create Task
              </button>
            </div>
          )}
          <button
            type="button"
            className="text-xs px-3 py-1.5 rounded-lg border border-violet-200 text-violet-800 hover:bg-violet-50 flex items-center gap-1"
            disabled={suggestReplyMutation.isPending}
            onClick={() => suggestReplyMutation.mutate()}
          >
            {suggestReplyMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <MessageSquare size={12} />}
            Suggest Reply
          </button>
        </div>

        {extractDemo && (
          <p className="text-xs text-amber-700">Demo mode — heuristic extraction</p>
        )}

        {crmForm && (
          <div className="grid sm:grid-cols-2 gap-2 text-sm">
            {([
              ["name", "Name"],
              ["company", "Company"],
              ["phone", "Phone"],
              ["email", "Email"],
              ["telegram", "Telegram"],
              ["whatsapp", "WhatsApp"],
              ["wechat", "WeChat"],
              ["country", "Country"],
              ["language", "Language"],
              ["budget", "Budget"],
              ["urgency", "Urgency"],
            ] as const).map(([key, label]) => (
              <div key={key}>
                <label className="text-[10px] uppercase text-gray-400">{label}</label>
                <input
                  className="input text-sm w-full mt-0.5"
                  value={String(crmForm[key] ?? "")}
                  onChange={(e) => updateCrmField(key, e.target.value)}
                />
              </div>
            ))}
            <div className="sm:col-span-2">
              <label className="text-[10px] uppercase text-gray-400">Interest</label>
              <textarea
                className="input text-sm w-full mt-0.5 min-h-[60px]"
                value={crmForm.interest ?? ""}
                onChange={(e) => updateCrmField("interest", e.target.value)}
              />
            </div>
            <div>
              <label className="text-[10px] uppercase text-gray-400">CRM Status</label>
              <select
                className="input text-sm w-full mt-0.5"
                value={crmForm.suggested_status ?? "new"}
                onChange={(e) => updateCrmField("suggested_status", e.target.value)}
              >
                {LEAD_STATUSES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] uppercase text-gray-400">Priority</label>
              <select
                className="input text-sm w-full mt-0.5"
                value={crmForm.suggested_priority ?? "medium"}
                onChange={(e) => updateCrmField("suggested_priority", e.target.value)}
              >
                {LEAD_PRIORITIES.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {suggestedReply && (
          <div className="rounded-lg border border-violet-100 bg-white p-3 space-y-2">
            <p className="text-xs font-semibold text-gray-800">Suggested reply (not sent)</p>
            <p className="text-sm text-gray-700 whitespace-pre-wrap">{suggestedReply}</p>
            <div className="flex gap-2">
              <button
                type="button"
                className="text-xs px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 flex items-center gap-1"
                onClick={copyReply}
              >
                {copied ? <Check size={12} className="text-green-600" /> : <Copy size={12} />}
                Copy
              </button>
              <button
                type="button"
                className="text-xs px-2 py-1 rounded border border-amber-200 text-amber-800 hover:bg-amber-50"
                disabled={saveReplyAsNoteMutation.isPending}
                onClick={() => saveReplyAsNoteMutation.mutate(suggestedReply)}
              >
                Save as internal note
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="text-xs px-3 py-1.5 rounded-lg border border-violet-200 text-violet-800 hover:bg-violet-50 flex items-center gap-1"
          disabled={aiMutation.isPending}
          onClick={() => aiMutation.mutate()}
        >
          {aiMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Bot size={12} />}
          AI Summarize
        </button>
        <button
          type="button"
          className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 flex items-center gap-1"
          onClick={() => setShowLinkLead((v) => !v)}
        >
          <Link2 size={12} />
          Link CRM Lead
        </button>
        {thread.contact_id && (
          <Link
            href={`/communications/contacts/${thread.contact_id}`}
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50"
          >
            View contact
          </Link>
        )}
      </div>

      {showLinkLead && (
        <div className="card p-3 flex flex-wrap gap-2 items-end">
          <select
            className="input text-sm flex-1 min-w-[200px]"
            value={linkLeadId}
            onChange={(e) => setLinkLeadId(e.target.value)}
          >
            <option value="">Select lead…</option>
            {normalizeList(leads).map((l) => (
              <option key={l.id} value={l.id}>{l.name}{l.company ? ` — ${l.company}` : ""}</option>
            ))}
          </select>
          <button
            type="button"
            className="btn-primary text-sm"
            disabled={!linkLeadId || linkLeadMutation.isPending}
            onClick={() => linkLeadMutation.mutate(linkLeadId)}
          >
            Link
          </button>
        </div>
      )}

      {aiResult && (
        <div className="card p-4 space-y-2 text-sm bg-violet-50/50 border-violet-100">
          <p className="font-semibold text-gray-900">AI Summary</p>
          <p className="text-gray-700">{aiResult.summary}</p>
          <p><span className="font-medium text-gray-800">Next action:</span> {aiResult.next_action}</p>
          <p><span className="font-medium text-gray-800">Sentiment:</span> {aiResult.sentiment}</p>
          <p><span className="font-medium text-gray-800">Interest:</span> {aiResult.possible_lead_interest}</p>
        </div>
      )}

      <div className="space-y-3 min-h-[200px]">
        {(thread.messages ?? []).length === 0 ? (
          <p className="text-sm text-gray-500 text-center py-8">No messages yet.</p>
        ) : (
          (thread.messages ?? []).map((msg) => (
            <div
              key={msg.id}
              className={cn("rounded-lg border p-3 text-sm", DIRECTION_STYLES[msg.direction])}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-xs font-medium text-gray-800">
                  {msg.direction === "internal_note" ? "📝 Internal note" : msg.sender_name}
                </span>
                <span className="text-[10px] text-gray-400">
                  {format(parseISO(msg.created_at), "MMM d, HH:mm")}
                </span>
              </div>
              <p className="text-gray-700 whitespace-pre-wrap">{msg.message_text}</p>
            </div>
          ))
        )}
      </div>

      <div className="card p-4 space-y-3 sticky bottom-4">
        <div className="flex gap-2">
          <button
            type="button"
            className={cn(
              "text-xs px-2 py-1 rounded border",
              !noteMode ? "bg-brand-50 border-brand-200" : "border-gray-200",
            )}
            onClick={() => setNoteMode(false)}
          >
            <MessageSquare size={12} className="inline mr-1" />
            Manual message
          </button>
          <button
            type="button"
            className={cn(
              "text-xs px-2 py-1 rounded border",
              noteMode ? "bg-amber-50 border-amber-200" : "border-gray-200",
            )}
            onClick={() => setNoteMode(true)}
          >
            <StickyNote size={12} className="inline mr-1" />
            Internal note
          </button>
        </div>
        <input
          className="input text-sm w-full"
          placeholder="Sender name"
          value={senderName}
          onChange={(e) => setSenderName(e.target.value)}
        />
        <textarea
          className="input text-sm w-full min-h-[80px]"
          placeholder={noteMode ? "Internal note (not sent to client)…" : "Log outbound or inbound message manually…"}
          value={messageText}
          onChange={(e) => setMessageText(e.target.value)}
        />
        <button
          type="button"
          className="btn-primary text-sm flex items-center gap-1.5"
          disabled={!messageText.trim() || addMessageMutation.isPending}
          onClick={() =>
            addMessageMutation.mutate(noteMode ? "internal_note" : "outbound")
          }
        >
          {addMessageMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Send size={14} />
          )}
          Save {noteMode ? "note" : "message"} (manual — not sent)
        </button>
        {thread.lead_id && (
          <p className="text-[10px] text-gray-500">
            Messages on linked threads sync to CRM lead activity automatically.
          </p>
        )}
      </div>
    </div>
  );
}
