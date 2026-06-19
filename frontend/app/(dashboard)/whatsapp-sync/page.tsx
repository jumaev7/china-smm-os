"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  CheckCircle2,
  Loader2,
  Phone,
  Plug,
  RefreshCw,
  Users,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  whatsappSyncApi,
  WhatsAppSyncAccount,
  WhatsAppSyncJob,
  WhatsAppSyncJobStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  whatsapp_business_api: "WhatsApp Business API",
  whatsapp_cloud_api: "WhatsApp Cloud API",
  third_party_connector: "Third-Party Connector",
  manual_import: "Manual Import",
};

const JOB_STATUS_STYLES: Record<WhatsAppSyncJobStatus, string> = {
  pending: "bg-amber-50 text-amber-800",
  running: "bg-blue-50 text-blue-800",
  completed: "bg-emerald-50 text-emerald-800",
  failed: "bg-red-50 text-red-800",
};

function formatDt(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "yyyy-MM-dd HH:mm");
  } catch {
    return iso;
  }
}

function StatusBadge({ status }: { status: string }) {
  const style =
    status === "connected"
      ? "bg-emerald-50 text-emerald-800"
      : status === "error"
        ? "bg-red-50 text-red-800"
        : "bg-gray-100 text-gray-600";
  return (
    <span className={cn("text-[10px] font-medium px-2 py-0.5 rounded-full uppercase", style)}>
      {status}
    </span>
  );
}

