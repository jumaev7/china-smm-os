"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  AlertCircle,
  CalendarClock,
  MessageCircle,
  MessagesSquare,
  Sparkles,
  TrendingUp,
  Users,
  Wifi,
} from "lucide-react";
import toast from "react-hot-toast";
import { WeChatSubNav } from "@/components/wechat/WeChatSubNav";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  KpiCard,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { wechatApi, type WeChatDashboard } from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  connected: "success",
  not_connected: "neutral",
  sync_error: "danger",
  disabled: "warning",
};

export default function WeChatDashboardPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["wechat-dashboard"],
    queryFn: () => wechatApi.dashboard().then((r) => r.data),
  });

  const seedMutation = useMutation({
    mutationFn: () => wechatApi.seedDemo().then((r) => r.data),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["wechat-dashboard"] });
      toast.success(result.message);
    },
    onError: (err: Error) => toast.error(err.message || "Demo seed failed"),
  });

  if (isLoading) {
    return (
      <PageShell>
        <LoadingState message={t("wechat.loadingDashboard")} />
      </PageShell>
    );
  }

  if (isError || !data) {
    return (
      <PageShell>
        <ErrorState message={t("wechat.loadError")} onRetry={() => refetch()} />
      </PageShell>
    );
  }

  const dash = data as WeChatDashboard;
  const { connection, kpis } = dash;

  return (
    <PageShell>
      <PageHeader
        title={t("wechat.dashboardTitle")}
        subtitle={t("wechat.dashboardSubtitle")}
        icon={MessageCircle}
        actions={
          connection.demo_mode ? (
            <button
              type="button"
              className="btn-secondary text-sm"
              disabled={seedMutation.isPending}
              onClick={() => seedMutation.mutate()}
            >
              {seedMutation.isPending ? t("common.loading") : t("wechat.seedDemo")}
            </button>
          ) : undefined
        }
      />
      <WeChatSubNav />

      <div className="mt-4 card p-4 flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2 rounded-lg bg-emerald-50 text-emerald-600">
            <Wifi size={18} />
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-900">{t("wechat.connectionStatus")}</p>
            <div className="flex flex-wrap items-center gap-2 mt-1">
              <StatusBadge variant={STATUS_VARIANT[connection.overall_status] ?? "neutral"}>
                {t(`wechat.accountStatus.${connection.overall_status}`)}
              </StatusBadge>
              {connection.demo_mode && (
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-100">
                  {t("wechat.demoMode")}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="sm:ml-auto text-xs text-gray-500 space-y-0.5">
          <p>
            {t("wechat.accountsConnected")}: {connection.accounts_connected}/{connection.accounts_total}
          </p>
          {connection.last_sync_at && (
            <p>{t("wechat.lastSync")}: {format(parseISO(connection.last_sync_at), "MMM d, HH:mm")}</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3 mt-4">
        <KpiCard
          label={t("wechat.kpi.totalContacts")}
          value={kpis.total_contacts}
          icon={Users}
          href="/wechat/contacts"
        />
        <KpiCard
          label={t("wechat.kpi.activeConversations")}
          value={kpis.active_conversations}
          icon={MessagesSquare}
          href="/wechat/messages"
        />
        <KpiCard
          label={t("wechat.kpi.newThisWeek")}
          value={kpis.new_conversations_this_week}
          icon={TrendingUp}
          iconClassName="bg-sky-50 text-sky-600"
        />
        <KpiCard
          label={t("wechat.kpi.opportunities")}
          value={kpis.opportunities_discovered}
          icon={Sparkles}
          iconClassName="bg-violet-50 text-violet-600"
        />
        <KpiCard
          label={t("wechat.kpi.followUps")}
          value={kpis.follow_ups_required}
          icon={CalendarClock}
          iconClassName="bg-amber-50 text-amber-600"
          href="/communications/followups"
        />
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mt-4">
        <PageSection title={t("wechat.linkedAccounts")}>
          {dash.linked_accounts.length === 0 ? (
            <EmptyState message={t("wechat.noAccounts")} />
          ) : (
            <ul className="space-y-2">
              {dash.linked_accounts.map((acc) => (
                <li key={acc.id} className="card p-3 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{acc.account_name}</p>
                    <p className="text-xs text-gray-500">
                      {acc.account_type.replace(/_/g, " ")}
                      {acc.provider ? ` · ${acc.provider}` : ""}
                    </p>
                  </div>
                  <StatusBadge variant={STATUS_VARIANT[acc.status] ?? "neutral"}>
                    {t(`wechat.accountStatus.${acc.status}`)}
                  </StatusBadge>
                </li>
              ))}
            </ul>
          )}
          <Link href="/wechat/accounts" className="text-xs text-brand-700 mt-2 inline-block">
            {t("common.viewAll")} →
          </Link>
        </PageSection>

        <PageSection title={t("wechat.recentActivity")}>
          {dash.recent_activity.length === 0 ? (
            <EmptyState message={t("wechat.noActivity")} />
          ) : (
            <ul className="space-y-2">
              {dash.recent_activity.map((item) => (
                <li key={item.id}>
                  <Link
                    href={`/wechat/messages?thread=${item.thread_id}`}
                    className="card p-3 block hover:ring-1 hover:ring-emerald-200 transition-shadow"
                  >
                    <p className="text-sm font-medium text-gray-900 truncate">{item.title}</p>
                    <p className="text-xs text-gray-500 truncate">
                      {item.subtitle ?? "—"} · {item.channel}
                    </p>
                    <p className="text-[10px] text-gray-400 mt-1">
                      {format(parseISO(item.occurred_at), "MMM d, HH:mm")}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </PageSection>
      </div>

      <div className="mt-4 card p-4 border-dashed border-emerald-100 bg-emerald-50/30">
        <div className="flex items-start gap-2">
          <AlertCircle size={16} className="text-emerald-700 mt-0.5 shrink-0" />
          <div className="text-xs text-gray-600 space-y-1">
            <p className="font-medium text-gray-800">{t("wechat.hubIntegrationTitle")}</p>
            <p>{t("wechat.hubIntegrationNote")}</p>
            <Link href="/communications" className="text-brand-700 inline-block">
              {t("wechat.openCommunicationHub")} →
            </Link>
          </div>
        </div>
      </div>
    </PageShell>
  );
}
