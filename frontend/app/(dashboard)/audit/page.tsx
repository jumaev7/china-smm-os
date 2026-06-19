"use client";

import { useMemo, useState, useEffect } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ClipboardCheck,
  ExternalLink,
  Filter,
  Info,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Wrench,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  auditApi,
  AuditFixActionType,
  AuditIssue,
  AuditSeverity,
  AUDIT_OVERVIEW_URL,
  AUDIT_RUN_URL,
  formatAuditApiError,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";
import { useTranslation } from "@/lib/I18nProvider";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";

const SEVERITY_STYLES: Record<AuditSeverity, string> = {
  critical: "bg-red-100 text-red-800 border-red-200",
  warning: "bg-amber-100 text-amber-800 border-amber-200",
  info: "bg-sky-100 text-sky-800 border-sky-200",
};

const SEVERITY_CARD: Record<
  AuditSeverity,
  { border: string; bg: string; text: string; icon: typeof ShieldAlert }
> = {
  critical: {
    border: "border-red-200",
    bg: "bg-red-50/60",
    text: "text-red-800",
    icon: ShieldAlert,
  },
  warning: {
    border: "border-amber-200",
    bg: "bg-amber-50/60",
    text: "text-amber-800",
    icon: AlertTriangle,
  },
  info: {
    border: "border-sky-200",
    bg: "bg-sky-50/60",
    text: "text-sky-800",
    icon: Info,
  },
};

const CONFIRM_FIX_ACTIONS = new Set<AuditFixActionType>(["cancel_schedule", "retry_publish"]);

function confirmFixMessage(action: AuditFixActionType): string {
  if (action === "cancel_schedule") {
    return "Remove this content from the publish schedule? It will not publish automatically.";
  }
  if (action === "retry_publish") {
    return "Retry publishing now? This will attempt to publish immediately (operator-initiated).";
  }
  return "Apply this quick fix?";
}

function entityHref(issue: AuditIssue): string | null {
  if (!issue.entity_id) return null;
  switch (issue.entity_type) {
    case "client":
      return `/clients/${issue.entity_id}`;
    case "content":
      return `/content/${issue.entity_id}`;
    case "deal":
      return `/crm/deals/${issue.entity_id}`;
    case "lead":
      return "/crm";
    case "task":
      return "/tasks";
    case "publish_attempt":
      return "/publishing/queue";
    case "document":
      return "/crm/deals";
    default:
      return null;
  }
}

function formatRanAt(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function AuditPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <AuditPageContent />
    </AdminAuthGuard>
  );
}

