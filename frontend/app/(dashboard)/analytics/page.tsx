"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { analyticsApi, Platform } from "@/lib/api";
import { PLATFORM_CONFIG, cn } from "@/lib/utils";
import { SimpleBarChart, HorizontalBarChart } from "@/components/analytics/SimpleBarChart";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { KpiCard, PageHeader, PageSection, PageShell } from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";
import {
  BarChart3,
  FileText,
  CalendarClock,
  CheckCircle2,
  XCircle,
  Plus,
} from "lucide-react";
import { format, parseISO } from "date-fns";

function formatDayLabel(isoDate: string): string {
  try {
    return format(parseISO(isoDate), "MMM d");
  } catch {
    return isoDate.slice(5);
  }
}

const QUERY_OPTS = { staleTime: 60_000, refetchOnWindowFocus: false } as const;

export default function AnalyticsPage() {
  const router = useRouter();
  const { t } = useTranslation();

  const overviewQuery = useQuery({
    queryKey: ["analytics-overview"],
    queryFn: () => analyticsApi.overview().then((r) => r.data),
    ...QUERY_OPTS,
  });

  const platformsQuery = useQuery({
    queryKey: ["analytics-platforms"],
    queryFn: () => analyticsApi.platforms().then((r) => r.data),
    ...QUERY_OPTS,
  });

  const activityQuery = useQuery({
    queryKey: ["analytics-activity"],
    queryFn: () => analyticsApi.activity().then((r) => r.data),
    ...QUERY_OPTS,
  });

  const overview = overviewQuery.data;
  const platforms = platformsQuery.data;
  const activity = activityQuery.data;

  const postsChartData =
    overview?.posts_over_time.map((d) => ({
      label: formatDayLabel(d.date),
      value: d.count,
    })) ?? [];

  const publishingChartData =
    activity?.daily_publishing.map((d) => ({
      label: formatDayLabel(d.date),
      value: d.attempts,
      sublabel: t("analyticsPage.okCount", { count: d.success }),
    })) ?? [];

  const platformBarData =
    platforms?.platforms.map((p) => ({
      label: PLATFORM_CONFIG[p.platform]?.label ?? p.platform,
      value: p.post_count,
      sublabel: t("analyticsPage.publishRatio", {
        success: p.success_count,
        total: p.attempt_count,
      }),
    })) ?? [];

  const clientBarData =
    overview?.most_active_clients.map((c) => ({
      label: c.company_name,
      value: c.post_count,
    })) ?? [];

  const isInitialLoading = overviewQuery.isLoading;
  const isError = overviewQuery.isError;
  const hasNoData =
    !isInitialLoading &&
    !isError &&
    (overview?.total_posts ?? 0) === 0 &&
    (overview?.publish_attempts_total ?? 0) === 0;

  if (isInitialLoading) {
    return (
      <PageShell>
        <LoadingState message={t("analyticsPage.loading")} />
      </PageShell>
    );
  }

  if (isError) {
    return (
      <PageShell>
        <ErrorState
          error={overviewQuery.error}
          onRetry={() => {
            overviewQuery.refetch();
            platformsQuery.refetch();
            activityQuery.refetch();
          }}
        />
      </PageShell>
    );
  }

  return (
    <PageShell wide className="space-y-5">
      <PageHeader
        title={t("analyticsPage.title")}
        subtitle={t("analyticsPage.subtitle")}
        icon={BarChart3}
      />

      {hasNoData ? (
        <EmptyState
          title={t("analyticsPage.emptyTitle")}
          description={t("analyticsPage.emptyDescription")}
          action={
            <div className="flex flex-wrap gap-2 justify-center mt-2">
              <Link href="/content" className="btn-primary text-sm">
                <Plus size={14} />
                {t("analyticsPage.goToContent")}
              </Link>
              <Link href="/publishing" className="btn-secondary text-sm">
                {t("analyticsPage.goToPublishing")}
              </Link>
            </div>
          }
        />
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard
              label={t("analyticsPage.kpiTotalPosts")}
              value={overview?.total_posts ?? 0}
              icon={FileText}
              iconClassName="bg-slate-100 text-slate-600 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-300"
            />
            <KpiCard
              label={t("analyticsPage.kpiScheduled")}
              value={overview?.scheduled_posts ?? 0}
              icon={CalendarClock}
              iconClassName="bg-purple-100 text-purple-600 dark-tenant:bg-violet-500/15 dark-tenant:text-violet-400"
            />
            <KpiCard
              label={t("analyticsPage.kpiPublished")}
              value={overview?.published_posts ?? 0}
              icon={CheckCircle2}
              iconClassName="bg-emerald-100 text-emerald-600 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-400"
            />
            <KpiCard
              label={t("analyticsPage.kpiFailed")}
              value={overview?.failed_posts ?? 0}
              icon={XCircle}
              iconClassName="bg-red-100 text-red-600 dark-tenant:bg-red-500/15 dark-tenant:text-red-400"
            />
          </div>

          <PageSection title={t("analyticsPage.postsPerPlatform")}>
            <div className="card p-4">
            {platforms?.platforms.length ? (
              <div className="flex flex-wrap gap-3">
                {platforms.platforms.map((p) => {
                  const cfg = PLATFORM_CONFIG[p.platform as Platform];
                  return (
                    <div
                      key={p.platform}
                      className={cn(
                        "rounded-lg border px-3 py-2 min-w-[120px]",
                        cfg?.color ?? "bg-gray-50",
                      )}
                    >
                      <p className="text-xs font-bold">{cfg?.icon ?? p.platform}</p>
                      <p className="text-lg font-semibold tabular-nums">{p.post_count}</p>
                      <p className="text-[10px] opacity-70">
                        {t("analyticsPage.publishCount", { count: p.attempt_count })}
                      </p>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-gray-400 dark-tenant:text-slate-500">
                {t("analyticsPage.noPlatformData")}
              </p>
            )}
            </div>
          </PageSection>

          <div className="grid md:grid-cols-2 gap-4">
            <PageSection title={t("analyticsPage.postsOverTime")} description={t("analyticsPage.postsOverTimeHint")}>
              <div className="card p-4">
              <SimpleBarChart data={postsChartData} barClassName="bg-brand-500" />
              </div>
            </PageSection>

            <PageSection title={t("analyticsPage.successRate")}>
              <div className="card p-4">
              <div className="flex items-end gap-3 mb-4">
                <span className="text-4xl font-bold text-brand-700 tabular-nums dark-tenant:text-violet-300">
                  {overview?.publishing_success_rate ?? 0}%
                </span>
                <span className="text-xs text-gray-500 pb-1 dark-tenant:text-slate-400">
                  {t("analyticsPage.attemptsRatio", {
                    success: overview?.publish_attempts_success ?? 0,
                    total: overview?.publish_attempts_total ?? 0,
                  })}
                </span>
              </div>
              <div className="h-3 bg-gray-100 rounded-full overflow-hidden dark-tenant:bg-white/[0.06]">
                <div
                  className="h-full bg-emerald-500 rounded-full transition-all"
                  style={{ width: `${overview?.publishing_success_rate ?? 0}%` }}
                />
              </div>
              <p className="text-[10px] text-gray-400 mt-4 mb-2 dark-tenant:text-slate-500">
                {t("analyticsPage.dailyAttempts")}
              </p>
              <SimpleBarChart
                data={publishingChartData}
                maxBars={14}
                barClassName="bg-emerald-500"
              />
              </div>
            </PageSection>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <PageSection title={t("analyticsPage.postsByPlatform")}>
              <div className="card p-4">
              <HorizontalBarChart data={platformBarData} barClassName="bg-brand-400" />
              </div>
            </PageSection>

            <PageSection title={t("analyticsPage.mostActiveClients")}>
              <div className="card p-4">
              <HorizontalBarChart data={clientBarData} barClassName="bg-violet-500" />
              </div>
            </PageSection>
          </div>
        </>
      )}

      <PageSection title={t("analyticsPage.recentActivity")}>
        <div className="card p-4">
        {activityQuery.isLoading ? (
          <LoadingState variant="inline" message={t("common.loading")} />
        ) : !activity?.recent_activity.length ? (
          <EmptyState
            title={t("analyticsPage.noActivityTitle")}
            description={t("analyticsPage.noActivityDescription")}
            action={
              <Link href="/content" className="btn-primary text-sm mt-2">
                {t("analyticsPage.goToContent")}
              </Link>
            }
            className="p-6"
          />
        ) : (
          <ul className="divide-y divide-gray-100 dark-tenant:divide-white/[0.06]">
            {activity.recent_activity.map((item) => {
              const cfg = PLATFORM_CONFIG[item.platform as Platform];
              const ok = item.status === "success";
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => router.push(`/content/${item.content_id}`)}
                    className="w-full flex items-start gap-3 py-3 text-left hover:bg-gray-50 dark-tenant:hover:bg-white/[0.03] rounded-lg px-2 -mx-2 transition-colors"
                  >
                    <span
                      className={cn(
                        "w-2 h-2 rounded-full mt-1.5 shrink-0",
                        ok ? "bg-emerald-500" : "bg-red-500",
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-gray-900 dark-tenant:text-slate-100">
                          {item.company_name}
                        </span>
                        <span
                          className={cn(
                            "text-[10px] px-1.5 py-0.5 rounded font-bold",
                            cfg?.color ?? "bg-gray-100",
                          )}
                        >
                          {cfg?.label ?? item.platform}
                        </span>
                        <span
                          className={cn(
                            "text-[10px] font-medium",
                            ok ? "text-emerald-600" : "text-red-600",
                          )}
                        >
                          {item.status}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 truncate dark-tenant:text-slate-400">
                        {item.content_title}
                      </p>
                      {item.error && (
                        <p className="text-[10px] text-red-500 truncate mt-0.5">{item.error}</p>
                      )}
                    </div>
                    <time className="text-[10px] text-gray-400 shrink-0 dark-tenant:text-slate-500">
                      {format(parseISO(item.created_at), "MMM d, HH:mm")}
                    </time>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        </div>
      </PageSection>
    </PageShell>
  );
}
