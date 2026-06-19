"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, ShieldCheck } from "lucide-react";
import { adminAuthApi } from "@/lib/api";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";

const EVENT_TYPES = ["", "login", "logout", "role_check", "permission_check", "user_management"];

export default function AdminAuditPage() {
  const { hasPermission } = useAdminAuth();
  const [eventType, setEventType] = useState("");

  const canView = hasPermission("logs.read");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-audit-logs", eventType],
    queryFn: () =>
      adminAuthApi
        .listAuditLogs({ event_type: eventType || undefined, limit: 100 })
        .then((r) => r.data),
    enabled: canView,
  });

  const { data: security } = useQuery({
    queryKey: ["admin-security-checks"],
    queryFn: () => adminAuthApi.securityChecks().then((r) => r.data),
    enabled: hasPermission("diagnostics.read"),
  });

  if (!canView) {
    return (
      <div className="mx-auto max-w-lg p-8 text-center text-slate-300">
        Auditor or support role with logs.read permission required.
      </div>
    );
  }

  if (isLoading) return <LoadingState label="Loading audit logs…" />;
  if (isError) return <ErrorState message={(error as Error).message} onRetry={() => refetch()} />;

  const logs = data?.items ?? [];

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Admin Audit Logs</h1>
        <p className="mt-1 text-sm text-slate-400">Login, logout, role checks, and permission checks</p>
      </div>

      {security ? (
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="mb-3 flex items-center gap-2">
            <ShieldCheck size={18} className="text-indigo-400" />
            <h2 className="text-lg font-medium text-white">Security Checks</h2>
            <span className="text-sm text-slate-500">
              {security.ok_count}/{security.total} OK
            </span>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {security.checks.map((c) => (
              <div
                key={c.name}
                className={`rounded-lg border px-3 py-2 text-sm ${
                  c.status === "ok"
                    ? "border-emerald-900/50 bg-emerald-950/30 text-emerald-200"
                    : c.status === "warning"
                      ? "border-amber-900/50 bg-amber-950/30 text-amber-200"
                      : "border-red-900/50 bg-red-950/30 text-red-200"
                }`}
              >
                <div className="font-medium">{c.name}</div>
                <div className="text-xs opacity-80">{c.message}</div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FileText size={18} className="text-indigo-400" />
            <h2 className="text-lg font-medium text-white">Audit Events</h2>
            <span className="text-sm text-slate-500">({data?.total ?? 0})</span>
          </div>
          <select
            value={eventType}
            onChange={(e) => setEventType(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-white"
          >
            {EVENT_TYPES.map((t) => (
              <option key={t || "all"} value={t}>
                {t || "All events"}
              </option>
            ))}
          </select>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400">
                <th className="pb-2 pr-3">Time</th>
                <th className="pb-2 pr-3">Admin</th>
                <th className="pb-2 pr-3">Event</th>
                <th className="pb-2 pr-3">Action</th>
                <th className="pb-2">OK</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} className="border-b border-slate-800/60">
                  <td className="py-2 pr-3 text-slate-400">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                  <td className="py-2 pr-3 text-white">{log.admin_email ?? "—"}</td>
                  <td className="py-2 pr-3">{log.event_type}</td>
                  <td className="py-2 pr-3">{log.action}</td>
                  <td className="py-2">{log.success ? "✓" : "✗"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