export default function WhatsAppSyncPage() {
  const qc = useQueryClient();
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);

  const {
    data: accountsData,
    isLoading: accountsLoading,
    isError: accountsError,
    refetch: refetchAccounts,
  } = useQuery({
    queryKey: ["whatsapp-sync-accounts"],
    queryFn: () => whatsappSyncApi.listAccounts().then((r) => r.data),
  });

  const { data: status } = useQuery({
    queryKey: ["whatsapp-sync-status"],
    queryFn: () => whatsappSyncApi.status().then((r) => r.data),
    enabled: !!accountsData,
  });

  const { data: jobsData, refetch: refetchJobs } = useQuery({
    queryKey: ["whatsapp-sync-jobs"],
    queryFn: () => whatsappSyncApi.listJobs({ limit: 30 }).then((r) => r.data),
    enabled: !!accountsData,
  });

  const accounts = accountsData?.items ?? [];
  const jobs = jobsData?.items ?? [];
  const activeAccountId = selectedAccountId ?? accounts[0]?.id ?? null;

  const syncContactsMut = useMutation({
    mutationFn: () =>
      whatsappSyncApi.syncContacts(
        activeAccountId ? { account_id: activeAccountId } : {},
      ),
    onSuccess: (res) => {
      toast.success(res.data.message || "Contacts synced");
      qc.invalidateQueries({ queryKey: ["whatsapp-sync-jobs"] });
      qc.invalidateQueries({ queryKey: ["whatsapp-sync-accounts"] });
      qc.invalidateQueries({ queryKey: ["whatsapp-sync-status"] });
    },
    onError: (e: Error) => toast.error(e.message || "Contact sync failed"),
  });

  const syncConversationsMut = useMutation({
    mutationFn: () =>
      whatsappSyncApi.syncConversations(
        activeAccountId ? { account_id: activeAccountId } : {},
      ),
    onSuccess: (res) => {
      toast.success(res.data.message || "Conversations synced");
      qc.invalidateQueries({ queryKey: ["whatsapp-sync-jobs"] });
      qc.invalidateQueries({ queryKey: ["whatsapp-sync-accounts"] });
      qc.invalidateQueries({ queryKey: ["whatsapp-sync-status"] });
    },
    onError: (e: Error) => toast.error(e.message || "Conversation sync failed"),
  });

  const testConnectionMut = useMutation({
    mutationFn: (accountId: string) => whatsappSyncApi.testConnection(accountId),
    onSuccess: (res) => {
      if (res.data.ok) toast.success(res.data.message);
      else toast.error(res.data.message);
      qc.invalidateQueries({ queryKey: ["whatsapp-sync-jobs"] });
      qc.invalidateQueries({ queryKey: ["whatsapp-sync-accounts"] });
    },
    onError: (e: Error) => toast.error(e.message || "Connection test failed"),
  });

  const busy =
    syncContactsMut.isPending ||
    syncConversationsMut.isPending ||
    testConnectionMut.isPending;

  const lastSyncLabel = useMemo(() => {
    const fromStatus = status?.last_sync_at;
    if (fromStatus) return formatDt(fromStatus);
    const latest = accounts
      .map((a) => a.last_sync_at)
      .filter(Boolean)
      .sort()
      .pop();
    return formatDt(latest);
  }, [status, accounts]);

  if (accountsLoading) return <LoadingState title="Loading WhatsApp Sync…" />;
  if (accountsError) {
    return (
      <ErrorState
        title="Failed to load WhatsApp Sync"
        onRetry={() => refetchAccounts()}
      />
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Phone size={22} className="text-green-600" />
            WhatsApp Sync
          </h1>
          <p className="text-sm text-gray-500 mt-1 max-w-xl">
            Integration-ready sync for contacts and conversations. Import only — no automatic
            messaging, CRM updates, or deal changes.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-secondary text-sm flex items-center gap-1.5"
            disabled={busy}
            onClick={() => {
              refetchAccounts();
              refetchJobs();
            }}
          >
            <RefreshCw size={14} className={busy ? "animate-spin" : ""} />
            Refresh
          </button>
          <Link href="/whatsapp" className="btn-secondary text-sm">
            WhatsApp Center
          </Link>
          <Link href="/unified-inbox" className="btn-secondary text-sm">
            Unified Inbox
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card p-4">
          <p className="text-[10px] uppercase text-gray-400 font-medium">Connected Accounts</p>
          <p className="text-2xl font-semibold tabular-nums mt-1">
            {status?.accounts_connected ?? 0}
            <span className="text-sm text-gray-400 font-normal">
              /{status?.accounts_total ?? accounts.length}
            </span>
          </p>
        </div>
        <div className="card p-4">
          <p className="text-[10px] uppercase text-gray-400 font-medium">Sync Status</p>
          <p className="text-sm font-medium text-gray-900 mt-2 flex items-center gap-1.5">
            {(status?.pending_jobs ?? 0) > 0 ? (
              <Loader2 size={14} className="text-amber-600 animate-spin" />
            ) : (
              <CheckCircle2 size={14} className="text-emerald-600" />
            )}
            {(status?.pending_jobs ?? 0) > 0
              ? `${status?.pending_jobs} pending`
              : "Ready"}
          </p>
          {(status?.failed_jobs_recent ?? 0) > 0 && (
            <p className="text-[10px] text-red-600 mt-1">
              {status?.failed_jobs_recent} failed (7d)
            </p>
          )}
        </div>
        <div className="card p-4">
          <p className="text-[10px] uppercase text-gray-400 font-medium">Last Sync</p>
          <p className="text-sm font-medium text-gray-900 mt-2">{lastSyncLabel}</p>
        </div>
        <div className="card p-4">
          <p className="text-[10px] uppercase text-gray-400 font-medium">Adapters</p>
          <p className="text-xs text-gray-600 mt-2 leading-relaxed">
            {(status?.adapters_available ?? []).join(", ") || "demo"}
          </p>
        </div>
      </div>

      <div className="card p-4 space-y-4">
        <p className="text-sm font-semibold text-gray-900">Manual Sync</p>
        <div className="flex flex-wrap gap-2 items-end">
          <label className="text-xs text-gray-500 flex flex-col gap-1">
            Account
            <select
              className="input text-sm min-w-[200px]"
              value={activeAccountId ?? ""}
              onChange={(e) => setSelectedAccountId(e.target.value || null)}
            >
              {accounts.map((a: WhatsAppSyncAccount) => (
                <option key={a.id} value={a.id}>
                  {a.account_name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn-primary text-sm flex items-center gap-1.5"
            disabled={busy || !activeAccountId}
            onClick={() => syncContactsMut.mutate()}
          >
            {syncContactsMut.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Users size={14} />
            )}
            Sync Contacts
          </button>
          <button
            type="button"
            className="btn-primary text-sm flex items-center gap-1.5"
            disabled={busy || !activeAccountId}
            onClick={() => syncConversationsMut.mutate()}
          >
            {syncConversationsMut.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Phone size={14} />
            )}
            Sync Conversations
          </button>
          <button
            type="button"
            className="btn-secondary text-sm flex items-center gap-1.5"
            disabled={busy || !activeAccountId}
            onClick={() => activeAccountId && testConnectionMut.mutate(activeAccountId)}
          >
            {testConnectionMut.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Plug size={14} />
            )}
            Test Connection
          </button>
        </div>
        <p className="text-[10px] text-gray-400">
          Sync imports inbound data into WhatsApp Center, Unified Inbox, and Communication
          Intelligence. Operators send messages manually from WhatsApp Center.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">Connected Accounts</p>
          {accounts.length === 0 ? (
            <EmptyState title="No accounts" description="Demo accounts seed on first load." />
          ) : (
            <ul className="space-y-2">
              {accounts.map((a) => (
                <li
                  key={a.id}
                  className={cn(
                    "border rounded-lg p-3 text-sm",
                    a.id === activeAccountId ? "border-brand-200 bg-brand-50/30" : "border-gray-100",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-gray-900">{a.account_name}</span>
                    <StatusBadge status={a.status} />
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    {ACCOUNT_TYPE_LABELS[a.account_type] ?? a.account_type}
                    {a.phone_number ? ` · ${a.phone_number}` : ""}
                    {a.provider ? ` · ${a.provider}` : ""}
                  </p>
                  <p className="text-[10px] text-gray-400 mt-1">
                    Last sync: {formatDt(a.last_sync_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">Sync Jobs</p>
          {jobs.length === 0 ? (
            <EmptyState title="No jobs yet" description="Run a manual sync to create jobs." />
          ) : (
            <ul className="space-y-2 max-h-[360px] overflow-y-auto">
              {jobs.map((j: WhatsAppSyncJob) => (
                <li key={j.id} className="border border-gray-100 rounded-lg p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-gray-800">{j.job_type}</span>
                    <span
                      className={cn(
                        "px-2 py-0.5 rounded-full uppercase text-[10px] font-medium",
                        JOB_STATUS_STYLES[j.status] ?? "bg-gray-100",
                      )}
                    >
                      {j.status}
                    </span>
                  </div>
                  <p className="text-gray-500 mt-1">
                    {j.account_name ?? "—"} · {j.trigger} · {formatDt(j.created_at)}
                  </p>
                  {j.stats_json && (
                    <pre className="mt-1 text-[10px] text-gray-400 overflow-x-auto">
                      {JSON.stringify(j.stats_json)}
                    </pre>
                  )}
                  {j.error_message && (
                    <p className="mt-1 text-red-600 flex items-center gap-1">
                      <XCircle size={12} />
                      {j.error_message}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
