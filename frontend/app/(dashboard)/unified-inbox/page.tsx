"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  Bot,
  ExternalLink,
  FileSignature,
  Inbox,
  Link2,
  ListTodo,
  Loader2,
  MessageCircle,
  MessagesSquare,
  Send,
  Sparkles,
  UserPlus,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  COMM_CRM_TASK_TYPES,
  CommCrmTaskType,
  UnifiedConversation,
  UnifiedInboxChannel,
  communicationsApi,
  crmApi,
  unifiedInboxApi,
  operatorTaskEngineApi,
  SalesAssistantRecommendation,
  CommunicationMessage,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/I18nProvider";

const CHANNEL_BADGE: Record<UnifiedInboxChannel, { label: string; className: string }> = {
  wechat: { label: "WeChat", className: "bg-emerald-100 text-emerald-800 border-emerald-200" },
  wecom: { label: "WeCom", className: "bg-sky-100 text-sky-800 border-sky-200" },
  whatsapp: { label: "WhatsApp", className: "bg-green-100 text-green-800 border-green-200" },
  email: { label: "Email", className: "bg-amber-100 text-amber-800 border-amber-200" },
  outreach: { label: "Outreach", className: "bg-violet-100 text-violet-800 border-violet-200" },
  manual: { label: "Manual", className: "bg-gray-100 text-gray-700 border-gray-200" },
};

const MESSAGE_STYLES: Record<string, string> = {
  inbound: "bg-white border-gray-200 mr-12",
  outbound: "bg-emerald-50 border-emerald-100 ml-12",
  draft: "bg-violet-50 border-violet-200 mx-6 border-dashed",
  internal_note: "bg-amber-50 border-amber-100 mx-8",
};

const CHANNEL_FILTERS: { value: UnifiedInboxChannel | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "wechat", label: "WeChat" },
  { value: "wecom", label: "WeCom" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "email", label: "Email" },
  { value: "outreach", label: "Outreach" },
  { value: "manual", label: "Manual" },
];

function ChannelBadge({ channel }: { channel: UnifiedInboxChannel }) {
  const cfg = CHANNEL_BADGE[channel] ?? CHANNEL_BADGE.manual;
  return (
    <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded border", cfg.className)}>
      {cfg.label}
    </span>
  );
}

function ConversationRow({
  conv,
  selected,
  onSelect,
}: {
  conv: UnifiedConversation;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full text-left rounded-lg px-3 py-2 text-sm transition-colors border",
        selected
          ? "bg-brand-50 text-brand-900 border-brand-100"
          : "hover:bg-gray-50 text-gray-800 border-transparent",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium truncate">{conv.contact_name}</span>
        <ChannelBadge channel={conv.channel} />
      </div>
      {conv.company && (
        <p className="text-[11px] text-gray-500 truncate">{conv.company}</p>
      )}
      <p className="text-[11px] text-gray-400 truncate mt-0.5">
        {conv.last_message || "No messages"}
      </p>
      <div className="flex items-center gap-2 mt-1 text-[10px] text-gray-400">
        {conv.last_message_at && (
          <span>{format(parseISO(conv.last_message_at), "MMM d, HH:mm")}</span>
        )}
        {conv.unread_count > 0 && (
          <span className="bg-red-500 text-white rounded-full px-1.5 min-w-[18px] text-center">
            {conv.unread_count}
          </span>
        )}
        {conv.lead_id && (
          <span className="text-brand-600">CRM</span>
        )}
        {conv.communication_health_score != null && (
          <span className="text-orange-700 font-semibold tabular-nums">
            {conv.communication_health_score}
          </span>
        )}
        {conv.communication_classification && (
          <span className="capitalize text-violet-700">{conv.communication_classification}</span>
        )}
      </div>
    </button>
  );
}

