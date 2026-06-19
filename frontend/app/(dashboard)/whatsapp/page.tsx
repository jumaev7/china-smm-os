"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  AlertCircle,
  CalendarClock,
  MessagesSquare,
  Phone,
  Sparkles,
  TrendingUp,
  Users,
  Wifi,
} from "lucide-react";
import toast from "react-hot-toast";
import { WhatsAppSubNav } from "@/components/whatsapp/WhatsAppSubNav";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  KpiCard,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { whatsappApi, type WhatsAppDashboard } from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  connected: "success",
  not_connected: "neutral",
  sync_error: "danger",
  disabled: "warning",
};

export default function WhatsAppDashboardPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["whatsapp-dashboard"],
    queryFn: () => whatsappApi.dashboard().then((r) => r.data),
  });

  const seedMutation = useMutation({
    mutationFn: () => whatsappApi.seedDemo().then((r) => r.data),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["whatsapp-dashboard"] });
      toast.success(result.message);
    },
    onError: (err: Error) => toast.error(err.message || "Demo seed failed"),
  });

  if (isLoading) {
    return (
      <PageShell>
        <LoadingState message={t("whatsapp.loadingDashboard")} />
      </PageShell>
    );
  }

  if (isError || !data) {
    return (
      <PageShell>
        <ErrorState message={t("whatsapp.loadError")} onRetry={() => refetch()} />
      </PageShell>
    );
  }

  const dash = data as WhatsAppDashboard;
  const { connection, kpis } = dash;

  return (
    <PageShell>
      <PageHeader
        title={t("whatsapp.dashboardTitle")}
        subtitle={t("whatsapp.dashboardSubtitle")}
        icon={Phone}
        actions={
          connection.demo_mode ? (
            <button
              type="button"
              className="btn-secondary text-sm"
              disabled={seedMutation.isPending}
              onClick={() => seedMutation.mutate()}
            >
              {seedMutation.isPending ? t("common.loading") : t("whatsapp.seedDemo")}
            </button>
          ) : undefined
        }
      />
      <WhatsAppSubNav />

      <div className="mt-4 card p-4 flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2 rounded-lg bg-green-50 text-green-600">
            <Wifi size={18} />
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-900">{t("whatsapp.connectionStatus")}</p>
            <div className="flex flex-wrap items-center gap-2 mt-1">
              <StatusBadge variant={STATUS_VARIANT[connection.overall_status] ?? "neutral"}>
                {t(`whatsapp.accountStatus.${connection.overall_status}`)}
              </StatusBadge>
              {connection.demo_mode && (
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-100">
                  {t("whatsapp.demoMode")}
                </span>
              )}
              {connection.webhook_configured && (
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-sky-50 text-sky-800 border border-sky-100">
                  Webhook ready
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="sm:ml-auto text-xs text-gray-500 space-y-0.5">
          <p>
            {t("whatsapp.accountsConnected")}: {connection.accounts_connected}/{connection.accounts_total}
          </p>
          {connection.last_sync_at && (
            <p>{t("whatsapp.lastSync")}: {format(parseISO(connection.last_sync_at), "MMM d, HH:mm")}</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3 mt-4">
        <KpiCard label={t("whatsapp.kpi.totalContacts")} value={kpis.total_contacts} icon={Users} href="/whatsapp/contacts" />
        <KpiCard label={t("whatsapp.kpi.activeConversations")} value={kpis.active_conversations} icon={MessagesSquare} href="/whatsapp/messages" />
        <KpiCard label={t("whatsapp.kpi.newThisWeek")} value={kpis.new_conversations_this_week} icon={TrendingUp} iconClassName="bg-sky-50 text-sky-600" />
        <KpiCard label={t("whatsapp.kpi.opportunities")} value={kpis.opportunities_discovered} icon={Sparkles} iconClassName="bg-violet-50 text-violet-600" />
        <KpiCard label={t("whatsapp.kpi.followUps")} value={kpis.follow_ups_required} icon={CalendarClock} iconClassName="bg-amber-50 text-amber-600" href="/communications/followups" />
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mt-4">
        <PageSection title={t("whatsapp.linkedAccounts")}>
          {dash.linked_accounts.length === 0 ? (
            <EmptyState message={t("whatsapp.noAccounts")} />
          ) : (
            <ul className="space-y-2">
              {dash.linked_accounts.map((acc) => (
                <li key={acc.id} className="card p-3 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{acc.account_name}</p>
                    <p className="text-xs text-gray-500 truncate">
                      {acc.phone_number || "—"}
                      {acc.business_display_name ? ` · ${acc.business_display_name}` : ""}
                    </p>
                  </div>
                  <StatusBadge variant={STATUS_VARIANT[acc.status] ?? "neutral"}>
                    {t(`whatsapp.accountStatus.${acc.status}`)}
                  </StatusBadge>
                </li>
              ))}
            </ul>
          )}
          <Link href="/whatsapp/accounts" className="text-xs text-brand-700 mt-2 inline-block">
            {t("common.viewAll")} →
          </Link>
        </PageSection>

        <PageSection title={t("whatsapp.recentActivity")}>
          {dash.recent_activity.length === 0 ? (
            <EmptyState message={t("whatsapp.noActivity")} />
          ) : (
            <ul className="space-y-2">
              {dash.recent_activity.map((item) => (
                <li key={item.id}>
                  <Link
                    href={`/whatsapp/messages?thread=${item.thread_id}`}
                    className="card p-3 block hover:ring-1 hover:ring-green-200 transition-shadow"
                  >
                    <p className="text-sm font-medium text-gray-900 truncate">{item.title}</p>
                    <p className="text-xs text-gray-500 truncate">
                      {item.subtitle ?? "—"} · WhatsApp
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

      <div className="mt-4 card p-4 border-dashed border-green-100 bg-green-50/30">
        <div className="flex items-start gap-2">
          <AlertCircle size={16} className="text-green-700 mt-0.5 shrink-0" />
          <div className="text-xs text-gray-600 space-y-1">
            <p className="font-medium text-gray-800">{t("whatsapp.hubIntegrationTitle")}</p>
            <p>{t("whatsapp.hubIntegrationNote")}</p>
            <Link href="/communications" className="text-brand-700 inline-block">
              {t("whatsapp.openCommunicationHub")} →
            </Link>
          </div>
        </div>
      </div>
    </PageShell>
  );
}
