"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { analyticsApi, Platform } from "@/lib/api";
import { PLATFORM_CONFIG, cn } from "@/lib/utils";
import { SimpleBarChart, HorizontalBarChart } from "@/components/analytics/SimpleBarChart";
import {
  BarChart3,
  FileText,
  CalendarClock,
  CheckCircle2,
  XCircle,
  Activity,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { format, parseISO } from "date-fns";

function StatCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: number | string;
  icon: LucideIcon;
  color: string;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
          <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
        </div>
        <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center", color)}>
          <Icon size={18} />
        </div>
      </div>
    </div>
  );
}

function formatDayLabel(isoDate: string): string {
  try {
    return format(parseISO(isoDate), "MMM d");
  } catch {
    return isoDate.slice(5);
  }
}

export default function AnalyticsPage() {
  const router = useRouter();

  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ["analytics-overview"],
    queryFn: () => analyticsApi.overview().then((r) => r.data),
  });

  const { data: platforms, isLoading: platformsLoading } = useQuery({
    queryKey: ["analytics-platforms"],
    queryFn: () => analyticsApi.platforms().then((r) => r.data),
  });

  const { data: activity, isLoading: activityLoading } = useQuery({
    queryKey: ["analytics-activity"],
    queryFn: () => analyticsApi.activity().then((r) => r.data),
  });

  const postsChartData =
    overview?.posts_over_time.map((d) => ({
      label: formatDayLabel(d.date),
      value: d.count,
    })) ?? [];

  const publishingChartData =
    activity?.daily_publishing.map((d) => ({
      label: formatDayLabel(d.date),
      value: d.attempts,
      sublabel: `${d.success} ok`,
    })) ?? [];

  const platformBarData =
    platforms?.platforms.map((p) => ({
      label: PLATFORM_CONFIG[p.platform]?.label ?? p.platform,
      value: p.post_count,
      sublabel: `${p.success_count}/${p.attempt_count} publishes`,
    })) ?? [];

  const clientBarData =
    overview?.most_active_clients.map((c) => ({
      label: c.company_name,
      value: c.post_count,
    })) ?? [];

  const isLoading = overviewLoading || platformsLoading || activityLoading;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center gap-2 mb-1">
        <BarChart3 size={22} className="text-brand-600" />
        <h1 className="text-xl font-semibold text-gray-900">Analytics</h1>
      </div>
      <p className="text-sm text-gray-500 mb-6">
        Publishing performance and content activity (last 30 days)
      </p>

      {isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-4 h-24 animate-pulse bg-gray-50" />
          ))}
        </div>
      ) : (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <StatCard
              label="Total posts"
              value={overview?.total_posts ?? 0}
              icon={FileText}
              color="bg-slate-100 text-slate-600"
            />
            <StatCard
              label="Scheduled"
              value={overview?.scheduled_posts ?? 0}
              icon={CalendarClock}
              color="bg-purple-100 text-purple-600"
            />
            <StatCard
              label="Published"
              value={overview?.published_posts ?? 0}
              icon={CheckCircle2}
              color="bg-emerald-100 text-emerald-600"
            />
            <StatCard
              label="Failed"
              value={overview?.failed_posts ?? 0}
              icon={XCircle}
              color="bg-red-100 text-red-600"
            />
          </div>

          {/* Posts per platform — card row */}
          <div className="card p-4 mb-6">
            <h2 className="text-sm font-semibold text-gray-900 mb-3">Posts per platform</h2>
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
                        {p.attempt_count} publish{p.attempt_count !== 1 ? "es" : ""}
                      </p>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-gray-400">No platform data yet.</p>
            )}
          </div>

          {/* Charts row */}
          <div className="grid md:grid-cols-2 gap-4 mb-6">
            <div className="card p-4">
              <h2 className="text-sm font-semibold text-gray-900 mb-1">Posts over time</h2>
              <p className="text-[10px] text-gray-400 mb-3">New content created per day</p>
              <SimpleBarChart data={postsChartData} barClassName="bg-brand-500" />
            </div>

            <div className="card p-4">
              <h2 className="text-sm font-semibold text-gray-900 mb-1">Publishing success rate</h2>
              <div className="flex items-end gap-3 mb-4">
                <span className="text-4xl font-bold text-brand-700 tabular-nums">
                  {overview?.publishing_success_rate ?? 0}%
                </span>
                <span className="text-xs text-gray-500 pb-1">
                  {overview?.publish_attempts_success ?? 0} / {overview?.publish_attempts_total ?? 0}{" "}
                  attempts
                </span>
              </div>
              <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 rounded-full transition-all"
                  style={{ width: `${overview?.publishing_success_rate ?? 0}%` }}
                />
              </div>
              <p className="text-[10px] text-gray-400 mt-4 mb-2">Daily publish attempts</p>
              <SimpleBarChart
                data={publishingChartData}
                maxBars={14}
                barClassName="bg-emerald-500"
              />
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4 mb-6">
            <div className="card p-4">
              <h2 className="text-sm font-semibold text-gray-900 mb-3">Posts by platform</h2>
              <HorizontalBarChart data={platformBarData} barClassName="bg-brand-400" />
            </div>

            <div className="card p-4">
              <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1.5">
                <TrendingUp size={14} className="text-brand-600" />
                Most active clients
              </h2>
              <HorizontalBarChart data={clientBarData} barClassName="bg-violet-500" />
            </div>
          </div>
        </>
      )}

      {/* Activity feed */}
      <div className="card p-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1.5">
          <Activity size={14} className="text-brand-600" />
          Recent publishing activity
        </h2>
        {activityLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-12 bg-gray-50 rounded animate-pulse" />
            ))}
          </div>
        ) : !activity?.recent_activity.length ? (
          <p className="text-xs text-gray-400 py-4 text-center">
            No publish attempts yet. Test publish from a content item to see activity here.
          </p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {activity.recent_activity.map((item) => {
              const cfg = PLATFORM_CONFIG[item.platform as Platform];
              const ok = item.status === "success";
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => router.push(`/content/${item.content_id}`)}
                    className="w-full flex items-start gap-3 py-3 text-left hover:bg-gray-50 rounded-lg px-2 -mx-2 transition-colors"
                  >
                    <span
                      className={cn(
                        "w-2 h-2 rounded-full mt-1.5 shrink-0",
                        ok ? "bg-emerald-500" : "bg-red-500",
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-gray-900">
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
                      <p className="text-xs text-gray-500 truncate">{item.content_title}</p>
                      {item.error && (
                        <p className="text-[10px] text-red-500 truncate mt-0.5">{item.error}</p>
                      )}
                    </div>
                    <time className="text-[10px] text-gray-400 shrink-0">
                      {format(parseISO(item.created_at), "MMM d, HH:mm")}
                    </time>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