export default function UnifiedInboxPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [channel, setChannel] = useState<UnifiedInboxChannel | "">("");
  const [linked, setLinked] = useState<"" | "linked" | "unlinked">("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [linkLeadId, setLinkLeadId] = useState("");
  const [linkDealId, setLinkDealId] = useState("");
  const [taskType, setTaskType] = useState<CommCrmTaskType>("follow_up");

  const listParams = useMemo(
    () => ({
      search: search.trim() || undefined,
      channel: channel || undefined,
      linked: linked || undefined,
      unread: unreadOnly ? true : undefined,
      limit: 100,
    }),
    [search, channel, linked, unreadOnly],
  );

  const { data: listData, isLoading: listLoading } = useQuery({
    queryKey: ["unified-inbox", listParams],
    queryFn: () => unifiedInboxApi.list(listParams).then((r) => r.data),
  });

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ["unified-inbox-detail", selectedId],
    queryFn: () => unifiedInboxApi.get(selectedId!).then((r) => r.data),
    enabled: !!selectedId,
  });

  const conv = detail?.conversation;
  const threadId = conv?.thread_id;

  const { data: leads } = useQuery({
    queryKey: ["crm-leads-unified", conv?.client_id],
    queryFn: () =>
      crmApi.listLeads({ client_id: conv!.client_id!, limit: 100 }).then((r) => r.data),
    enabled: !!conv?.client_id,
  });

  const { data: deals } = useQuery({
    queryKey: ["crm-deals-unified", conv?.client_id],
    queryFn: () =>
      crmApi.listDeals({ client_id: conv!.client_id! }).then((r) => r.data),
    enabled: !!conv?.client_id && conv?.source === "thread",
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["unified-inbox"] });
    qc.invalidateQueries({ queryKey: ["unified-inbox-detail", selectedId] });
  };

  const linkLeadMutation = useMutation({
    mutationFn: () => unifiedInboxApi.linkLead(selectedId!, linkLeadId).then((r) => r.data),
    onSuccess: (data) => {
      setLinkLeadId("");
      invalidate();
      toast.success(`Linked to ${data.lead_name}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to link lead"),
  });

  const linkDealMutation = useMutation({
    mutationFn: () => unifiedInboxApi.linkDeal(selectedId!, linkDealId).then((r) => r.data),
    onSuccess: (data) => {
      setLinkDealId("");
      invalidate();
      toast.success(`Linked to deal: ${data.deal_title}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to link deal"),
  });

  const createTaskMutation = useMutation({
    mutationFn: () =>
      operatorTaskEngineApi
        .fromConversation(selectedId!, { task_type: taskType })
        .then((r) => r.data),
    onSuccess: (data) => toast.success(data.message || `Task created: ${data.task.title}`),
    onError: (err: Error) => toast.error(err.message || "Failed to create task"),
  });

  const createLeadMutation = useMutation({
    mutationFn: () => {
      if (!threadId) throw new Error("Create lead requires a communication thread");
      return communicationsApi.createLead(threadId).then((r) => r.data);
    },
    onSuccess: (data) => {
      invalidate();
      toast.success(data.created ? `Lead created: ${data.lead_name}` : `Lead updated: ${data.lead_name}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create lead"),
  });

  const conversations = listData?.items ?? [];

  const openContactHref = conv?.contact_id
    ? `/communications/contacts/${conv.contact_id}`
    : conv?.outreach_id
      ? `/outreach/${conv.outreach_id}`
      : null;

  const openProposalHref =
    conv?.lead_id ? `/proposals?lead_id=${conv.lead_id}` : null;

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)]">
      <header className="shrink-0 border-b border-gray-200 bg-white px-4 py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Inbox className="text-brand-600" size={20} />
          <div>
            <h1 className="text-lg font-semibold text-gray-900">{t("nav.unifiedInbox")}</h1>
            <p className="text-xs text-gray-500">
              All channels in one place — manual actions only, no auto-send
            </p>
          </div>
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        <aside className="w-80 shrink-0 border-r border-gray-200 bg-white flex flex-col">
          <div className="p-3 border-b border-gray-100 space-y-2">
            <input
              className="input text-sm w-full"
              placeholder="Search contact, company, message…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="flex flex-wrap gap-1">
              {CHANNEL_FILTERS.map((f) => (
                <button
                  key={f.value || "all"}
                  type="button"
                  onClick={() => setChannel(f.value)}
                  className={cn(
                    "text-[10px] px-2 py-1 rounded-full border",
                    channel === f.value
                      ? "bg-brand-100 border-brand-200 text-brand-800"
                      : "border-gray-200 text-gray-600 hover:bg-gray-50",
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={unreadOnly}
                  onChange={(e) => setUnreadOnly(e.target.checked)}
                />
                Unread
              </label>
              <select
                className="input text-xs py-1"
                value={linked}
                onChange={(e) => setLinked(e.target.value as typeof linked)}
              >
                <option value="">All CRM links</option>
                <option value="linked">Linked</option>
                <option value="unlinked">Unlinked</option>
              </select>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {listLoading ? (
              <div className="flex justify-center py-8 text-gray-400">
                <Loader2 className="animate-spin" size={20} />
              </div>
            ) : conversations.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-8">No conversations</p>
            ) : (
              conversations.map((c) => (
                <ConversationRow
                  key={c.id}
                  conv={c}
                  selected={selectedId === c.id}
                  onSelect={() => setSelectedId(c.id)}
                />
              ))
            )}
          </div>
        </aside>

        <section className="flex-1 flex flex-col min-w-0 bg-gray-50">
          {!selectedId ? (
            <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
              Select a conversation
            </div>
          ) : detailLoading || !detail ? (
            <div className="flex-1 flex items-center justify-center text-sm text-gray-500">
              <Loader2 className="animate-spin mr-2" size={16} />
              Loading conversation…
            </div>
          ) : (
            <>
              <div className="shrink-0 border-b border-gray-200 bg-white px-4 py-3">
                <div className="flex items-center gap-2">
                  <h2 className="font-semibold text-gray-900">{conv!.contact_name}</h2>
                  <ChannelBadge channel={conv!.channel} />
                </div>
                <p className="text-xs text-gray-500 mt-0.5">
                  {[conv!.company, conv!.country].filter(Boolean).join(" · ") || "—"}
                </p>
                {conv!.lead_id && (
                  <Link href="/crm" className="text-xs text-brand-700 inline-flex items-center gap-1 mt-1">
                    CRM: {conv!.lead_name || conv!.lead_id}
                    <ExternalLink size={11} />
                  </Link>
                )}
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {(detail.messages ?? []).map((msg: CommunicationMessage) => (
                  <div
                    key={msg.id}
                    className={cn(
                      "rounded-xl border px-3 py-2 text-sm",
                      MESSAGE_STYLES[msg.direction] || MESSAGE_STYLES.inbound,
                    )}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="text-[11px] font-medium text-gray-600">{msg.sender_name}</span>
                      <span className="text-[10px] text-gray-400">
                        {format(parseISO(msg.created_at), "MMM d, HH:mm")}
                      </span>
                    </div>
                    <p className="whitespace-pre-wrap text-gray-900">{msg.message_text}</p>
                  </div>
                ))}
              </div>

              <div className="shrink-0 border-t border-gray-200 bg-white px-4 py-2 flex flex-wrap gap-2 text-xs">
                {openContactHref && (
                  <Link href={openContactHref} className="btn-secondary py-1 px-2 inline-flex items-center gap-1">
                    <MessageCircle size={12} />
                    Open contact
                  </Link>
                )}
                {conv!.channel === "wechat" || conv!.channel === "wecom" ? (
                  <Link
                    href={threadId ? `/wechat` : "/wechat"}
                    className="btn-secondary py-1 px-2 inline-flex items-center gap-1"
                  >
                    WeChat Center
                  </Link>
                ) : null}
                {conv!.channel === "whatsapp" && conv!.whatsapp_thread_id ? (
                  <Link
                    href="/whatsapp"
                    className="btn-secondary py-1 px-2 inline-flex items-center gap-1"
                  >
                    WhatsApp Center
                  </Link>
                ) : null}
                {openProposalHref && (
                  <Link href={openProposalHref} className="btn-secondary py-1 px-2 inline-flex items-center gap-1">
                    <FileSignature size={12} />
                    Proposals
                  </Link>
                )}
                {conv!.channel === "outreach" && conv!.outreach_id && (
                  <Link
                    href={`/outreach/${conv!.outreach_id}`}
                    className="btn-secondary py-1 px-2 inline-flex items-center gap-1"
                  >
                    <Send size={12} />
                    Open outreach
                  </Link>
                )}
              </div>
            </>
          )}
        </section>

        <aside className="w-80 shrink-0 border-l border-gray-200 bg-white flex flex-col overflow-y-auto">
          <div className="p-4 space-y-4">
            <div className="rounded-xl border border-violet-100 bg-violet-50/40 p-3 space-y-2">
              <div className="flex items-center gap-2 text-violet-900 font-semibold text-sm">
                <Bot size={16} />
                AI Assistant
              </div>
              {detail?.ai_panel ? (
                <>
                  <p className="text-xs text-gray-700">{detail.ai_panel.summary}</p>
                  {detail.ai_panel.lead_status && (
                    <p className="text-xs text-gray-600">
                      Lead status: <strong>{detail.ai_panel.lead_status}</strong>
                    </p>
                  )}
                  {detail.ai_panel.proposal_status && (
                    <p className="text-xs text-gray-600">
                      Proposal: <strong>{detail.ai_panel.proposal_status}</strong>
                    </p>
                  )}
                  <p className="text-xs text-violet-800">{detail.ai_panel.recommended_action}</p>
                </>
              ) : (
                <p className="text-xs text-gray-500">Select a conversation</p>
              )}
            </div>

            {(detail?.communication_intelligence?.intelligence ||
              detail?.conversation?.communication_health_score != null) && (
              <div className="rounded-xl border border-teal-100 bg-teal-50/40 p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-teal-900 font-semibold text-sm">
                    <MessagesSquare size={16} />
                    Communication Intelligence
                  </div>
                  <Link href="/communication-intelligence" className="text-[10px] text-brand-700 hover:underline">
                    View all
                  </Link>
                </div>
                {detail?.communication_intelligence?.intelligence ? (
                  <>
                    <p className="text-xs text-gray-700">
                      Health{" "}
                      <strong>{detail.communication_intelligence.intelligence.health_score}/100</strong>
                      {" · "}
                      <span className="capitalize">
                        {detail.communication_intelligence.intelligence.classification}
                      </span>
                    </p>
                    {(detail.communication_intelligence.intelligence.insights ?? [])
                      .slice(0, 3)
                      .map((item) => (
                        <p key={item} className="text-xs text-gray-600 capitalize">
                          • {item}
                        </p>
                      ))}
                  </>
                ) : (
                  <p className="text-xs text-gray-600">
                    Health {detail?.conversation?.communication_health_score}/100 ·{" "}
                    <span className="capitalize">{detail?.conversation?.communication_classification}</span>
                  </p>
                )}
              </div>
            )}

            {(detail?.sales_assistant_recommendations?.length ?? 0) > 0 && (
              <div className="rounded-xl border border-amber-100 bg-amber-50/40 p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-amber-900 font-semibold text-sm">
                    <Sparkles size={16} />
                    Sales Assistant
                  </div>
                  <Link href="/sales-assistant" className="text-[10px] text-brand-700">
                    View all
                  </Link>
                </div>
                <ul className="space-y-2">
                  {detail!.sales_assistant_recommendations!.map((rec: SalesAssistantRecommendation) => (
                    <li key={rec.id} className="text-xs border-b border-amber-100/80 pb-2 last:border-0">
                      <p className="font-medium text-gray-900">{rec.title}</p>
                      <p className="text-gray-600 mt-0.5 line-clamp-2">{rec.recommended_action}</p>
                      <div className="flex gap-1 mt-1.5">
                        <Link
                          href="/sales-assistant"
                          className="text-[10px] text-brand-700"
                        >
                          Details
                        </Link>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail?.ai_panel?.can_create_lead && threadId && (
              <button
                type="button"
                className="btn-primary w-full text-sm flex items-center justify-center gap-1.5"
                disabled={createLeadMutation.isPending}
                onClick={() => createLeadMutation.mutate()}
              >
                <UserPlus size={14} />
                Create lead
              </button>
            )}

            {detail?.ai_panel?.can_create_proposal && conv?.lead_id && (
              <Link
                href={`/proposals/new?lead_id=${conv.lead_id}`}
                className="btn-secondary w-full text-sm flex items-center justify-center gap-1.5"
              >
                <FileSignature size={14} />
                Create proposal
              </Link>
            )}

            {conv?.client_id && (
              <div className="space-y-2 border-t border-gray-100 pt-3">
                <p className="text-xs font-semibold text-gray-600">Link CRM lead</p>
                <select
                  className="input text-sm w-full"
                  value={linkLeadId}
                  onChange={(e) => setLinkLeadId(e.target.value)}
                >
                  <option value="">Select lead…</option>
                  {(leads?.items ?? []).map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn-secondary w-full text-sm"
                  disabled={!linkLeadId || linkLeadMutation.isPending}
                  onClick={() => linkLeadMutation.mutate()}
                >
                  <Link2 size={14} className="inline mr-1" />
                  Link lead
                </button>
              </div>
            )}

            {conv?.source === "thread" && conv?.client_id && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-gray-600">Link deal</p>
                <select
                  className="input text-sm w-full"
                  value={linkDealId}
                  onChange={(e) => setLinkDealId(e.target.value)}
                >
                  <option value="">Select deal…</option>
                  {(deals?.items ?? []).map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.title}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn-secondary w-full text-sm"
                  disabled={!linkDealId || linkDealMutation.isPending}
                  onClick={() => linkDealMutation.mutate()}
                >
                  Link deal
                </button>
              </div>
            )}

            <div className="space-y-2 border-t border-gray-100 pt-3">
              <p className="text-xs font-semibold text-gray-600 flex items-center gap-1">
                <ListTodo size={14} />
                Create task
              </p>
              <select
                className="input text-sm w-full"
                value={taskType}
                onChange={(e) => setTaskType(e.target.value as CommCrmTaskType)}
              >
                {COMM_CRM_TASK_TYPES.map((tt) => (
                  <option key={tt.value} value={tt.value}>
                    {tt.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn-primary w-full text-sm"
                disabled={!selectedId || createTaskMutation.isPending}
                onClick={() => createTaskMutation.mutate()}
              >
                Create task
              </button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
