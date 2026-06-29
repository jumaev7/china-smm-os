"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  Calendar,
  Clock,
  Facebook,
  FileText,
  Loader2,
  MessageSquare,
  Radio,
  X,
  type LucideIcon,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  crmPipelineApi,
  normalizeList,
  publishingApi,
  salesCrmApi,
  type CrmPipelineEvent,
  type CrmPipelinePublishingHealthSummary,
  type SalesDeal,
  type SalesDealStage,
} from "@/lib/api";
import {
  crmPipelineFmtMoney,
  crmPipelinePublishingStatus,
} from "@/lib/crm-pipeline";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";

const QUERY_ROOT = ["executive-crm-pipeline"];

function stageLabel(stage: SalesDealStage, t: (k: string) => string) {
  const key = `salesCrm.stage.${stage}`;
  const translated = t(key);
  return translated === key ? stage.replace(/_/g, " ") : translated;
}

function TimelineItem({ event }: { event: CrmPipelineEvent }) {
  return (
    <li className="relative pl-5 pb-4 last:pb-0">
      <span className="absolute left-0 top-1.5 w-2 h-2 rounded-full bg-violet-500 ring-4 ring-violet-500/10" />
      <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-100">{event.title}</p>
      {event.description && (
        <p className="text-xs text-gray-600 dark-tenant:text-slate-400 mt-0.5 whitespace-pre-wrap">
          {event.description}
        </p>
      )}
      <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500 mt-1">
        {format(parseISO(event.created_at), "MMM d, yyyy HH:mm")}
        {event.actor ? ` · ${event.actor}` : ""}
      </p>
    </li>
  );
}

function DrawerSection({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: LucideIcon;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark-tenant:text-slate-500 flex items-center gap-1.5">
        <Icon size={13} />
        {title}
      </h3>
      {children}
    </section>
  );
}

