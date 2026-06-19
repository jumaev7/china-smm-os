"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Inbox, MessagesSquare, Plus, Search } from "lucide-react";
import {
  CHANNEL_LABELS,
  CommunicationChannel,
  communicationHubApi,
  communicationsApi,
  normalizeList,
  type CommunicationRecord,
  type CommunicationThread,
  unifiedInboxApi,
  type UnifiedConversation,
  type UnifiedInboxChannel,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageSection, PageShell } from "@/components/ui/design-system";
import { CommunicationsSubNav } from "@/components/communications/CommunicationsSubNav";
import { useTranslation } from "@/lib/I18nProvider";

const CHANNELS: (CommunicationChannel | "telegram")[] = [
  "telegram",
  "whatsapp",
  "wechat",
  "email",
  "manual",
];

function UnifiedRow({ conv }: { conv: UnifiedConversation }) {
  const href =
    conv.source === "thread"
      ? `/communications/threads/${conv.source_id}`
      : `/unified-inbox`;
  const title = conv.contact_name + (conv.company ? ` — ${conv.company}` : "");
  return (
    <Link href={href} className="block card p-3 hover:ring-1 hover:ring-brand-200 transition-shadow">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">{title}</p>
          <p className="text-xs text-gray-500 truncate">
            {conv.country ?? "—"}
            {conv.lead_name ? ` · ${conv.lead_name}` : ""}
          </p>
        </div>
        <span className="text-[10px] px-1.5 py-0.5 rounded border capitalize shrink-0 bg-gray-50 text-gray-600">
          {conv.channel}
        </span>
      </div>
      {conv.last_message && (
        <p className="text-xs text-gray-600 mt-1 line-clamp-2">{conv.last_message}</p>
      )}
      {conv.last_message_at && (
        <p className="text-[10px] text-gray-400 mt-1">
          {format(parseISO(conv.last_message_at), "MMM d, HH:mm")}
        </p>
      )}
    </Link>
  );
}

function RecordRow({ record }: { record: CommunicationRecord }) {
  return (
    <Link
      href={`/communications/threads/${record.thread_id}`}
      className="block card p-3 hover:ring-1 hover:ring-brand-200 transition-shadow"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">{record.subject}</p>
          <p className="text-xs text-gray-500 truncate">
            {record.contact_name ?? "—"} · {CHANNEL_LABELS[record.channel as CommunicationChannel] ?? record.channel}
          </p>
        </div>
        <span className="text-[10px] px-1.5 py-0.5 rounded border capitalize shrink-0">
          {record.direction}
        </span>
      </div>
      <p className="text-xs text-gray-600 mt-1 line-clamp-2">{record.content}</p>
      <p className="text-[10px] text-gray-400 mt-1">
        {format(parseISO(record.created_at), "MMM d, HH:mm")}
      </p>
    </Link>
  );
}

