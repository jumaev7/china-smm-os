"use client";

import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Shield } from "lucide-react";
import { platformOpsApi } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageShell } from "@/components/ui/design-system";

export default function AuditLogsPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <AuditLogsContent />
    </AdminAuthGuard>
  );
}

function AuditLogsContent() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["platform-audit-logs"],
    queryFn: () => platformOpsApi.listAuditLogs({ limit: 100 }).then((r) => r.data),
  });

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState error={error} onRetry={refetch} />;

  const items = data?.items ?? [];

  return (
    <PageShell>
      <PageHeader
        title="Audit Logs"
        subtitle="Centralized activity log — login, content, leads, admin actions"
        icon={Shield}
      />
      {items.length === 0 ? (
        <EmptyState title="No audit events yet" description="Actions will appear here as users interact with the platform." />
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Actor</th>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">Resource</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id} className="border-t border-gray-100">
                  <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                    {format(parseISO(row.created_at), "MMM d HH:mm:ss")}
                  </td>
                  <td className="px-4 py-3">
                    {row.actor_type}
                    {row.tenant_id ? ` · tenant` : ""}
                  </td>
                  <td className="px-4 py-3 font-medium">{row.event_type}</td>
                  <td className="px-4 py-3 text-gray-600">
                    {row.resource_type ?? "—"}
                    {row.resource_id ? ` #${row.resource_id.slice(0, 8)}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}
