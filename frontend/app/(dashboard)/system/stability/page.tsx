"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Database,
  GitBranch,
  LayoutDashboard,
  RefreshCw,
  Server,
  Timer,
  XCircle,
  Zap,
} from "lucide-react";
import {
  systemApi,
  ApiHealth,
  ApiHealthEndpoint,
  PageDependency,
  QueryHealth,
  RecentErrorEntry,
  RecentErrors,
  SchemaHealth,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { useTranslation } from "@/lib/I18nProvider";

type TabId = "overview" | "schema" | "api" | "errors" | "query" | "dependencies";

const TAB_KEYS: { id: TabId; labelKey: string }[] = [
  { id: "overview", labelKey: "systemStability.tabOverview" },
  { id: "schema", labelKey: "systemStability.tabSchema" },
  { id: "api", labelKey: "systemStability.tabApi" },
  { id: "errors", labelKey: "systemStability.tabErrors" },
  { id: "query", labelKey: "systemStability.tabQuery" },
  { id: "dependencies", labelKey: "systemStability.tabDependencies" },
];

type HealthLabel = "Excellent" | "Good" | "Warning" | "Critical";

function computeHealthScore(
  schema: SchemaHealth | undefined,
  apiHealth: ApiHealth | undefined,
  recent: RecentErrors | undefined,
): { score: number; label: HealthLabel } {
  let score = 100;

  if (schema) {
    if (!schema.ok) score -= 30;
    score -= Math.min(schema.missing_tables.length * 10, 20);
    score -= Math.min(schema.missing_columns.length * 5, 15);
    if (schema.migration_drift) score -= 10;
    if (!schema.database_connected) score -= 25;
  }

  if (apiHealth) {
    const broken = apiHealth.endpoints.filter((e) => e.status === "error").length;
    const slow = apiHealth.endpoints.filter((e) => e.status === "slow").length;
    score -= Math.min(broken * 5, 25);
    score -= Math.min(slow * 2, 10);
  }

  if (recent) {
    score -= Math.min(recent.errors.length * 2, 20);
    score -= Math.min(recent.slow.length, 10);
  }

  score = Math.max(0, Math.min(100, score));

  let label: HealthLabel = "Critical";
  if (score >= 90) label = "Excellent";
  else if (score >= 75) label = "Good";
  else if (score >= 50) label = "Warning";

  return { score, label };
}

function healthLabelColor(label: HealthLabel): string {
  switch (label) {
    case "Excellent":
      return "text-emerald-700 bg-emerald-50 border-emerald-200";
    case "Good":
      return "text-sky-700 bg-sky-50 border-sky-200";
    case "Warning":
      return "text-amber-700 bg-amber-50 border-amber-200";
    default:
      return "text-red-700 bg-red-50 border-red-200";
  }
}

function ProbeStatusIcon({ status }: { status: ApiHealthEndpoint["status"] }) {
  if (status === "ok") return <CheckCircle2 size={14} className="text-emerald-500" />;
  if (status === "slow") return <Timer size={14} className="text-amber-500" />;
  return <XCircle size={14} className="text-red-500" />;
}

function RequestLogTable({
  title,
  rows,
  emptyMessage,
  showCategory = false,
}: {
  title: string;
  rows: RecentErrorEntry[];
  emptyMessage: string;
  showCategory?: boolean;
}) {
  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
        <p className="text-sm font-semibold text-gray-900">{title}</p>
        <span className="text-[10px] text-gray-400">{rows.length} entries</span>
      </div>
      {rows.length === 0 ? (
        <p className="p-4 text-xs text-gray-400">{emptyMessage}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-100">
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">Method</th>
                <th className="px-3 py-2 font-medium">Path</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Duration</th>
                {showCategory && <th className="px-3 py-2 font-medium">Category</th>}
                <th className="px-3 py-2 font-medium">Summary</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.timestamp}-${i}`} className="border-b border-gray-50 hover:bg-gray-50/50">
                  <td className="px-3 py-2 text-gray-500 whitespace-nowrap">
                    {new Date(row.timestamp).toLocaleTimeString()}
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-700">{row.method}</td>
                  <td className="px-3 py-2 font-mono text-gray-700 max-w-[180px] truncate" title={row.path}>
                    {row.path}
                  </td>
                  <td className="px-3 py-2 tabular-nums">{row.status}</td>
                  <td className="px-3 py-2 tabular-nums">{row.duration_ms}ms</td>
                  {showCategory && (
                    <td className="px-3 py-2 text-gray-600 capitalize">{row.category?.replace(/_/g, " ") ?? "—"}</td>
                  )}
                  <td className="px-3 py-2 text-gray-600 max-w-[160px] truncate" title={row.error_summary ?? ""}>
                    {row.error_summary ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SchemaPanel({ schema, loading }: { schema?: SchemaHealth; loading: boolean }) {
  if (loading && !schema) return <LoadingState message="Checking schema…" />;
  if (!schema) return <ErrorState message="Schema health unavailable" />;

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <div className="card p-4 space-y-2 text-xs">
        <div className="flex justify-between">
          <span className="text-gray-500">Database</span>
          <span className={schema.database_connected ? "text-emerald-700" : "text-red-700"}>
            {schema.database_connected ? "Connected" : "Disconnected"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Alembic current</span>
          <span className="font-mono text-gray-800 truncate max-w-[180px]">{schema.alembic_current_revision ?? "—"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Alembic head</span>
          <span className="font-mono text-gray-800 truncate max-w-[180px]">{schema.alembic_head_revision ?? "—"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Migration drift</span>
          <span className={schema.migration_drift ? "text-amber-700" : "text-emerald-700"}>
            {schema.migration_drift ? "Yes" : "No"}
          </span>
        </div>
      </div>
      <div className="card p-4 space-y-2 text-xs">
        <p className="text-gray-500 font-medium">Checked models ({schema.checked_models.length})</p>
        <p className="text-gray-700 leading-relaxed">{schema.checked_models.join(", ")}</p>
        {schema.missing_tables.length > 0 && (
          <p className="text-red-700">Missing tables: {schema.missing_tables.join(", ")}</p>
        )}
        {schema.missing_columns.length > 0 && (
          <p className="text-red-700">
            Missing columns: {schema.missing_columns.map((c) => `${c.table}.${c.column}`).join(", ")}
          </p>
        )}
        {schema.warnings.length > 0 && (
          <ul className="list-disc list-inside text-amber-800 space-y-0.5">
            {schema.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ApiPanel({ apiHealth, loading }: { apiHealth?: ApiHealth; loading: boolean }) {
  if (loading && !apiHealth) return <LoadingState message="Probing endpoints…" />;
  if (!apiHealth) return <ErrorState message="API health unavailable" />;

  return (
    <div className="card overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-gray-400 border-b border-gray-100 bg-gray-50/50">
            <th className="px-3 py-2 font-medium">Module</th>
            <th className="px-3 py-2 font-medium">Path</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Duration</th>
            <th className="px-3 py-2 font-medium">Error</th>
          </tr>
        </thead>
        <tbody>
          {apiHealth.endpoints.map((ep) => (
            <tr key={ep.name} className="border-b border-gray-50 hover:bg-gray-50/50">
              <td className="px-3 py-2 font-medium text-gray-800 capitalize">{ep.name.replace(/_/g, " ")}</td>
              <td className="px-3 py-2 font-mono text-gray-600">{ep.path}</td>
              <td className="px-3 py-2">
                <span className="inline-flex items-center gap-1 capitalize">
                  <ProbeStatusIcon status={ep.status} />
                  {ep.status}
                </span>
              </td>
              <td className="px-3 py-2 tabular-nums">{ep.duration_ms}ms</td>
              <td className="px-3 py-2 text-gray-500 max-w-[200px] truncate" title={ep.error ?? ""}>
                {ep.error ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function QueryPanel({ queryHealth, loading }: { queryHealth?: QueryHealth; loading: boolean }) {
  if (loading && !queryHealth) return <LoadingState message="Loading query stats…" />;
  if (!queryHealth) return <ErrorState message="Query health unavailable" />;

  return (
    <div className="space-y-4">
      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100">
          <p className="text-sm font-semibold text-gray-900">Endpoint query profile</p>
        </div>
        {queryHealth.endpoints.length === 0 ? (
          <p className="p-4 text-xs text-gray-400">No API traffic profiled yet.</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-100">
                <th className="px-3 py-2 font-medium">Endpoint</th>
                <th className="px-3 py-2 font-medium">Calls</th>
                <th className="px-3 py-2 font-medium">Avg ms</th>
                <th className="px-3 py-2 font-medium">Max ms</th>
                <th className="px-3 py-2 font-medium">Avg queries</th>
              </tr>
            </thead>
            <tbody>
              {queryHealth.endpoints.map((row) => (
                <tr key={row.endpoint} className="border-b border-gray-50">
                  <td className="px-3 py-2 font-mono text-gray-700">{row.endpoint}</td>
                  <td className="px-3 py-2 tabular-nums">{row.call_count}</td>
                  <td className="px-3 py-2 tabular-nums">{row.avg_duration_ms}</td>
                  <td className="px-3 py-2 tabular-nums">{row.max_duration_ms}</td>
                  <td className="px-3 py-2 tabular-nums">{row.avg_query_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {queryHealth.slowest_requests.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-900">Top 50 slowest requests</p>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-100">
                <th className="px-3 py-2 font-medium">Endpoint</th>
                <th className="px-3 py-2 font-medium">Duration</th>
                <th className="px-3 py-2 font-medium">Queries</th>
                <th className="px-3 py-2 font-medium">Query time</th>
              </tr>
            </thead>
            <tbody>
              {queryHealth.slowest_requests.slice(0, 20).map((row, i) => (
                <tr key={`${row.endpoint}-${i}`} className="border-b border-gray-50">
                  <td className="px-3 py-2 font-mono text-gray-700">{row.endpoint}</td>
                  <td className="px-3 py-2 tabular-nums">{row.duration_ms}ms</td>
                  <td className="px-3 py-2 tabular-nums">{row.query_count}</td>
                  <td className="px-3 py-2 tabular-nums">{row.query_duration_ms}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DependenciesPanel({
  pages,
  loading,
}: {
  pages?: PageDependency[];
  loading: boolean;
}) {
  if (loading && !pages) return <LoadingState message="Loading dependencies…" />;
  if (!pages) return <ErrorState message="Dependencies unavailable" />;

  return (
    <div className="space-y-3">
      {pages.map((dep) => (
        <div key={dep.page} className="card p-4">
          <div className="flex flex-wrap items-start justify-between gap-2 mb-3">
            <div>
              <p className="text-sm font-semibold text-gray-900">{dep.page}</p>
              <Link href={dep.route} className="text-xs text-brand-700 hover:underline">
                {dep.route}
              </Link>
            </div>
          </div>
          <div className="grid sm:grid-cols-3 gap-3 text-xs">
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-1">Endpoints</p>
              <ul className="space-y-0.5 font-mono text-gray-700">
                {dep.endpoints.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-1">Services</p>
              <ul className="space-y-0.5 text-gray-700">
                {dep.services.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-1">Depends on tables</p>
              <div className="flex flex-wrap gap-1">
                {dep.tables.map((t) => (
                  <span key={t} className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 font-mono text-[10px]">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function CriticalAlerts({
  schema,
  apiHealth,
  recent,
}: {
  schema?: SchemaHealth;
  apiHealth?: ApiHealth;
  recent?: RecentErrors;
}) {
  const alerts: { severity: "critical" | "warning"; message: string }[] = [];

  if (schema?.migration_drift) {
    alerts.push({ severity: "critical", message: "Schema migration drift detected — run alembic upgrade head" });
  }
  if (schema && !schema.database_connected) {
    alerts.push({ severity: "critical", message: "Database disconnected" });
  }
  if (schema?.missing_tables.length) {
    alerts.push({
      severity: "critical",
      message: `Missing tables: ${schema.missing_tables.slice(0, 5).join(", ")}${schema.missing_tables.length > 5 ? "…" : ""}`,
    });
  }

  apiHealth?.endpoints
    .filter((e) => e.status === "error")
    .forEach((e) => {
      alerts.push({ severity: "critical", message: `Broken endpoint: ${e.name} (${e.path})` });
    });

  recent?.errors.slice(0, 5).forEach((e) => {
    alerts.push({
      severity: "warning",
      message: `Recent 5xx: ${e.method} ${e.path} — ${e.error_summary ?? "HTTP error"}`,
    });
  });

  if (alerts.length === 0) {
    return (
      <div className="card p-4 flex items-center gap-2 text-sm text-emerald-700 bg-emerald-50/50">
        <CheckCircle2 size={16} />
        No critical alerts — system looks stable
      </div>
    );
  }

  return (
    <div className="card divide-y divide-gray-100">
      <div className="px-4 py-3 border-b border-gray-100">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-2">
          <AlertTriangle size={16} className="text-amber-500" />
          Critical Alerts
        </p>
      </div>
      {alerts.map((a, i) => (
        <div
          key={i}
          className={cn(
            "px-4 py-2.5 text-xs",
            a.severity === "critical" ? "text-red-800 bg-red-50/30" : "text-amber-900 bg-amber-50/30",
          )}
        >
          {a.message}
        </div>
      ))}
    </div>
  );
}

export default function SystemStabilityPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabId>("overview");

  const { data: schema, isLoading: schemaLoading, refetch: refetchSchema } = useQuery({
    queryKey: ["system-schema-health"],
    queryFn: () => systemApi.schemaHealth().then((r) => r.data),
  });

  const { data: apiHealth, isLoading: apiLoading, refetch: refetchApi } = useQuery({
    queryKey: ["system-api-health"],
    queryFn: () => systemApi.apiHealth().then((r) => r.data),
  });

  const { data: recent, isLoading: logsLoading, refetch: refetchLogs } = useQuery({
    queryKey: ["system-recent-errors"],
    queryFn: () => systemApi.recentErrors().then((r) => r.data),
    refetchInterval: 30000,
  });

  const { data: queryHealth, isLoading: queryLoading, refetch: refetchQuery } = useQuery({
    queryKey: ["system-query-health"],
    queryFn: () => systemApi.queryHealth().then((r) => r.data),
    enabled: tab === "overview" || tab === "query",
  });

  const { data: deps, isLoading: depsLoading, refetch: refetchDeps } = useQuery({
    queryKey: ["system-dependencies"],
    queryFn: () => systemApi.dependencies().then((r) => r.data),
    enabled: tab === "overview" || tab === "dependencies",
  });

  const { data: snapshots } = useQuery({
    queryKey: ["system-health-snapshots"],
    queryFn: () => systemApi.healthSnapshots().then((r) => r.data),
    enabled: tab === "overview",
    refetchInterval: 60000,
  });

  const { score, label } = useMemo(
    () => computeHealthScore(schema, apiHealth, recent),
    [schema, apiHealth, recent],
  );

  const refreshAll = () => {
    refetchSchema();
    refetchApi();
    refetchLogs();
    refetchQuery();
    refetchDeps();
  };

  const initialLoading = schemaLoading && apiLoading && logsLoading && !schema && !apiHealth && !recent;

  if (initialLoading) {
    return <LoadingState message={t("systemStability.loading")} className="min-h-[40vh]" />;
  }

  const healthLabelKey: Record<HealthLabel, string> = {
    Excellent: "systemStability.excellent",
    Good: "systemStability.good",
    Warning: "systemStability.warning",
    Critical: "systemStability.critical",
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Activity size={22} className="text-brand-600" />
            {t("systemStability.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("systemStability.subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={refreshAll} className="btn-secondary text-xs flex items-center gap-1.5">
            <RefreshCw size={13} />
            {t("common.refresh")}
          </button>
          <Link href="/audit" className="btn-secondary text-xs flex items-center gap-1.5">
            <ClipboardCheck size={13} />
            Open Audit
          </Link>
          <Link href="/dashboard" className="btn-secondary text-xs flex items-center gap-1.5">
            <LayoutDashboard size={13} />
            Open Dashboard
          </Link>
          <Link href="/system" className="btn-secondary text-xs flex items-center gap-1.5">
            <Server size={13} />
            Open Logs
          </Link>
        </div>
      </div>

      {/* Health score */}
      <div className="card p-4 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-3">
          <div className="w-14 h-14 rounded-full border-4 border-brand-100 flex items-center justify-center">
            <span className="text-xl font-bold text-brand-800 tabular-nums">{score}</span>
          </div>
          <div>
            <p className="text-[10px] uppercase text-gray-400 tracking-wide">{t("systemStability.healthScore")}</p>
            <span className={cn("inline-block mt-1 text-xs px-2 py-0.5 rounded-full border font-medium", healthLabelColor(label))}>
              {t(healthLabelKey[label])}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-4 text-xs text-gray-600 ml-auto">
          <span className="flex items-center gap-1">
            <Database size={12} />
            Schema: {schema?.ok ? "ok" : "issues"}
          </span>
          <span className="flex items-center gap-1">
            <Zap size={12} />
            API: {apiHealth ? `${apiHealth.ok_count}/${apiHealth.total}` : "—"}
          </span>
          <span className="flex items-center gap-1">
            <AlertTriangle size={12} />
            5xx: {recent?.errors.length ?? 0}
          </span>
          <span className="flex items-center gap-1">
            <Timer size={12} />
            Slow: {recent?.slow.length ?? 0}
          </span>
          {snapshots && snapshots.snapshots.length > 0 && (
            <span className="flex items-center gap-1">
              <GitBranch size={12} />
              Snapshots: {snapshots.snapshots.length} (48h)
            </span>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {TAB_KEYS.map((tabItem) => (
          <button
            key={tabItem.id}
            type="button"
            onClick={() => setTab(tabItem.id)}
            className={cn(
              "px-3 py-2 text-xs font-medium whitespace-nowrap border-b-2 -mb-px transition-colors",
              tab === tabItem.id
                ? "border-brand-600 text-brand-800"
                : "border-transparent text-gray-500 hover:text-gray-800",
            )}
          >
            {t(tabItem.labelKey)}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="space-y-4">
          <CriticalAlerts schema={schema} apiHealth={apiHealth} recent={recent} />
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="card p-3 text-xs">
              <p className="text-gray-400">Schema</p>
              <p className={cn("text-lg font-semibold mt-1", schema?.ok ? "text-emerald-700" : "text-amber-700")}>
                {schema?.ok ? "Healthy" : "Issues"}
              </p>
            </div>
            <div className="card p-3 text-xs">
              <p className="text-gray-400">API probes</p>
              <p className="text-lg font-semibold mt-1 text-gray-900">
                {apiHealth?.ok_count ?? "—"}/{apiHealth?.total ?? "—"} ok
              </p>
            </div>
            <div className="card p-3 text-xs">
              <p className="text-gray-400">Recent 5xx</p>
              <p className={cn("text-lg font-semibold mt-1", (recent?.errors.length ?? 0) > 0 ? "text-red-700" : "text-gray-900")}>
                {recent?.errors.length ?? 0}
              </p>
            </div>
            <div className="card p-3 text-xs">
              <p className="text-gray-400">Profiled endpoints</p>
              <p className="text-lg font-semibold mt-1 text-gray-900">{queryHealth?.endpoints.length ?? 0}</p>
            </div>
          </div>
          {recent?.categories && Object.keys(recent.categories).length > 0 && (
            <div className="card p-4">
              <p className="text-sm font-semibold text-gray-900 mb-2">Error categories</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(recent.categories).map(([cat, count]) => (
                  <span key={cat} className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-700 capitalize">
                    {cat.replace(/_/g, " ")}: {count}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "schema" && <SchemaPanel schema={schema} loading={schemaLoading} />}
      {tab === "api" && <ApiPanel apiHealth={apiHealth} loading={apiLoading} />}
      {tab === "errors" && (
        <div className="grid lg:grid-cols-2 gap-4">
          {logsLoading && !recent ? (
            <LoadingState message="Loading errors…" className="lg:col-span-2" />
          ) : recent ? (
            <>
              <RequestLogTable
                title="Recent Errors (5xx)"
                rows={recent.errors}
                emptyMessage="No server errors captured."
                showCategory
              />
              <RequestLogTable
                title="Slow Endpoints (&gt;1s)"
                rows={recent.slow}
                emptyMessage="No slow requests captured."
              />
            </>
          ) : (
            <ErrorState message="Error log unavailable" onRetry={() => refetchLogs()} className="lg:col-span-2" />
          )}
        </div>
      )}
      {tab === "query" && <QueryPanel queryHealth={queryHealth} loading={queryLoading} />}
      {tab === "dependencies" && <DependenciesPanel pages={deps?.pages} loading={depsLoading} />}
    </div>
  );
}