export default function CommunicationsInboxPage() {
  const { t } = useTranslation();
  const [channel, setChannel] = useState<string>("");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"conversations" | "records">("conversations");

  const convQuery = useQuery({
    queryKey: ["communication-inbox-conversations", channel, search],
    queryFn: () =>
      unifiedInboxApi
        .list({
          channel: (channel && channel !== "telegram"
            ? channel
            : undefined) as UnifiedInboxChannel | undefined,
          search: search || undefined,
          limit: 80,
        })
        .then((r) => r.data),
    enabled: view === "conversations",
  });

  const recordsQuery = useQuery({
    queryKey: ["communication-inbox-records", channel],
    queryFn: () =>
      communicationHubApi
        .listInbox({ channel: channel || undefined, limit: 80 })
        .then((r) => r.data),
    enabled: view === "records",
  });

  const threadsQuery = useQuery({
    queryKey: ["communication-inbox-threads", channel],
    queryFn: () =>
      communicationsApi
        .listThreads({ channel: (channel || undefined) as CommunicationChannel, limit: 50 })
        .then((r) => r.data),
  });

  const conversations = normalizeList<UnifiedConversation>(convQuery.data);
  const records = normalizeList<CommunicationRecord>(recordsQuery.data);
  const threads = normalizeList<CommunicationThread>(threadsQuery.data);

  const filteredThreads = useMemo(() => {
    if (!search.trim()) return threads;
    const q = search.toLowerCase();
    return threads.filter(
      (th) =>
        th.title.toLowerCase().includes(q) ||
        (th.contact_name ?? "").toLowerCase().includes(q),
    );
  }, [threads, search]);

  const isLoading = view === "conversations" ? convQuery.isLoading : recordsQuery.isLoading;
  const isError = view === "conversations" ? convQuery.isError : recordsQuery.isError;

  return (
    <PageShell>
      <PageHeader
        title={t("communicationsHub.inboxTitle")}
        subtitle={t("communicationsHub.inboxSubtitle")}
        icon={Inbox}
        actions={
          <Link href="/communications/contacts/new" className="btn-primary text-sm flex items-center gap-1.5">
            <Plus size={14} />
            {t("communications.newThread")}
          </Link>
        }
      />
      <CommunicationsSubNav />

      <div className="card p-4 space-y-3 mt-4">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setView("conversations")}
            className={cn(
              "text-sm px-3 py-1.5 rounded-lg border",
              view === "conversations"
                ? "bg-brand-50 border-brand-200 text-brand-800"
                : "border-gray-200 text-gray-600",
            )}
          >
            {t("communicationsHub.viewConversations")}
          </button>
          <button
            type="button"
            onClick={() => setView("records")}
            className={cn(
              "text-sm px-3 py-1.5 rounded-lg border",
              view === "records"
                ? "bg-brand-50 border-brand-200 text-brand-800"
                : "border-gray-200 text-gray-600",
            )}
          >
            {t("communicationsHub.viewRecords")}
          </button>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
          <select
            className="input text-sm"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
          >
            <option value="">{t("communicationsHub.allChannels")}</option>
            {CHANNELS.map((ch) => (
              <option key={ch} value={ch}>
                {CHANNEL_LABELS[ch as CommunicationChannel] ?? ch}
              </option>
            ))}
          </select>
          {view === "conversations" && (
            <div className="relative sm:col-span-2">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                className="input text-sm pl-8 w-full"
                placeholder={t("communications.searchPlaceholder")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          )}
        </div>

        <p className="text-xs text-gray-500 flex items-center gap-1.5">
          <MessagesSquare size={12} />
          {t("communicationsHub.providerNote")}
        </p>
      </div>

      {isLoading ? (
        <LoadingState message={t("communications.loadingThreads")} className="mt-4" />
      ) : isError ? (
        <ErrorState message={t("communicationsHub.loadError")} className="mt-4" />
      ) : view === "conversations" ? (
        <PageSection title={t("communicationsHub.unifiedInbox")} className="mt-4">
          {conversations.length === 0 ? (
            <EmptyState
              title={t("communications.emptyThreads")}
              description={t("communicationsHub.inboxEmptyHint")}
            />
          ) : (
            <div className="space-y-2">
              {conversations.map((c) => (
                <UnifiedRow key={c.id} conv={c} />
              ))}
            </div>
          )}
        </PageSection>
      ) : (
        <PageSection title={t("communicationsHub.communicationRecords")} className="mt-4">
          {records.length === 0 ? (
            <EmptyState title={t("communicationsHub.emptyRecords")} />
          ) : (
            <div className="space-y-2">
              {records.map((r) => (
                <RecordRow key={r.id} record={r} />
              ))}
            </div>
          )}
        </PageSection>
      )}

      {filteredThreads.length > 0 && (
        <PageSection title={t("common.threads")} className="mt-6">
          <div className="space-y-2">
            {filteredThreads.slice(0, 10).map((th) => (
              <Link
                key={th.id}
                href={`/communications/threads/${th.id}`}
                className="block card p-3 hover:ring-1 hover:ring-brand-200"
              >
                <p className="text-sm font-medium">{th.title}</p>
                <p className="text-xs text-gray-500">{th.contact_name} · {th.channel}</p>
              </Link>
            ))}
          </div>
        </PageSection>
      )}
    </PageShell>
  );
}