function AuditPageContent() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [severityFilter, setSeverityFilter] = useState<AuditSeverity | "all">("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [fixingId, setFixingId] = useState<string | null>(null);

  useEffect(() => {
    const sev = searchParams.get("severity");
    if (sev === "critical" || sev === "warning" || sev === "info") {
      setSeverityFilter(sev);
    }
    const cat = searchParams.get("category");
    if (cat) setCategoryFilter(cat);
  }, [searchParams]);

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["audit-overview"],
    queryFn: () => auditApi.overview().then((r) => r.data),
  });

  const runMutation = useMutation({
    mutationFn: () => auditApi.run().then((r) => r.data),
    onSuccess: (result) => {
      queryClient.setQueryData(["audit-overview"], result);
      toast.success(t("audit.auditComplete", { count: result.summary.total }));
    },
    onError: (err: Error) =>
      toast.error(formatAuditApiError(err, AUDIT_RUN_URL)),
  });

  const applyFixMutation = useMutation({
    mutationFn: (issueId: string) => auditApi.applyFix(issueId).then((r) => r.data),
    onSuccess: async (result) => {
      if (result.navigate_to) {
        router.push(result.navigate_to);
      }
      if (result.ok) {
        toast.success(result.message);
      } else {
        toast.error(result.message);
      }
      const refreshed = await auditApi.run().then((r) => r.data);
      queryClient.setQueryData(["audit-overview"], refreshed);
    },
    onError: (err: Error, issueId) =>
      toast.error(formatAuditApiError(err, `${AUDIT_OVERVIEW_URL.replace("/overview", "")}/fixes/${issueId}/apply`)),
    onSettled: () => setFixingId(null),
  });

  const handleQuickFix = (issue: AuditIssue) => {
    if (!issue.fix_action_type) return;

    if (issue.fix_action_type === "open_billing") {
      const href = issue.entity_id ? `/clients/${issue.entity_id}` : "/billing";
      router.push(href);
      return;
    }

    if (CONFIRM_FIX_ACTIONS.has(issue.fix_action_type)) {
      if (!window.confirm(confirmFixMessage(issue.fix_action_type))) return;
    }

    setFixingId(issue.id);
    applyFixMutation.mutate(issue.id);
  };

  const filteredIssues = useMemo(() => {
    if (!data?.issues) return [];
    return data.issues.filter((issue) => {
      if (severityFilter !== "all" && issue.severity !== severityFilter) return false;
      if (categoryFilter !== "all" && issue.category !== categoryFilter) return false;
      return true;
    });
  }, [data?.issues, severityFilter, categoryFilter]);

  if (isLoading) {
    return <LoadingState message={t("audit.loading")} />;
  }

  if (isError || !data) {
    return (
      <ErrorState
        message={formatAuditApiError(error, AUDIT_OVERVIEW_URL)}
        onRetry={() => refetch()}
        technical
      />
    );
  }

  const summary = data.summary;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <ClipboardCheck size={22} className="text-brand-600" />
            {t("audit.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("audit.subtitle")}</p>
          <p className="text-[10px] text-gray-400 mt-1">
            Last run: {formatRanAt(data.ran_at)}
          </p>
        </div>
        <button
          type="button"
          onClick={() => runMutation.mutate()}
          disabled={runMutation.isPending || isFetching}
          className="btn-primary flex items-center gap-2 self-start"
        >
          {runMutation.isPending || isFetching ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <RefreshCw size={16} />
          )}
          {t("audit.runAudit")}
        </button>
      </div>

      <PartialErrorsBanner errors={data.errors} />

      <div className="grid gap-4 sm:grid-cols-3">
        {(["critical", "warning", "info"] as const).map((sev) => {
          const cfg = SEVERITY_CARD[sev];
          const Icon = cfg.icon;
          const count = summary[sev];
          return (
            <button
              key={sev}
              type="button"
              onClick={() => setSeverityFilter(severityFilter === sev ? "all" : sev)}
              className={cn(
                "card p-4 text-left transition-shadow hover:ring-1 hover:ring-brand-200",
                cfg.border,
                cfg.bg,
                severityFilter === sev && "ring-2 ring-brand-400",
              )}
            >
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-[10px] uppercase tracking-wide font-medium capitalize opacity-70">
                    {sev}
                  </p>
                  <p className={cn("text-3xl font-semibold tabular-nums mt-1", cfg.text)}>
                    {count}
                  </p>
                </div>
                <Icon size={20} className={cfg.text} />
              </div>
            </button>
          );
        })}
      </div>

      <div className="card p-4 space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <Filter size={14} />
            Filters
          </div>
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value as AuditSeverity | "all")}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
          >
            <option value="all">All severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
          >
            <option value="all">All categories</option>
            {data.categories.map((cat) => (
              <option key={cat} value={cat}>
                {cat}
              </option>
            ))}
          </select>
          {(severityFilter !== "all" || categoryFilter !== "all") && (
            <button
              type="button"
              onClick={() => {
                setSeverityFilter("all");
                setCategoryFilter("all");
              }}
              className="text-xs text-brand-700 hover:text-brand-900"
            >
              Clear filters
            </button>
          )}
          <span className="text-[10px] text-gray-400 ml-auto">
            Showing {filteredIssues.length} of {summary.total}
          </span>
        </div>

        {filteredIssues.length === 0 ? (
          <EmptyState
            title="No issues match filters"
            message={
              summary.total === 0
                ? "All checks passed — nothing to fix right now."
                : "Try clearing filters to see other issues."
            }
          />
        ) : (
          <div className="overflow-x-auto -mx-4 px-4">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-gray-400 border-b border-gray-100">
                  <th className="pb-2 pr-3 font-medium">Severity</th>
                  <th className="pb-2 pr-3 font-medium">Category</th>
                  <th className="pb-2 pr-3 font-medium">Issue</th>
                  <th className="pb-2 pr-3 font-medium">Suggested fix</th>
                  <th className="pb-2 font-medium min-w-[140px]">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filteredIssues.map((issue) => {
                  const href = entityHref(issue);
                  const hasQuickFix = Boolean(issue.fix_action_type && issue.fix_action_label);
                  const isFixing = fixingId === issue.id;
                  return (
                    <tr key={issue.id} className="align-top">
                      <td className="py-3 pr-3">
                        <span
                          className={cn(
                            "inline-block text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
                            SEVERITY_STYLES[issue.severity],
                          )}
                        >
                          {issue.severity}
                        </span>
                      </td>
                      <td className="py-3 pr-3 text-xs text-gray-600 capitalize">{issue.category}</td>
                      <td className="py-3 pr-3">
                        <p className="font-medium text-gray-900 text-xs">{issue.title}</p>
                        <p className="text-[11px] text-gray-500 mt-0.5 line-clamp-2">{issue.description}</p>
                      </td>
                      <td className="py-3 pr-3 text-[11px] text-gray-600 max-w-xs">
                        {issue.suggested_fix}
                      </td>
                      <td className="py-3">
                        <div className="flex flex-col gap-1.5">
                          {hasQuickFix && (
                            <button
                              type="button"
                              onClick={() => handleQuickFix(issue)}
                              disabled={isFixing || applyFixMutation.isPending}
                              className="inline-flex items-center gap-1 text-[11px] text-violet-700 hover:text-violet-900 whitespace-nowrap disabled:opacity-50"
                            >
                              {isFixing ? (
                                <Loader2 size={12} className="animate-spin" />
                              ) : (
                                <Wrench size={12} />
                              )}
                              {issue.fix_action_label}
                            </button>
                          )}
                          {href ? (
                            <Link
                              href={href}
                              className="inline-flex items-center gap-1 text-[11px] text-brand-700 hover:text-brand-900 whitespace-nowrap"
                            >
                              Open
                              <ExternalLink size={12} />
                            </Link>
                          ) : !hasQuickFix ? (
                            <span className="text-[11px] text-gray-300">—</span>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
