"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ArrowLeft,
  Archive,
  CheckCircle,
  CheckCircle2,
  Circle,
  Copy,
  ExternalLink,
  Link2,
  ListTodo,
  Loader2,
  MessageSquare,
  RefreshCw,
  Send,
} from "lucide-react";
import toast from "react-hot-toast";
import { communicationsApi, outreachApi, OutreachEventType, OutreachStyle, normalizeList } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";

const STYLES: OutreachStyle[] = ["formal", "friendly", "executive", "distributor"];

const WORKFLOW_STEPS = [
  { key: "draft", label: "Draft" },
  { key: "approved", label: "Approved" },
  { key: "sent", label: "Sent" },
] as const;

const EVENT_LABELS: Record<OutreachEventType, string> = {
  generated: "Generated",
  approved: "Approved",
  copied: "Copied",
  sent: "Marked sent",
  follow_up_created: "Follow-up task created",
  thread_linked: "Thread linked",
};

function defaultFollowUpDue() {
  const d = new Date();
  d.setDate(d.getDate() + 3);
  return format(d, "yyyy-MM-dd'T'HH:mm");
}

export default function OutreachDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const qc = useQueryClient();
  const [regenStyle, setRegenStyle] = useState<OutreachStyle>("formal");
  const [followUpDue, setFollowUpDue] = useState(defaultFollowUpDue);
  const [linkThreadId, setLinkThreadId] = useState("");
  const [showLinkThread, setShowLinkThread] = useState(false);

  const { data: msg, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["outreach", id],
    queryFn: () => outreachApi.get(id).then((r) => r.data),
  });

  const { data: threadsData } = useQuery({
    queryKey: ["communications-threads", "outreach-link", msg?.lead_id, msg?.client_id],
    queryFn: () =>
      communicationsApi
        .listThreads({
          lead_id: msg!.lead_id!,
          client_id: msg!.client_id,
          limit: 50,
        })
        .then((r) => r.data),
    enabled: showLinkThread && !!msg?.lead_id,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["outreach", id] });
    qc.invalidateQueries({ queryKey: ["outreach"] });
  };

  const updateMutation = useMutation({
    mutationFn: (data: Parameters<typeof outreachApi.update>[1]) =>
      outreachApi.update(id, data).then((r) => r.data),
    onSuccess: () => {
      invalidate();
      toast.success("Outreach updated");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  const regenMutation = useMutation({
    mutationFn: () => outreachApi.regenerate(id, { style: regenStyle }).then((r) => r.data),
    onSuccess: () => {
      invalidate();
      toast.success("Message regenerated");
    },
    onError: (err: Error) => toast.error(err.message || "Regeneration failed"),
  });

  const approveMutation = useMutation({
    mutationFn: () => outreachApi.approve(id).then((r) => r.data),
    onSuccess: (data) => {
      invalidate();
      toast.success(data.message || "Outreach approved");
    },
    onError: (err: Error) => toast.error(err.message || "Approve failed"),
  });

  const markCopiedMutation = useMutation({
    mutationFn: () => outreachApi.markCopied(id).then((r) => r.data),
    onSuccess: (data) => {
      invalidate();
      toast.success(data.message || "Copy recorded");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to record copy"),
  });

  const markSentMutation = useMutation({
    mutationFn: () => outreachApi.markSent(id, { create_follow_up_task: true }).then((r) => r.data),
    onSuccess: (data) => {
      invalidate();
      toast.success(data.message || "Marked as sent");
    },
    onError: (err: Error) => toast.error(err.message || "Mark sent failed"),
  });

  const followUpMutation = useMutation({
    mutationFn: () =>
      outreachApi
        .createFollowUp(id, { due_at: new Date(followUpDue).toISOString() })
        .then((r) => r.data),
    onSuccess: (data) => {
      invalidate();
      toast.success(data.message || "Follow-up task created");
    },
    onError: (err: Error) => toast.error(err.message || "Follow-up failed"),
  });

  const linkThreadMutation = useMutation({
    mutationFn: (threadId: string) =>
      outreachApi.linkThread(id, { communication_thread_id: threadId }).then((r) => r.data),
    onSuccess: (data) => {
      invalidate();
      setShowLinkThread(false);
      toast.success(data.message || "Thread linked");
    },
    onError: (err: Error) => toast.error(err.message || "Link failed"),
  });

  const copyText = async (text: string, label: string) => {
    await navigator.clipboard.writeText(text);
    toast.success(`${label} copied`);
  };

  const copyMessage = async () => {
    if (!msg) return;
    const text = msg.subject ? `Subject: ${msg.subject}\n\n${msg.message_text}` : msg.message_text;
    await copyText(text, "Message");
  };

  if (isLoading) return <LoadingState message="Loading outreach…" className="min-h-[40vh]" />;
  if (isError || !msg) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Outreach not found"}
        onRetry={() => refetch()}
        className="min-h-[40vh]"
      />
    );
  }

  const workflowBusy =
    approveMutation.isPending ||
    markCopiedMutation.isPending ||
    markSentMutation.isPending ||
    followUpMutation.isPending ||
    linkThreadMutation.isPending;

  const statusIndex = WORKFLOW_STEPS.findIndex((s) => s.key === msg.status);
  const effectiveIndex = msg.status === "archived" ? 0 : statusIndex >= 0 ? statusIndex : 0;

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <div>
        <Link href="/outreach" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          All outreach
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
              <Send size={20} className="text-indigo-600" />
              {msg.buyer_name || msg.lead_name || "Outreach draft"}
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              {msg.buyer_company && `${msg.buyer_company} · `}
              {msg.country} · {msg.channel} · {msg.outreach_type.replace(/_/g, " ")}
            </p>
            <p className="text-[10px] text-gray-400 mt-1">
              {format(parseISO(msg.created_at), "MMM d, yyyy HH:mm")} · {msg.language.toUpperCase()}
              {msg.demo_mode && " · Demo mode"}
            </p>
          </div>
          <span
            className={cn(
              "text-xs px-2 py-1 rounded-full capitalize",
              msg.status === "approved" && "bg-emerald-100 text-emerald-800",
              msg.status === "sent" && "bg-sky-100 text-sky-800",
              msg.status === "archived" && "bg-gray-100 text-gray-500",
              msg.status === "draft" && "bg-gray-100 text-gray-700",
            )}
          >
            {msg.status}
          </span>
        </div>
      </div>

      {(msg.product_id || msg.proposal_id || msg.lead_id || msg.sales_playbook_id) && (
        <div className="flex flex-wrap gap-3 text-xs">
          {msg.sales_playbook_id && (
            <Link href={`/sales-playbooks/${msg.sales_playbook_id}`} className="text-violet-700 hover:underline">
              Playbook: {msg.sales_playbook_name || msg.sales_playbook_id.slice(0, 8)}
            </Link>
          )}
          {msg.lead_id && (
            <Link href={`/crm?lead=${msg.lead_id}`} className="text-brand-700 hover:underline">
              Lead: {msg.lead_name}
            </Link>
          )}
          {msg.product_id && (
            <Link href={`/products/${msg.product_id}`} className="text-brand-700 hover:underline">
              Product: {msg.product_name}
            </Link>
          )}
          {msg.proposal_id && (
            <Link href={`/proposals/${msg.proposal_id}`} className="text-brand-700 hover:underline">
              Proposal: {msg.proposal_title}
            </Link>
          )}
        </div>
      )}

      {/* Workflow panel */}
      {msg.status !== "archived" && (
        <div className="card p-4 space-y-4 border-indigo-100 bg-indigo-50/20">
          <p className="text-xs font-semibold text-gray-900">Outreach workflow</p>

          <div className="flex flex-wrap items-center gap-1">
            {WORKFLOW_STEPS.map((step, idx) => {
              const done = effectiveIndex > idx;
              const active = effectiveIndex === idx && msg.status !== "archived";
              return (
                <div key={step.key} className="flex items-center gap-1">
                  {idx > 0 && <span className="text-gray-300 text-[10px]">→</span>}
                  <span
                    className={cn(
                      "flex items-center gap-1 text-[10px] px-2 py-1 rounded-full border",
                      active
                        ? "border-indigo-500 bg-indigo-50 text-indigo-900 font-medium"
                        : done
                          ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                          : "border-gray-200 text-gray-500",
                    )}
                  >
                    {done && !active ? <CheckCircle2 size={10} /> : <Circle size={10} />}
                    {step.label}
                  </span>
                </div>
              );
            })}
          </div>

          <div className="grid sm:grid-cols-2 gap-2 text-[11px] text-gray-600">
            {msg.approved_at && (
              <p>Approved: {format(parseISO(msg.approved_at), "MMM d, yyyy HH:mm")}</p>
            )}
            {msg.copied_at && (
              <p>Copied: {format(parseISO(msg.copied_at), "MMM d, yyyy HH:mm")}</p>
            )}
            {msg.sent_at && (
              <p className="text-sky-700">Sent: {format(parseISO(msg.sent_at), "MMM d, yyyy HH:mm")}</p>
            )}
            {msg.communication_thread_id && (
              <p className="sm:col-span-2">
                Thread:{" "}
                <Link
                  href={`/communications/threads/${msg.communication_thread_id}`}
                  className="text-brand-700 hover:underline inline-flex items-center gap-0.5"
                >
                  {msg.communication_thread_title || msg.communication_thread_id.slice(0, 8)}
                  <ExternalLink size={10} />
                </Link>
              </p>
            )}
            {msg.follow_up_task_id && (
              <p className="sm:col-span-2">
                Follow-up task:{" "}
                <Link href="/tasks" className="text-brand-700 hover:underline">
                  {msg.follow_up_task_title || msg.follow_up_task_id.slice(0, 8)}
                </Link>
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            {msg.status === "draft" && (
              <button
                type="button"
                disabled={workflowBusy}
                onClick={() => approveMutation.mutate()}
                className="text-xs px-3 py-1.5 rounded border border-emerald-300 bg-emerald-50 text-emerald-900 flex items-center gap-1 disabled:opacity-50"
              >
                {approveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
                Approve
              </button>
            )}
            <button
              type="button"
              onClick={copyMessage}
              className="text-xs px-3 py-1.5 rounded border border-gray-200 bg-white flex items-center gap-1"
            >
              <Copy size={12} />
              Copy message
            </button>
            <button
              type="button"
              disabled={workflowBusy}
              onClick={() => markCopiedMutation.mutate()}
              className="text-xs px-3 py-1.5 rounded border border-gray-200 bg-white flex items-center gap-1 disabled:opacity-50"
            >
              Mark copied
            </button>
            {msg.status !== "sent" && (
              <button
                type="button"
                disabled={workflowBusy}
                onClick={() => markSentMutation.mutate()}
                className="text-xs px-3 py-1.5 rounded bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 flex items-center gap-1"
              >
                {markSentMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                Mark sent
              </button>
            )}
            {!msg.follow_up_task_id && (
              <>
                <input
                  type="datetime-local"
                  className="input text-xs w-auto"
                  value={followUpDue}
                  onChange={(e) => setFollowUpDue(e.target.value)}
                />
                <button
                  type="button"
                  disabled={workflowBusy}
                  onClick={() => followUpMutation.mutate()}
                  className="text-xs px-3 py-1.5 rounded border border-indigo-200 text-indigo-800 flex items-center gap-1 disabled:opacity-50"
                >
                  {followUpMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <ListTodo size={12} />}
                  Create follow-up
                </button>
              </>
            )}
            <button
              type="button"
              disabled={workflowBusy}
              onClick={() => setShowLinkThread((v) => !v)}
              className="text-xs px-3 py-1.5 rounded border border-gray-200 flex items-center gap-1 disabled:opacity-50"
            >
              <Link2 size={12} />
              Link thread
            </button>
          </div>

          {showLinkThread && (
            <div className="flex flex-wrap gap-2 items-end pt-1">
              {msg.lead_id && normalizeList(threadsData).length > 0 ? (
                <select
                  className="input text-xs flex-1 min-w-[200px]"
                  value={linkThreadId}
                  onChange={(e) => setLinkThreadId(e.target.value)}
                >
                  <option value="">Select thread…</option>
                  {normalizeList(threadsData).map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.title} ({t.channel})
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="input text-xs flex-1 min-w-[200px]"
                  placeholder="Communication thread UUID"
                  value={linkThreadId}
                  onChange={(e) => setLinkThreadId(e.target.value)}
                />
              )}
              <button
                type="button"
                className="btn-primary text-xs"
                disabled={!linkThreadId || linkThreadMutation.isPending}
                onClick={() => linkThreadMutation.mutate(linkThreadId)}
              >
                Link
              </button>
            </div>
          )}

          <p className="text-[10px] text-amber-700">
            Manual workflow only — Mark sent confirms you sent this outside the system. Nothing is auto-delivered.
          </p>
        </div>
      )}

      {/* Timeline */}
      {(msg.events?.length ?? 0) > 0 && (
        <div className="card p-4 space-y-2">
          <p className="text-xs font-semibold text-gray-900 flex items-center gap-1">
            <MessageSquare size={14} />
            Timeline
          </p>
          <ul className="space-y-2">
            {(msg.events ?? []).map((ev) => (
              <li key={ev.id} className="flex items-start gap-2 text-[11px]">
                <span className="text-gray-400 shrink-0">
                  {format(parseISO(ev.created_at), "MMM d, HH:mm")}
                </span>
                <span className="font-medium text-gray-800">
                  {EVENT_LABELS[ev.event_type] ?? ev.event_type}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {msg.subject && (
        <div className="card p-4 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold text-gray-900">Subject</p>
            <button
              type="button"
              onClick={() => copyText(msg.subject!, "Subject")}
              className="text-[10px] px-2 py-1 rounded border border-gray-200 flex items-center gap-1"
            >
              <Copy size={10} />
              Copy Subject
            </button>
          </div>
          <p className="text-sm text-gray-800">{msg.subject}</p>
        </div>
      )}

      <div className="card p-4 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-semibold text-gray-900">Message</p>
          <button
            type="button"
            onClick={() => copyText(msg.message_text, "Message")}
            className="text-[10px] px-2 py-1 rounded border border-gray-200 flex items-center gap-1"
          >
            <Copy size={10} />
            Copy Message
          </button>
        </div>
        <pre className="text-sm text-gray-800 whitespace-pre-wrap font-sans bg-gray-50 rounded p-3">
          {msg.message_text}
        </pre>
      </div>

      <div className="card p-4 space-y-3">
        <p className="text-xs font-semibold text-gray-900">Edit & regenerate</p>
        <div className="flex flex-wrap gap-2 items-center">
          <select
            className="input text-xs"
            value={regenStyle}
            onChange={(e) => setRegenStyle(e.target.value as OutreachStyle)}
          >
            {STYLES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <button
            type="button"
            disabled={regenMutation.isPending}
            onClick={() => regenMutation.mutate()}
            className="text-xs px-3 py-1.5 rounded border border-indigo-200 bg-indigo-50 text-indigo-900 flex items-center gap-1 disabled:opacity-50"
          >
            {regenMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            Regenerate
          </button>
          {msg.status !== "archived" && (
            <button
              type="button"
              disabled={updateMutation.isPending}
              onClick={() => updateMutation.mutate({ status: "archived" })}
              className="text-xs px-3 py-1.5 rounded border border-gray-200 flex items-center gap-1"
            >
              <Archive size={12} />
              Archive
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
