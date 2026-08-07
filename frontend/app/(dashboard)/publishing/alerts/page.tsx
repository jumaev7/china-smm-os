"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  PublishAlert,
  PublishAlertSeverity,
  PublishAlertState,
  getApiErrorMessage,
  publishingApi,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  Filter,
  RefreshCw,
} from "lucide-react";
import toast from "react-hot-toast";
import { TelegramAlertDeliveryPanel } from "@/components/publishing/TelegramAlertDeliveryPanel";

const SEVERITY_BADGE: Record<PublishAlertSeverity, string> = {
  critical: "bg-red-100 text-red-800 border-red-200",
  warning: "bg-amber-100 text-amber-800 border-amber-200",
  info: "bg-sky-100 text-sky-800 border-sky-200",
};

const STATE_BADGE: Record<PublishAlertState, string> = {
  open: "bg-violet-100 text-violet-800 border-violet-200",
  acknowledged: "bg-slate-100 text-slate-700 border-slate-200",
  resolved: "bg-emerald-100 text-emerald-800 border-emerald-200",
};

type Filters = {
  state: string;
  severity: string;
  platform: string;
};

const EMPTY_FILTERS: Filters = { state: "open", severity: "", platform: "" };

function formatWhen(value?: string | null) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export default function PublishingAlertsPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [resolveNote, setResolveNote] = useState<Record<string, string>>({});
  const [confirmResolveId, setConfirmResolveId] = useState<string | null>(null);

  const countsQuery = useQuery({
    queryKey: ["publishing-alert-counts"],
    queryFn: () => publishingApi.alertCounts().then((r) => r.data),
    refetchInterval: 30_000,
  });

  const listQuery = useQuery({
    queryKey: ["publishing-alerts", filters, page],
    queryFn: () =>
      publishingApi
        .listAlerts({
          state: filters.state || undefined,
          severity: filters.severity || undefined,
          platform: filters.platform || undefined,
          page,
          page_size: 20,
        })
        .then((r) => r.data),
    refetchInterval: 30_000,
  });

  const acknowledgeMutation = useMutation({
    mutationFn: (id: string) => publishingApi.acknowledgeAlert(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("Alert acknowledged");
      queryClient.invalidateQueries({ queryKey: ["publishing-alerts"] });
      queryClient.invalidateQueries({ queryKey: ["publishing-alert-counts"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const resolveMutation = useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) =>
      publishingApi.resolveAlert(id, note ? { note } : undefined).then((r) => r.data),
    onSuccess: () => {
      toast.success("Alert resolved");
      setConfirmResolveId(null);
      queryClient.invalidateQueries({ queryKey: ["publishing-alerts"] });
      queryClient.invalidateQueries({ queryKey: ["publishing-alert-counts"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const counts = countsQuery.data;
  const items = listQuery.data?.items ?? [];
  const openBadge = useMemo(() => {
    const critical = counts?.critical_open_count ?? 0;
    const warning = counts?.warning_open_count ?? 0;
    return critical + warning;
  }, [counts]);

  const isMutating = acknowledgeMutation.isPending || resolveMutation.isPending;

  return (
    <div className="p-4 sm:p-6 space-y-5 max-w-6xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div className="space-y-1">
          <Link
            href="/publishing/queue"
            className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
          >
            <ArrowLeft size={14} />
            Publishing queue
          </Link>
          <h1 className="text-xl sm:text-2xl font-semibold text-gray-900 flex items-center gap-2">
            <AlertTriangle className="text-amber-600" size={22} />
            Publishing alerts
            {openBadge > 0 ? (
              <span className="inline-flex min-w-[1.5rem] h-6 px-1.5 items-center justify-center rounded-full bg-red-500 text-white text-xs font-bold">
                {openBadge}
              </span>
            ) : null}
          </h1>
          <p className="text-sm text-gray-500">
            Deduplicated in-app operator alerts for publish failures and recoveries.
            Telegram outbound delivery is configured separately below and stays off by default.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            listQuery.refetch();
            countsQuery.refetch();
          }}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
        >
          <RefreshCw size={14} className={cn(listQuery.isFetching && "animate-spin")} />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Open", value: counts?.open_count ?? 0 },
          { label: "Critical open", value: counts?.critical_open_count ?? 0 },
          { label: "Warning open", value: counts?.warning_open_count ?? 0 },
          { label: "Acknowledged", value: counts?.acknowledged_count ?? 0 },
        ].map((card) => (
          <div
            key={card.label}
            className="rounded-xl border border-gray-200 bg-white px-3 py-3"
          >
            <div className="text-xs text-gray-500">{card.label}</div>
            <div className="text-xl font-semibold text-gray-900">{card.value}</div>
          </div>
        ))}
      </div>

      <TelegramAlertDeliveryPanel />

      <div className="rounded-xl border border-gray-200 bg-white p-3 sm:p-4 space-y-3">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
          <Filter size={14} />
          Filters
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <label className="text-xs text-gray-500 space-y-1">
            <span>State</span>
            <select
              className="w-full rounded-lg border border-gray-200 px-2.5 py-2 text-sm"
              value={filters.state}
              onChange={(e) => {
                setPage(1);
                setFilters((f) => ({ ...f, state: e.target.value }));
              }}
            >
              <option value="">All</option>
              <option value="open">Open</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="resolved">Resolved</option>
            </select>
          </label>
          <label className="text-xs text-gray-500 space-y-1">
            <span>Severity</span>
            <select
              className="w-full rounded-lg border border-gray-200 px-2.5 py-2 text-sm"
              value={filters.severity}
              onChange={(e) => {
                setPage(1);
                setFilters((f) => ({ ...f, severity: e.target.value }));
              }}
            >
              <option value="">All</option>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
          </label>
          <label className="text-xs text-gray-500 space-y-1">
            <span>Platform</span>
            <select
              className="w-full rounded-lg border border-gray-200 px-2.5 py-2 text-sm"
              value={filters.platform}
              onChange={(e) => {
                setPage(1);
                setFilters((f) => ({ ...f, platform: e.target.value }));
              }}
            >
              <option value="">All</option>
              <option value="facebook">Facebook</option>
              <option value="instagram">Instagram</option>
              <option value="telegram">Telegram</option>
            </select>
          </label>
        </div>
      </div>

      {listQuery.isLoading ? (
        <div className="rounded-xl border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
          Loading alerts…
        </div>
      ) : null}

      {listQuery.isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800 space-y-3">
          <p>{getApiErrorMessage(listQuery.error)}</p>
          <button
            type="button"
            className="rounded-lg bg-red-600 px-3 py-1.5 text-white text-sm"
            onClick={() => listQuery.refetch()}
          >
            Retry
          </button>
        </div>
      ) : null}

      {!listQuery.isLoading && !listQuery.isError && items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 bg-white p-10 text-center space-y-2">
          <CheckCircle2 className="mx-auto text-emerald-500" size={28} />
          <p className="font-medium text-gray-800">No alerts for these filters</p>
          <p className="text-sm text-gray-500">
            Publishing problems will appear here automatically.
          </p>
        </div>
      ) : null}

      <div className="space-y-3">
        {items.map((alert) => (
          <AlertCard
            key={alert.id}
            alert={alert}
            disabled={isMutating}
            confirmResolve={confirmResolveId === alert.id}
            resolveNote={resolveNote[alert.id] ?? ""}
            onResolveNoteChange={(value) =>
              setResolveNote((prev) => ({ ...prev, [alert.id]: value }))
            }
            onAcknowledge={() => acknowledgeMutation.mutate(alert.id)}
            onAskResolve={() => setConfirmResolveId(alert.id)}
            onCancelResolve={() => setConfirmResolveId(null)}
            onConfirmResolve={() =>
              resolveMutation.mutate({
                id: alert.id,
                note: resolveNote[alert.id]?.trim() || undefined,
              })
            }
          />
        ))}
      </div>

      {(listQuery.data?.pages ?? 0) > 1 ? (
        <div className="flex items-center justify-between gap-3 text-sm">
          <button
            type="button"
            disabled={page <= 1}
            className="rounded-lg border border-gray-200 px-3 py-1.5 disabled:opacity-40"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <span className="text-gray-500">
            Page {listQuery.data?.page ?? page} of {listQuery.data?.pages ?? 1}
          </span>
          <button
            type="button"
            disabled={page >= (listQuery.data?.pages ?? 1)}
            className="rounded-lg border border-gray-200 px-3 py-1.5 disabled:opacity-40"
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}

function AlertCard({
  alert,
  disabled,
  confirmResolve,
  resolveNote,
  onResolveNoteChange,
  onAcknowledge,
  onAskResolve,
  onCancelResolve,
  onConfirmResolve,
}: {
  alert: PublishAlert;
  disabled: boolean;
  confirmResolve: boolean;
  resolveNote: string;
  onResolveNoteChange: (value: string) => void;
  onAcknowledge: () => void;
  onAskResolve: () => void;
  onCancelResolve: () => void;
  onConfirmResolve: () => void;
}) {
  const canAck = alert.state === "open";
  const canResolve = alert.state === "open" || alert.state === "acknowledged";

  return (
    <article className="rounded-xl border border-gray-200 bg-white p-4 space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
        <div className="space-y-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase",
                SEVERITY_BADGE[alert.severity],
              )}
            >
              {alert.severity}
            </span>
            <span
              className={cn(
                "inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase",
                STATE_BADGE[alert.state],
              )}
            >
              {alert.state}
            </span>
            <span className="text-[11px] text-gray-500 font-mono">{alert.alert_type}</span>
          </div>
          <h2 className="text-sm sm:text-base font-semibold text-gray-900 break-words">
            {alert.title}
          </h2>
          {alert.body ? (
            <p className="text-sm text-gray-600 break-words">{alert.body}</p>
          ) : null}
        </div>
        <div className="text-xs text-gray-500 shrink-0 space-y-0.5 sm:text-right">
          <div>First: {formatWhen(alert.first_occurred_at)}</div>
          <div>Latest: {formatWhen(alert.latest_occurred_at)}</div>
          <div>×{alert.occurrence_count}</div>
        </div>
      </div>

      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-600">
        <div>
          <dt className="inline text-gray-400">Client: </dt>
          <dd className="inline">{alert.company_name || "—"}</dd>
        </div>
        <div>
          <dt className="inline text-gray-400">Destination: </dt>
          <dd className="inline">
            {[alert.platform, alert.account_name].filter(Boolean).join(" / ") || "—"}
          </dd>
        </div>
        <div>
          <dt className="inline text-gray-400">Attempt: </dt>
          <dd className="inline">
            {alert.attempt_status || "—"}
            {alert.attempt_number != null ? ` #${alert.attempt_number}` : ""}
          </dd>
        </div>
        <div>
          <dt className="inline text-gray-400">Code: </dt>
          <dd className="inline font-mono">{alert.failure_code || "—"}</dd>
        </div>
        {alert.next_retry_at ? (
          <div className="sm:col-span-2">
            <dt className="inline text-gray-400">Next retry: </dt>
            <dd className="inline">{formatWhen(alert.next_retry_at)}</dd>
          </div>
        ) : null}
      </dl>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        {alert.content_url ? (
          <Link
            href={alert.content_url}
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
          >
            Content <ExternalLink size={12} />
          </Link>
        ) : null}
        <Link
          href={alert.queue_url || "/publishing/queue"}
          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
        >
          Queue <ExternalLink size={12} />
        </Link>
        {canAck ? (
          <button
            type="button"
            disabled={disabled}
            onClick={onAcknowledge}
            className="rounded-lg border border-violet-200 bg-violet-50 px-2.5 py-1.5 text-xs font-medium text-violet-800 disabled:opacity-50"
          >
            Acknowledge
          </button>
        ) : null}
        {canResolve && !confirmResolve ? (
          <button
            type="button"
            disabled={disabled}
            onClick={onAskResolve}
            className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-xs font-medium text-emerald-800 disabled:opacity-50"
          >
            Resolve
          </button>
        ) : null}
      </div>

      {confirmResolve ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3 space-y-2">
          <p className="text-xs text-emerald-900">
            Resolve this alert? Optional operator note (never paste tokens or secrets).
          </p>
          <textarea
            value={resolveNote}
            onChange={(e) => onResolveNoteChange(e.target.value)}
            rows={2}
            maxLength={1000}
            className="w-full rounded-lg border border-emerald-200 bg-white px-2.5 py-2 text-sm"
            placeholder="Optional note"
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={disabled}
              onClick={onConfirmResolve}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
            >
              Confirm resolve
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={onCancelResolve}
              className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}
