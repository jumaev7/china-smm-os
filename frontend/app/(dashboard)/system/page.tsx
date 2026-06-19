"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Bot,
  Briefcase,
  Database,
  FileText,
  HardDrive,
  Loader2,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  Users,
  type LucideIcon,
} from "lucide-react";
import toast from "react-hot-toast";
import { systemApi, SystemHealth } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { UiHealthSection } from "@/components/system/UiHealthSection";
import { TelegramIngestionSettingsPanel } from "@/components/system/TelegramIngestionSettingsPanel";
import { PageHeader, PageShell } from "@/components/ui/design-system";

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatMoney(val: number | string): string {
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function statusColor(ok: boolean): string {
  return ok ? "bg-emerald-100 text-emerald-800 border-emerald-200" : "bg-amber-100 text-amber-800 border-amber-200";
}

function HealthCard({
  label,
  value,
  ok,
  icon: Icon,
}: {
  label: string;
  value: string;
  ok: boolean;
  icon: LucideIcon;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
          <p className="text-sm font-semibold text-gray-900 mt-1 capitalize">{value}</p>
        </div>
        <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center", ok ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600")}>
          <Icon size={18} />
        </div>
      </div>
      <span className={cn("inline-block mt-2 text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize", statusColor(ok))}>
        {ok ? "healthy" : "check"}
      </span>
    </div>
  );
}

function StatCard({ label, value, icon: Icon }: { label: string; value: string | number; icon: LucideIcon }) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray-400">{label}</p>
          <p className="text-xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
        </div>
        <Icon size={18} className="text-gray-300" />
      </div>
    </div>
  );
}

function healthChecks(data: SystemHealth) {
  return {
    database: data.database === "ok",
    scheduler: data.scheduler === "running" || data.scheduler === "disabled",
    ai: data.ai_services === "ok" || data.ai_services === "demo",
    telegram: data.telegram_bot === "configured",
  };
}

export default function SystemPage() {
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["system-health"],
    queryFn: () => systemApi.health().then((r) => r.data),
    refetchInterval: 30_000,
  });

  const seedMutation = useMutation({
    mutationFn: () => systemApi.demoSeed().then((r) => r.data),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["system-health"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      toast.success(result.message);
    },
    onError: (err: Error) => toast.error(err.message || "Demo seed failed"),
  });

  const resetMutation = useMutation({
    mutationFn: () => systemApi.demoReset().then((r) => r.data),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["system-health"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      toast.success(result.message);
    },
    onError: (err: Error) => toast.error(err.message || "Demo reset failed"),
  });

  if (isLoading) return <LoadingState message="Loading system health…" />;
  if (isError || !data) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load system health"}
        onRetry={() => refetch()}
      />
    );
  }

  const checks = healthChecks(data);

  return (
    <PageShell className="max-w-5xl">
      <PageHeader
        title="System"
        subtitle="Platform health, statistics, demo tools, and UI design system registry"
        icon={Activity}
        actions={
          <button
            type="button"
            disabled={isFetching}
            onClick={() => refetch()}
            className="btn-secondary text-sm"
          >
            {isFetching ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Refresh
          </button>
        }
      />

      <UiHealthSection />

      <TelegramIngestionSettingsPanel />

      <div className="card p-4 flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "text-xs px-2.5 py-1 rounded-full border font-medium capitalize",
            data.status === "ok"
              ? "bg-emerald-100 text-emerald-800 border-emerald-200"
              : "bg-amber-100 text-amber-800 border-amber-200",
          )}
        >
          {data.status}
        </span>
        <span className="text-xs text-gray-500">Uptime: {formatUptime(data.uptime)}</span>
        {data.demo_mode && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-violet-100 text-violet-800 border border-violet-200">
            DEMO_MODE active
          </span>
        )}
      </div>

      <div>
        <p className="text-xs font-semibold text-gray-700 mb-2">Infrastructure</p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <HealthCard label="Database" value={data.database} ok={checks.database} icon={Database} />
          <HealthCard label="Scheduler" value={data.scheduler} ok={checks.scheduler} icon={HardDrive} />
          <HealthCard label="AI Services" value={data.ai_services} ok={checks.ai} icon={Sparkles} />
          <HealthCard label="Telegram Bot" value={data.telegram_bot} ok={checks.telegram} icon={Send} />
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold text-gray-700 mb-2">Platform statistics</p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <StatCard label="Clients" value={data.total_clients} icon={Users} />
          <StatCard label="Leads" value={data.total_leads} icon={Briefcase} />
          <StatCard label="Deals" value={data.total_deals} icon={Briefcase} />
          <StatCard label="Revenue" value={`${formatMoney(data.total_revenue)} UZS`} icon={Activity} />
          <StatCard label="Posts" value={data.total_posts} icon={FileText} />
        </div>
        <p className="text-[10px] text-gray-400 mt-2">
          {data.total_content} content items · {formatMoney(data.total_commissions)} UZS commissions tracked
        </p>
      </div>

      <div className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Bot size={16} className="text-violet-600" />
          Demo tools
        </p>
        <p className="text-xs text-gray-500">
          Demo data is tagged with <code className="text-[10px] bg-gray-100 px-1 rounded">[SYSTEM_DEMO_V1]</code> in
          notes. Reset removes only tagged records — real data is never deleted.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={seedMutation.isPending}
            onClick={() => seedMutation.mutate()}
            className="btn-primary text-sm flex items-center gap-1.5"
          >
            {seedMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Seed demo data
          </button>
          <button
            type="button"
            disabled={resetMutation.isPending}
            onClick={() => {
              if (window.confirm("Remove all demo-tagged data? Real records will not be affected.")) {
                resetMutation.mutate();
              }
            }}
            className="text-sm px-3 py-1.5 rounded-lg border border-red-200 text-red-700 hover:bg-red-50 flex items-center gap-1.5 disabled:opacity-50"
          >
            {resetMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            Reset demo data
          </button>
        </div>
      </div>
    </PageShell>
  );
}