export function DealDrawer({
  deal,
  publishingHealth,
  metaConnected,
  onClose,
}: {
  deal: SalesDeal;
  publishingHealth: CrmPipelinePublishingHealthSummary;
  metaConnected: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [noteText, setNoteText] = useState("");
  const [meetingTitle, setMeetingTitle] = useState("");
  const [activeTab, setActiveTab] = useState<"timeline" | "notes" | "meetings" | "proposals">(
    "timeline",
  );

  const { data: timeline, isLoading: timelineLoading } = useQuery({
    queryKey: [...QUERY_ROOT, "timeline", deal.id],
    queryFn: () => crmPipelineApi.getDealTimeline(deal.id, { limit: 100 }).then((r) => r.data),
  });

  const { data: related } = useQuery({
    queryKey: [...QUERY_ROOT, "related", deal.id],
    queryFn: () => salesCrmApi.getDealRelated(deal.id).then((r) => r.data),
  });

  const { data: accountsData } = useQuery({
    queryKey: [...QUERY_ROOT, "publishing-accounts"],
    queryFn: () => publishingApi.listAccounts().then((r) => r.data),
    staleTime: 60_000,
  });

  const events = timeline?.items ?? [];
  const noteEvents = useMemo(
    () => events.filter((e) => e.event_type === "manual_note"),
    [events],
  );
  const meetingEvents = useMemo(
    () => events.filter((e) => e.event_type === "meeting_added"),
    [events],
  );
  const proposalEvents = useMemo(
    () =>
      events.filter((e) =>
        ["proposal_sent", "proposal_accepted", "proposal_rejected"].includes(e.event_type),
      ),
    [events],
  );

  const addNoteMutation = useMutation({
    mutationFn: (description: string) =>
      crmPipelineApi.addNote(deal.id, { description }),
    onSuccess: () => {
      toast.success(t("crmPipeline.noteAdded"));
      setNoteText("");
      qc.invalidateQueries({ queryKey: [...QUERY_ROOT, "timeline", deal.id] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const addMeetingMutation = useMutation({
    mutationFn: (title: string) =>
      crmPipelineApi.scheduleMeeting(deal.id, { title, advance_stage: true }),
    onSuccess: () => {
      toast.success(t("crmPipeline.meetingAdded"));
      setMeetingTitle("");
      qc.invalidateQueries({ queryKey: QUERY_ROOT });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const publishing = crmPipelinePublishingStatus(deal.stage);
  const accounts = normalizeList(accountsData) as Array<{
    id: string;
    platform: string;
    status: string;
    account_name: string;
    health?: string | null;
  }>;

  const tabs = [
    { id: "timeline" as const, label: t("crmPipeline.timeline") },
    { id: "notes" as const, label: t("crmPipeline.notes") },
    { id: "meetings" as const, label: t("crmPipeline.meetings") },
    { id: "proposals" as const, label: t("crmPipeline.proposals") },
  ];

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-30 backdrop-blur-[1px]"
        onClick={onClose}
        data-app-modal
        aria-hidden
      />
      <aside
        className={cn(
          "fixed inset-y-0 right-0 w-full max-w-lg z-40 flex flex-col",
          "bg-white border-l border-gray-200 shadow-2xl",
          "dark-tenant:bg-surface-dark-page dark-tenant:border-white/[0.08]",
        )}
      >
        <header className="shrink-0 p-4 border-b border-gray-100 dark-tenant:border-white/[0.06]">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs text-violet-600 dark-tenant:text-violet-400 font-medium uppercase tracking-wide">
                {stageLabel(deal.stage, t)}
              </p>
              <h2 className="text-lg font-semibold text-gray-900 dark-tenant:text-slate-100 mt-0.5 truncate">
                {deal.title}
              </h2>
              <p className="text-sm text-gray-500 dark-tenant:text-slate-400 truncate">
                {deal.customer_name || deal.lead_name || "—"}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark-tenant:hover:bg-white/[0.06] dark-tenant:hover:text-slate-200"
              aria-label={t("common.cancel")}
            >
              <X size={18} />
            </button>
          </div>

          <div className="grid grid-cols-3 gap-3 mt-4 text-center">
            <div className="rounded-lg bg-gray-50 dark-tenant:bg-white/[0.04] px-2 py-2">
              <p className="text-[10px] text-gray-500 dark-tenant:text-slate-500 uppercase">
                {t("salesCrm.value")}
              </p>
              <p className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100 tabular-nums">
                {crmPipelineFmtMoney(deal.value, deal.currency)}
              </p>
            </div>
            <div className="rounded-lg bg-gray-50 dark-tenant:bg-white/[0.04] px-2 py-2">
              <p className="text-[10px] text-gray-500 dark-tenant:text-slate-500 uppercase">
                {t("salesCrm.probability")}
              </p>
              <p className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100">
                {deal.probability}%
              </p>
            </div>
            <div className="rounded-lg bg-gray-50 dark-tenant:bg-white/[0.04] px-2 py-2">
              <p className="text-[10px] text-gray-500 dark-tenant:text-slate-500 uppercase">
                {t("salesCrm.expectedClose")}
              </p>
              <p className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100">
                {deal.expected_close_date
                  ? format(parseISO(deal.expected_close_date), "MMM d")
                  : "—"}
              </p>
            </div>
          </div>
        </header>

        <div className="shrink-0 px-4 py-3 border-b border-gray-100 dark-tenant:border-white/[0.06] space-y-3">
          <DrawerSection title={t("crmPipeline.publishingStatus")} icon={Radio}>
            <div className="flex flex-wrap gap-2 text-xs">
              <span
                className={cn(
                  "px-2 py-1 rounded-md font-medium",
                  publishing === "publishing"
                    ? "bg-teal-500/15 text-teal-700 dark-tenant:text-teal-400"
                    : publishing === "client"
                      ? "bg-emerald-500/15 text-emerald-700 dark-tenant:text-emerald-400"
                      : publishing === "expansion"
                        ? "bg-lime-500/15 text-lime-700 dark-tenant:text-lime-400"
                        : "bg-gray-100 text-gray-600 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-400",
                )}
              >
                {publishing !== "none"
                  ? t(`crmPipeline.publishing.${publishing}`)
                  : t("crmPipeline.publishing.none")}
              </span>
              <span className="px-2 py-1 rounded-md bg-gray-100 text-gray-600 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-400">
                {t("crmPipeline.accountsHealthy", {
                  healthy: publishingHealth.healthy_count,
                  total: publishingHealth.total_accounts,
                })}
              </span>
            </div>
          </DrawerSection>

          <DrawerSection title={t("crmPipeline.metaStatus")} icon={Facebook}>
            <div className="flex flex-wrap gap-2 text-xs">
              {metaConnected ? (
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-blue-500/15 text-blue-700 dark-tenant:text-blue-400 font-medium">
                  <Facebook size={12} />
                  {t("crmPipeline.metaConnected")}
                </span>
              ) : (
                <span className="px-2 py-1 rounded-md bg-gray-100 text-gray-500 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-500">
                  {t("crmPipeline.metaNotConnected")}
                </span>
              )}
              {accounts
                .filter((a) => a.platform === "facebook" || a.platform === "instagram")
                .slice(0, 4)
                .map((a) => (
                  <span
                    key={a.id}
                    className="px-2 py-1 rounded-md bg-white border border-gray-200 dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-elevated text-gray-600 dark-tenant:text-slate-400 capitalize"
                  >
                    {a.platform}: {a.status}
                  </span>
                ))}
            </div>
          </DrawerSection>
        </div>

        <div className="shrink-0 flex gap-1 px-4 pt-3 border-b border-gray-100 dark-tenant:border-white/[0.06]">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "px-3 py-2 text-xs font-medium rounded-t-lg transition-colors",
                activeTab === tab.id
                  ? "bg-violet-500/10 text-violet-700 dark-tenant:text-violet-400 border-b-2 border-violet-500"
                  : "text-gray-500 hover:text-gray-800 dark-tenant:text-slate-500 dark-tenant:hover:text-slate-300",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {activeTab === "timeline" && (
            <>
              {timelineLoading ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
                </div>
              ) : events.length === 0 ? (
                <p className="text-sm text-gray-400 dark-tenant:text-slate-500 text-center py-6">
                  {t("crmPipeline.noTimeline")}
                </p>
              ) : (
                <ul className="border-l border-gray-200 dark-tenant:border-white/[0.08] ml-1">
                  {events.map((event) => (
                    <TimelineItem key={event.id} event={event} />
                  ))}
                </ul>
              )}
            </>
          )}

          {activeTab === "notes" && (
            <div className="space-y-4">
              <form
                className="space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  const text = noteText.trim();
                  if (!text) return;
                  addNoteMutation.mutate(text);
                }}
              >
                <textarea
                  value={noteText}
                  onChange={(e) => setNoteText(e.target.value)}
                  rows={3}
                  placeholder={t("crmPipeline.notePlaceholder")}
                  className="w-full text-sm rounded-lg border border-gray-200 px-3 py-2 resize-none dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-200"
                />
                <button
                  type="submit"
                  disabled={addNoteMutation.isPending || !noteText.trim()}
                  className="btn-primary text-xs px-3 py-1.5 disabled:opacity-50"
                >
                  {addNoteMutation.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    t("crmPipeline.addNote")
                  )}
                </button>
              </form>
              {noteEvents.length > 0 && (
                <ul className="space-y-3">
                  {noteEvents.map((event) => (
                    <li
                      key={event.id}
                      className="rounded-lg border border-gray-100 p-3 dark-tenant:border-white/[0.06] dark-tenant:bg-surface-dark-elevated/50"
                    >
                      <p className="text-sm text-gray-800 dark-tenant:text-slate-200 whitespace-pre-wrap">
                        {event.description}
                      </p>
                      <p className="text-[10px] text-gray-400 mt-1">
                        {format(parseISO(event.created_at), "MMM d, yyyy HH:mm")}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {activeTab === "meetings" && (
            <div className="space-y-4">
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  const title = meetingTitle.trim();
                  if (!title) return;
                  addMeetingMutation.mutate(title);
                }}
              >
                <input
                  value={meetingTitle}
                  onChange={(e) => setMeetingTitle(e.target.value)}
                  placeholder={t("crmPipeline.meetingPlaceholder")}
                  className="flex-1 text-sm rounded-lg border border-gray-200 px-3 py-2 dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-200"
                />
                <button
                  type="submit"
                  disabled={addMeetingMutation.isPending || !meetingTitle.trim()}
                  className="btn-primary text-xs px-3 py-2 disabled:opacity-50 shrink-0"
                >
                  {addMeetingMutation.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    t("crmPipeline.schedule")
                  )}
                </button>
              </form>
              {meetingEvents.length === 0 ? (
                <p className="text-sm text-gray-400 dark-tenant:text-slate-500">
                  {t("crmPipeline.noMeetings")}
                </p>
              ) : (
                <ul className="space-y-2">
                  {meetingEvents.map((event) => (
                    <li
                      key={event.id}
                      className="flex items-start gap-2 rounded-lg border border-gray-100 p-3 dark-tenant:border-white/[0.06]"
                    >
                      <Calendar size={14} className="text-violet-500 mt-0.5 shrink-0" />
                      <div>
                        <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-100">
                          {event.title}
                        </p>
                        {event.description && (
                          <p className="text-xs text-gray-500 dark-tenant:text-slate-400">
                            {event.description}
                          </p>
                        )}
                        <p className="text-[10px] text-gray-400 mt-0.5 flex items-center gap-1">
                          <Clock size={10} />
                          {format(parseISO(event.created_at), "MMM d, yyyy HH:mm")}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {activeTab === "proposals" && (
            <div className="space-y-3">
              {proposalEvents.length > 0 && (
                <ul className="space-y-2">
                  {proposalEvents.map((event) => (
                    <li
                      key={event.id}
                      className="rounded-lg border border-gray-100 p-3 dark-tenant:border-white/[0.06]"
                    >
                      <div className="flex items-center gap-2">
                        <FileText size={14} className="text-indigo-500" />
                        <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-100">
                          {event.title}
                        </p>
                      </div>
                      {event.description && (
                        <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-1">
                          {event.description}
                        </p>
                      )}
                      <p className="text-[10px] text-gray-400 mt-1">
                        {format(parseISO(event.created_at), "MMM d, yyyy")}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
              {related?.related_proposals && related.related_proposals.length > 0 && (
                <ul className="space-y-2">
                  {related.related_proposals.map((p) => (
                    <li
                      key={p.entity_id}
                      className="flex items-center justify-between rounded-lg border border-gray-100 p-3 dark-tenant:border-white/[0.06]"
                    >
                      <div>
                        <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-100">
                          {p.label}
                        </p>
                        {p.status && (
                          <p className="text-xs text-gray-500 capitalize">{p.status}</p>
                        )}
                      </div>
                      {p.href && (
                        <a
                          href={p.href}
                          className="text-xs text-violet-600 dark-tenant:text-violet-400 hover:underline"
                        >
                          {t("common.open")}
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {proposalEvents.length === 0 &&
                (!related?.related_proposals || related.related_proposals.length === 0) && (
                  <p className="text-sm text-gray-400 dark-tenant:text-slate-500">
                    {t("crmPipeline.noProposals")}
                  </p>
                )}
            </div>
          )}

          {deal.notes && activeTab === "timeline" && (
            <DrawerSection title={t("salesCrm.notes")} icon={MessageSquare}>
              <p className="text-sm text-gray-700 dark-tenant:text-slate-300 whitespace-pre-wrap">
                {deal.notes}
              </p>
            </DrawerSection>
          )}
        </div>
      </aside>
    </>
  );
}
