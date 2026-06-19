"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  Bot,
  Check,
  Copy,
  ExternalLink,
  Link2,
  ListTodo,
  Loader2,
  MessageCircle,
  Plus,
  Send,
  UserPlus,
} from "lucide-react";
import toast from "react-hot-toast";
import { WeChatSubNav } from "@/components/wechat/WeChatSubNav";
import {
  clientsApi,
  crmApi,
  normalizeList,
  wechatApi,
  WeChatChannel,
  WeChatGenerateReplyResult,
  CommunicationMessage,
  COMM_CRM_TASK_TYPES,
  CommCrmTaskType,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/I18nProvider";

const MESSAGE_STYLES: Record<string, string> = {
  inbound: "bg-white border-gray-200 mr-12",
  outbound: "bg-emerald-50 border-emerald-100 ml-12",
  draft: "bg-violet-50 border-violet-200 mx-6 border-dashed",
};

function parseDraftMeta(msg: CommunicationMessage): WeChatGenerateReplyResult | null {
  if (msg.direction !== "draft" || !msg.ai_summary) return null;
  try {
    const meta = JSON.parse(msg.ai_summary) as Partial<WeChatGenerateReplyResult>;
    return {
      message_id: msg.id,
      language: meta.language || "zh",
      reply_text: msg.message_text,
      tone: meta.tone || "professional",
      recommended_next_action: meta.recommended_next_action || "",
      risk_flags: meta.risk_flags || [],
    };
  } catch {
    return null;
  }
}

export default function WeChatMessagesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [inboundText, setInboundText] = useState("");
  const [showAddContact, setShowAddContact] = useState(false);
  const [linkLeadId, setLinkLeadId] = useState("");
  const [linkDealId, setLinkDealId] = useState("");
  const [taskType, setTaskType] = useState<CommCrmTaskType>("follow_up");
  const [latestReply, setLatestReply] = useState<WeChatGenerateReplyResult | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const [contactForm, setContactForm] = useState({
    name: "",
    channel: "wechat" as WeChatChannel,
    wechat_id: "",
    wecom_id: "",
    company: "",
    country: "",
    preferred_language: "zh",
    client_id: "",
  });

  const { data: clients } = useQuery({
    queryKey: ["clients-wechat"],
    queryFn: () => clientsApi.list().then((r) => normalizeList(r.data)),
  });

  const { data: contactsData } = useQuery({
    queryKey: ["wechat-contacts", search],
    queryFn: () => wechatApi.listContacts({ search: search || undefined, limit: 50 }).then((r) => r.data),
  });

  const { data: threadsData } = useQuery({
    queryKey: ["wechat-threads"],
    queryFn: () => wechatApi.listThreads({ limit: 100 }).then((r) => r.data),
  });

  const { data: thread, isLoading: threadLoading } = useQuery({
    queryKey: ["wechat-thread", selectedThreadId],
    queryFn: () => wechatApi.getThread(selectedThreadId!).then((r) => r.data),
    enabled: !!selectedThreadId,
  });

  const { data: leads } = useQuery({
    queryKey: ["crm-leads-wechat", thread?.client_id],
    queryFn: () =>
      crmApi.listLeads({ client_id: thread!.client_id!, limit: 100 }).then((r) => r.data),
    enabled: !!thread?.client_id,
  });

  const { data: deals } = useQuery({
    queryKey: ["crm-deals-wechat", thread?.client_id],
    queryFn: () =>
      crmApi.listDeals({ client_id: thread!.client_id! }).then((r) => r.data),
    enabled: !!thread?.client_id,
  });

  const invalidateThread = () => {
    qc.invalidateQueries({ queryKey: ["wechat-thread", selectedThreadId] });
    qc.invalidateQueries({ queryKey: ["wechat-threads"] });
    qc.invalidateQueries({ queryKey: ["wechat-contacts"] });
    qc.invalidateQueries({ queryKey: ["wechat-dashboard"] });
  };

  const createContactMutation = useMutation({
    mutationFn: () =>
      wechatApi.createContact({
        name: contactForm.name.trim(),
        channel: contactForm.channel,
        wechat_id: contactForm.wechat_id.trim() || null,
        wecom_id: contactForm.wecom_id.trim() || null,
        company: contactForm.company.trim() || null,
        country: contactForm.country.trim() || null,
        preferred_language: contactForm.preferred_language || null,
        client_id: contactForm.client_id || null,
      }).then(async (r) => {
        const contact = r.data;
        const threadRes = await wechatApi.createThread({
          contact_id: contact.id,
          channel: contactForm.channel,
          client_id: contactForm.client_id || null,
        });
        return { contact, thread: threadRes.data };
      }),
    onSuccess: ({ thread: newThread }) => {
      setShowAddContact(false);
      setSelectedThreadId(newThread.id);
      invalidateThread();
      toast.success(t("wechat.contactCreated"));
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create contact"),
  });

  const pasteMutation = useMutation({
    mutationFn: () =>
      wechatApi.pasteInbound(selectedThreadId!, {
        message_text: inboundText.trim(),
      }).then((r) => r.data),
    onSuccess: () => {
      setInboundText("");
      invalidateThread();
      toast.success(t("wechat.inboundPasted"));
    },
    onError: (err: Error) => toast.error(err.message || "Failed to paste message"),
  });

  const generateMutation = useMutation({
    mutationFn: () => wechatApi.generateReply(selectedThreadId!).then((r) => r.data),
    onSuccess: (data) => {
      setLatestReply(data);
      invalidateThread();
      toast.success(data.demo_mode ? t("wechat.draftDemo") : t("wechat.draftGenerated"));
    },
    onError: (err: Error) => toast.error(err.message || "Generate reply failed"),
  });

  const markCopiedMutation = useMutation({
    mutationFn: (messageId: string) => wechatApi.markCopied(messageId).then((r) => r.data),
    onSuccess: () => {
      invalidateThread();
      toast.success(t("wechat.markedCopied"));
    },
    onError: (err: Error) => toast.error(err.message || "Failed to mark copied"),
  });

  const markSentMutation = useMutation({
    mutationFn: (messageId: string) => wechatApi.markManuallySent(messageId).then((r) => r.data),
    onSuccess: () => {
      setLatestReply(null);
      invalidateThread();
      toast.success(t("wechat.markedSent"));
    },
    onError: (err: Error) => toast.error(err.message || "Failed to mark sent"),
  });

  const createLeadMutation = useMutation({
    mutationFn: () => wechatApi.createLead(selectedThreadId!).then((r) => r.data),
    onSuccess: (data) => {
      invalidateThread();
      toast.success(data.created ? `Lead created: ${data.lead_name}` : `Lead updated: ${data.lead_name}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create lead"),
  });

  const linkLeadMutation = useMutation({
    mutationFn: () => wechatApi.linkLead(selectedThreadId!, linkLeadId).then((r) => r.data),
    onSuccess: (data) => {
      setLinkLeadId("");
      invalidateThread();
      toast.success(`Linked to ${data.lead_name}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to link lead"),
  });

  const linkDealMutation = useMutation({
    mutationFn: () => wechatApi.linkDeal(selectedThreadId!, linkDealId).then((r) => r.data),
    onSuccess: (data) => {
      setLinkDealId("");
      invalidateThread();
      toast.success(`Linked to deal: ${data.deal_title}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to link deal"),
  });

  const createTaskMutation = useMutation({
    mutationFn: () =>
      wechatApi.createTask(selectedThreadId!, { task_type: taskType }).then((r) => r.data),
    onSuccess: (data) => toast.success(`Task created: ${data.title}`),
    onError: (err: Error) => toast.error(err.message || "Failed to create task"),
  });

  const contacts = contactsData?.items ?? [];
  const threads = threadsData?.items ?? [];

  const activeReply = useMemo(() => {
    if (latestReply) return latestReply;
    if (!thread?.messages?.length) return null;
    for (let i = thread.messages.length - 1; i >= 0; i -= 1) {
      const m = thread.messages[i];
      if (m.direction === "draft") {
        return parseDraftMeta(m) || {
          message_id: m.id,
          language: "zh",
          reply_text: m.message_text,
          tone: "professional",
          recommended_next_action: thread.ai_panel?.recommended_next_action || "",
          risk_flags: [],
        };
      }
    }
    return null;
  }, [latestReply, thread]);

  const copyReply = async (text: string, messageId?: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedId(messageId || "draft");
    setTimeout(() => setCopiedId(null), 2000);
    if (messageId) {
      markCopiedMutation.mutate(messageId);
    }
    toast.success(t("wechat.copyManualNote"));
  };

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)]">
      <header className="shrink-0 border-b border-gray-200 bg-white px-4 py-3 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <MessageCircle className="text-emerald-600" size={20} />
            <div>
              <h1 className="text-lg font-semibold text-gray-900">{t("wechat.nav.messages")}</h1>
              <p className="text-xs text-gray-500">{t("wechat.messagesSubtitle")}</p>
            </div>
          </div>
          <button
            type="button"
            className="btn-primary text-sm flex items-center gap-1.5"
            onClick={() => setShowAddContact(true)}
          >
            <Plus size={14} />
            {t("wechat.addContact")}
          </button>
        </div>
        <WeChatSubNav />
      </header>

      <div className="flex flex-1 min-h-0">
        <aside className="w-72 shrink-0 border-r border-gray-200 bg-white flex flex-col">
          <div className="p-3 border-b border-gray-100">
            <input
              className="input text-sm w-full"
              placeholder={t("wechat.searchContacts")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex-1 overflow-y-auto">
            <p className="px-3 pt-3 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
              {t("wechat.conversations")}
            </p>
            <ul className="p-2 space-y-1">
              {threads.map((th) => (
                <li key={th.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedThreadId(th.id);
                      setLatestReply(null);
                    }}
                    className={cn(
                      "w-full text-left rounded-lg px-3 py-2 text-sm transition-colors",
                      selectedThreadId === th.id
                        ? "bg-emerald-50 text-emerald-900 border border-emerald-100"
                        : "hover:bg-gray-50 text-gray-800",
                    )}
                  >
                    <div className="font-medium truncate">{th.contact_name || th.title}</div>
                    <div className="text-[11px] text-gray-500 truncate">
                      {th.channel === "wecom" ? "WeCom" : "WeChat"}
                      {th.last_message_preview ? ` · ${th.last_message_preview}` : ""}
                    </div>
                  </button>
                </li>
              ))}
              {threads.length === 0 && (
                <li className="px-3 py-6 text-xs text-gray-400 text-center">{t("wechat.noThreads")}</li>
              )}
            </ul>
          </div>
        </aside>

        <section className="flex-1 flex flex-col min-w-0 bg-gray-50">
          {!selectedThreadId ? (
            <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
              {t("wechat.selectThread")}
            </div>
          ) : threadLoading || !thread ? (
            <div className="flex-1 flex items-center justify-center text-sm text-gray-500">
              <Loader2 className="animate-spin mr-2" size={16} />
              {t("common.loading")}
            </div>
          ) : (
            <>
              <div className="shrink-0 border-b border-gray-200 bg-white px-4 py-3">
                <h2 className="font-semibold text-gray-900">{thread.contact?.name || thread.title}</h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  {thread.contact?.company || "—"}
                  {thread.contact?.country ? ` · ${thread.contact.country}` : ""}
                  {thread.contact?.wechat_id ? ` · ID: ${thread.contact.wechat_id}` : ""}
                </p>
                {thread.lead_id && (
                  <Link href="/crm" className="text-xs text-brand-700 inline-flex items-center gap-1 mt-1">
                    CRM Lead: {thread.lead_name}
                    <ExternalLink size={11} />
                  </Link>
                )}
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {(thread.messages ?? []).map((msg) => (
                  <div
                    key={msg.id}
                    className={cn(
                      "rounded-xl border px-3 py-2 text-sm",
                      MESSAGE_STYLES[msg.direction] || MESSAGE_STYLES.inbound,
                    )}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="text-[11px] font-medium text-gray-600">
                        {msg.direction === "draft" ? "AI draft" : msg.sender_name}
                      </span>
                      <span className="text-[10px] text-gray-400">
                        {format(parseISO(msg.created_at), "MMM d, HH:mm")}
                      </span>
                    </div>
                    <p className="whitespace-pre-wrap text-gray-900">{msg.message_text}</p>
                    {msg.translated_text && (
                      <p className="mt-1 text-xs text-gray-500 border-t border-gray-100 pt-1">
                        Translation: {msg.translated_text}
                      </p>
                    )}
                    {msg.direction === "draft" && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        <button
                          type="button"
                          className="text-xs btn-secondary py-1 px-2 inline-flex items-center gap-1"
                          onClick={() => copyReply(msg.message_text, msg.id)}
                        >
                          {copiedId === msg.id ? <Check size={12} /> : <Copy size={12} />}
                          Copy
                        </button>
                        <button
                          type="button"
                          className="text-xs btn-primary py-1 px-2 inline-flex items-center gap-1"
                          onClick={() => markSentMutation.mutate(msg.id)}
                          disabled={markSentMutation.isPending}
                        >
                          <Send size={12} />
                          Mark manually sent
                        </button>
                      </div>
                    )}
                    {msg.manual_sent_at && (
                      <p className="text-[10px] text-emerald-600 mt-1">{t("wechat.sentManually")}</p>
                    )}
                  </div>
                ))}
              </div>

              <div className="shrink-0 border-t border-gray-200 bg-white p-4 space-y-2">
                <label className="text-xs font-medium text-gray-600">{t("wechat.pasteInbound")}</label>
                <textarea
                  className="input w-full text-sm min-h-[80px]"
                  placeholder={t("wechat.pastePlaceholder")}
                  value={inboundText}
                  onChange={(e) => setInboundText(e.target.value)}
                />
                <button
                  type="button"
                  className="btn-primary text-sm"
                  disabled={!inboundText.trim() || pasteMutation.isPending}
                  onClick={() => pasteMutation.mutate()}
                >
                  {pasteMutation.isPending ? t("common.loading") : t("wechat.pasteInbound")}
                </button>
              </div>
            </>
          )}
        </section>

        <aside className="w-80 shrink-0 border-l border-gray-200 bg-white flex flex-col overflow-y-auto hidden lg:flex">
          <div className="p-4 space-y-4">
            <div className="rounded-xl border border-violet-100 bg-violet-50/40 p-3 space-y-2">
              <div className="flex items-center gap-2 text-violet-900 font-semibold text-sm">
                <Bot size={16} />
                AI Assistant
              </div>
              {thread?.ai_panel ? (
                <>
                  <p className="text-xs text-gray-700">{thread.ai_panel.summary}</p>
                  <p className="text-xs text-violet-800">
                    <span className="font-medium">Next:</span> {thread.ai_panel.recommended_next_action}
                  </p>
                </>
              ) : (
                <p className="text-xs text-gray-500">{t("wechat.selectThread")}</p>
              )}
              <button
                type="button"
                className="btn-primary w-full text-sm"
                disabled={!selectedThreadId || generateMutation.isPending}
                onClick={() => generateMutation.mutate()}
              >
                {generateMutation.isPending ? t("common.loading") : t("wechat.generateReply")}
              </button>
            </div>

            {activeReply && (
              <div className="rounded-xl border border-gray-200 p-3 space-y-2">
                <p className="text-xs font-semibold text-gray-800">{t("wechat.latestDraft")}</p>
                <p className="text-xs text-gray-600 whitespace-pre-wrap">{activeReply.reply_text}</p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="btn-secondary text-xs flex-1 inline-flex items-center justify-center gap-1"
                    onClick={() => copyReply(activeReply.reply_text, activeReply.message_id)}
                  >
                    <Copy size={12} />
                    Copy
                  </button>
                  <button
                    type="button"
                    className="btn-primary text-xs flex-1"
                    onClick={() => markSentMutation.mutate(activeReply.message_id)}
                  >
                    Mark sent
                  </button>
                </div>
              </div>
            )}

            <div className="rounded-xl border border-gray-200 p-3 space-y-2">
              <p className="text-xs font-semibold text-gray-800">CRM</p>
              <button
                type="button"
                className="btn-secondary w-full text-xs inline-flex items-center justify-center gap-1"
                disabled={!selectedThreadId || createLeadMutation.isPending}
                onClick={() => createLeadMutation.mutate()}
              >
                <UserPlus size={12} />
                Create CRM lead
              </button>
              <div className="flex gap-1">
                <select
                  className="input text-xs flex-1"
                  value={linkLeadId}
                  onChange={(e) => setLinkLeadId(e.target.value)}
                >
                  <option value="">Link lead…</option>
                  {(leads?.items ?? []).map((l) => (
                    <option key={l.id} value={l.id}>{l.name}</option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn-secondary text-xs px-2"
                  disabled={!linkLeadId || linkLeadMutation.isPending}
                  onClick={() => linkLeadMutation.mutate()}
                >
                  <Link2 size={12} />
                </button>
              </div>
              <div className="flex gap-1">
                <select
                  className="input text-xs flex-1"
                  value={linkDealId}
                  onChange={(e) => setLinkDealId(e.target.value)}
                >
                  <option value="">Link deal…</option>
                  {(deals?.items ?? []).map((d) => (
                    <option key={d.id} value={d.id}>{d.title}</option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn-secondary text-xs px-2"
                  disabled={!linkDealId || linkDealMutation.isPending}
                  onClick={() => linkDealMutation.mutate()}
                >
                  <Link2 size={12} />
                </button>
              </div>
            </div>

            <div className="rounded-xl border border-gray-200 p-3 space-y-2">
              <p className="text-xs font-semibold text-gray-800 inline-flex items-center gap-1">
                <ListTodo size={12} />
                Follow-up task
              </p>
              <select
                className="input text-xs w-full"
                value={taskType}
                onChange={(e) => setTaskType(e.target.value as CommCrmTaskType)}
              >
                {COMM_CRM_TASK_TYPES.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <button
                type="button"
                className="btn-secondary w-full text-xs"
                disabled={!selectedThreadId || createTaskMutation.isPending}
                onClick={() => createTaskMutation.mutate()}
              >
                Create follow-up task
              </button>
            </div>
          </div>
        </aside>
      </div>

      {showAddContact && (
        <div
          data-app-modal
          className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4"
        >
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5 space-y-3">
            <h3 className="font-semibold text-gray-900">{t("wechat.addContact")}</h3>
            <input
              className="input w-full text-sm"
              placeholder="Name *"
              value={contactForm.name}
              onChange={(e) => setContactForm((f) => ({ ...f, name: e.target.value }))}
            />
            <select
              className="input w-full text-sm"
              value={contactForm.channel}
              onChange={(e) => setContactForm((f) => ({ ...f, channel: e.target.value as WeChatChannel }))}
            >
              <option value="wechat">WeChat</option>
              <option value="wecom">WeCom</option>
            </select>
            <input
              className="input w-full text-sm"
              placeholder="WeChat ID"
              value={contactForm.wechat_id}
              onChange={(e) => setContactForm((f) => ({ ...f, wechat_id: e.target.value }))}
            />
            <input
              className="input w-full text-sm"
              placeholder="Company"
              value={contactForm.company}
              onChange={(e) => setContactForm((f) => ({ ...f, company: e.target.value }))}
            />
            <div className="flex gap-2 pt-2">
              <button type="button" className="btn-secondary flex-1" onClick={() => setShowAddContact(false)}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="btn-primary flex-1"
                disabled={!contactForm.name.trim() || createContactMutation.isPending}
                onClick={() => createContactMutation.mutate()}
              >
                {createContactMutation.isPending ? t("common.loading") : t("common.create")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
