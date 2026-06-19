"use client";

import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { ShieldAlert } from "lucide-react";
import { platformOpsApi } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageShell } from "@/components/ui/design-system";

export default function ErrorTrackingPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <ErrorTrackingContent />
    </AdminAuthGuard>
  );
}

function ErrorTrackingContent() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["platform-errors"],
    queryFn: () => platformOpsApi.listErrors({ limit: 100 }).then((r) => r.data),
    refetchInterval: 30_000,
  });

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState error={error} onRetry={refetch} />;

  const items = data?.items ?? [];
  const inMemory = (data?.in_memory_errors ?? []) as Array<Record<string, unknown>>;

  return (
    <PageShell>
      <PageHeader
        title="Error Tracking"
        subtitle="Frontend, API, and integration errors"
        icon={ShieldAlert}
      />

      {Object.keys(data?.categories ?? {}).length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {Object.entries(data?.categories ?? {}).map(([cat, count]) => (
            <span key={cat} className="px-3 py-1 bg-gray-100 rounded-full text-xs font-medium">
              {cat}: {count}
            </span>
          ))}
        </div>
      )}

      {inMemory.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-medium text-gray-700 mb-2">Recent API errors (in-memory)</h3>
          <div className="space-y-2">
            {inMemory.slice(0, 10).map((err, i) => (
              <div key={i} className="bg-red-50 border border-red-100 rounded-lg p-3 text-sm">
                <span className="font-mono text-xs text-red-800">
                  {String(err.method)} {String(err.path)} — {String(err.status)}
                </span>
                {typeof err.error_summary === "string" && err.error_summary.length > 0 && (
                  <div className="text-red-700 mt-1">{String(err.error_summary)}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <h3 className="text-sm font-medium text-gray-700 mb-2">Persisted error reports</h3>
      {items.length === 0 ? (
        <EmptyState title="No persisted errors" />
      ) : (
        <div className="space-y-3">
          {items.map((row) => (
            <div key={row.id} className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="flex justify-between gap-2 text-xs text-gray-500">
                <span>{row.source} · {row.path ?? "—"}</span>
                <span>{format(parseISO(row.created_at), "MMM d HH:mm")}</span>
              </div>
              <div className="font-medium text-sm mt-1">{row.message}</div>
              {row.stack_trace && (
                <pre className="mt-2 text-xs bg-gray-50 p-2 rounded overflow-x-auto max-h-32">
                  {row.stack_trace}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </PageShell>
  );
}
