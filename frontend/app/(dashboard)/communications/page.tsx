"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  AlertCircle,
  CalendarClock,
  Handshake,
  Inbox,
  MessageSquare,
  MessagesSquare,
  TrendingUp,
  Users,
} from "lucide-react";
import {
  communicationHubApi,
  type CommunicationConversationPreview,
  type CommunicationDashboard,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  KpiCard,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";

function ConversationRow({ conv }: { conv: CommunicationConversationPreview }) {
  return (
    <Link
      href={`/communications/threads/${conv.thread_id}`}
      className="block card p-3 hover:ring-1 hover:ring-brand-200 transition-shadow"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">{conv.title}</p>
          <p className="text-xs text-gray-500 truncate">
            {conv.contact_name ?? "—"} · {conv.channel}
          </p>
        </div>
        {conv.unread_count > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-100 text-red-800 font-medium shrink-0">
            {conv.unread_count}
          </span>
        )}
      </div>
      {conv.last_message_preview && (
        <p className="text-xs text-gray-600 mt-1 line-clamp-2">{conv.last_message_preview}</p>
      )}
      {conv.last_message_at && (
        <p className="text-[10px] text-gray-400 mt-1">
          {format(parseISO(conv.last_message_at), "MMM d, HH:mm")}
        </p>
      )}
    </Link>
  );
}

export default function CommunicationsDashboardPage() {
  const { t } = useTranslation();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["communication-hub-dashboard"],
    queryFn: () => communicationHubApi.dashboard().then((r) => r.data),
  });

  if (isLoading) {
    return (
      <PageShell>
        <LoadingState message={t("communicationsHub.loadingDashboard")} />
      </PageShell>
    );
  }

  if (isError || !data) {
    return (
      <PageShell>
        <ErrorState message={t("communicationsHub.loadError")} onRetry={() => refetch()} />
      </PageShell>
    );
  }

  const dash = data as CommunicationDashboard;
  const { kpis } = dash;

  return (
    <PageShell>
      <PageHeader
        title={t("communicationsHub.dashboardTitle")}
        subtitle={t("communicationsHub.dashboardSubtitle")}
        icon={MessagesSquare}
      />

      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3 mt-4">
        <KpiCard
          label={t("communicationsHub.kpi.totalCommunications")}
          value={kpis.total_communications}
          icon={MessageSquare}
          href="/communications/inbox"
        />
        <KpiCard
          label={t("communicationsHub.kpi.thisWeek")}
          value={kpis.communications_this_week}
          icon={TrendingUp}
          iconClassName="bg-sky-50 text-sky-600"
        />
        <KpiCard
          label={t("communicationsHub.kpi.unanswered")}
          value={kpis.unanswered_conversations}
          icon={AlertCircle}
          iconClassName="bg-red-50 text-red-600"
          href="/communications/inbox"
        />
        <KpiCard
          label={t("communicationsHub.kpi.followUpsToday")}
          value={kpis.follow_ups_due_today}
          icon={CalendarClock}
          iconClassName="bg-amber-50 text-amber-600"
          href="/communications/followups"
        />
        <KpiCard
          label={t("communicationsHub.kpi.activeBuyers")}
          value={kpis.active_buyers}
          icon={Users}
          iconClassName="bg-emerald-50 text-emerald-600"
          href="/buyers"
        />
        <KpiCard
          label={t("communicationsHub.kpi.activeNegotiations")}
          value={kpis.active_negotiations}
          icon={Handshake}
          iconClassName="bg-violet-50 text-violet-600"
          href="/crm"
        />
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mt-6">
        <PageSection
          title={t("communicationsHub.recentConversations")}
          action={
            <Link href="/communications/inbox" className="text-xs text-brand-600 hover:underline">
              {t("common.viewAll")}
            </Link>
          }
        >
          {dash.recent_conversations.length === 0 ? (
            <EmptyState title={t("communicationsHub.emptyConversations")} />
          ) : (
            <div className="space-y-2">
              {dash.recent_conversations.map((c) => (
                <ConversationRow key={c.id} conv={c} />
              ))}
            </div>
          )}
        </PageSection>

        <PageSection title={t("communicationsHub.unanswered")}>
          {dash.unanswered.length === 0 ? (
            <EmptyState title={t("communicationsHub.emptyUnanswered")} />
          ) : (
            <div className="space-y-2">
              {dash.unanswered.map((c) => (
                <ConversationRow key={c.id} conv={c} />
              ))}
            </div>
          )}
        </PageSection>
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mt-6">
        <PageSection
          title={t("communicationsHub.followUpsDue")}
          action={
            <Link href="/communications/followups" className="text-xs text-brand-600 hover:underline">
              {t("common.viewAll")}
            </Link>
          }
        >
          {dash.follow_ups_due.length === 0 ? (
            <EmptyState title={t("communicationsHub.emptyFollowUps")} />
          ) : (
            <div className="space-y-2">
              {dash.follow_ups_due.map((fu) => (
                <div key={fu.id} className="card p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-gray-900">{fu.title}</p>
                    <StatusBadge variant={fu.is_overdue ? "danger" : "warning"}>
                      {fu.is_overdue ? t("communicationsHub.overdue") : t("communicationsHub.today")}
                    </StatusBadge>
                  </div>
                  {fu.assigned_user && (
                    <p className="text-xs text-gray-500 mt-1">{fu.assigned_user}</p>
                  )}
                  <p className="text-[10px] text-gray-400 mt-1">
                    {format(parseISO(fu.due_date), "MMM d, HH:mm")}
                  </p>
                </div>
              ))}
            </div>
          )}
        </PageSection>

        <PageSection title={t("communicationsHub.recentActivity")}>
          {dash.recent_activity.length === 0 ? (
            <EmptyState title={t("communicationsHub.emptyActivity")} />
          ) : (
            <div className="space-y-2">
              {dash.recent_activity.map((a) => (
                <div key={a.id} className="card p-3 flex gap-3">
                  <Inbox size={16} className="text-brand-500 shrink-0 mt-0.5" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{a.title}</p>
                    {a.subtitle && (
                      <p className="text-xs text-gray-500 line-clamp-1">{a.subtitle}</p>
                    )}
                    <p className="text-[10px] text-gray-400 mt-1">
                      {format(parseISO(a.occurred_at), "MMM d, HH:mm")}
                      {a.channel ? ` · ${a.channel}` : ""}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </PageSection>
      </div>

      {Object.keys(dash.statistics).length > 0 && (
        <PageSection title={t("communicationsHub.statistics")} className="mt-6">
          <div className="flex flex-wrap gap-2">
            {Object.entries(dash.statistics).map(([key, val]) => (
              <span
                key={key}
                className="text-xs px-2 py-1 rounded-lg bg-gray-50 border border-gray-100 text-gray-700"
              >
                {key.replace(/_/g, " ")}: <strong>{val}</strong>
              </span>
            ))}
          </div>
        </PageSection>
      )}
    </PageShell>
  );
}
